//! DownloadManager — 任务状态机与工作线程。
//!
//! 设计红线（ADR-0004）：下载器跑在自己的线程上，状态放在自己的锁里，
//! **绝不**触碰 `AppState` 的互斥锁——40GB 下载期间参数页/日志页照常可用。
//! 任何状态变化都经 `notify` 回调（命令层接到 tauri emit）推**全量**任务
//! 列表；`market.json` 持久化跨重启任务，重启后 Running 一律降级为 Paused
//! （恢复列表、手动续）。

use std::collections::{HashMap, HashSet};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Instant;

use serde::{Deserialize, Serialize};

use super::downloader::{download, part_path, DownloadPlan, Outcome};
use super::store::{load_store, save_store, MarketStore};
use crate::deps::{AppError, AppErrorKind, Deps};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum TaskState {
    Queued,
    Running,
    Paused,
    Done,
    Failed,
}

/// 任务内的单个文件（分片或 mmproj）。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TaskFile {
    pub url: String,
    pub dest: PathBuf,
    pub sha256: Option<String>,
    pub size: u64,
}

/// 一个量化档的完整下载任务（含分片与 mmproj）。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DownloadTask {
    pub id: String,
    pub hub: super::HubKind,
    pub repo: String,
    pub label: String,
    pub files: Vec<TaskFile>,
    pub state: TaskState,
    pub received: u64,
    pub total: u64,
    pub speed_bps: u64,
    pub error: Option<String>,
    pub added_at_ms: u64,
}

/// 一条 llama-bench 实测记录（M5 写入，与任务同文件存储）。
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BenchRecord {
    pub model_path: String,
    pub pp_tps: f64,
    pub tg_tps: f64,
    pub ngl: u32,
    pub benched_at_ms: u64,
}

type Notify = Arc<dyn Fn(&[DownloadTask]) + Send + Sync>;

pub struct DownloadManager {
    state: Arc<Mutex<MarketStore>>,
    /// 每个进行中任务的暂停/取消旗标（工作线程的进度回调逐块检查）。
    flags: Arc<Mutex<HashMap<String, Arc<AtomicBool>>>>,
    /// 已请求取消但任务还在跑的 id：任务收场时删任务 + 清 `.part`。
    pending_cancel: Arc<Mutex<HashSet<String>>>,
    notify: Mutex<Option<Notify>>,
    file: PathBuf,
    /// 下载重试退避毫秒；生产 2000，测试置 0。
    pub backoff_ms: u64,
}

impl DownloadManager {
    pub fn new(file: PathBuf) -> Self {
        Self {
            state: Arc::new(Mutex::new(MarketStore::default())),
            flags: Arc::new(Mutex::new(HashMap::new())),
            pending_cancel: Arc::new(Mutex::new(HashSet::new())),
            notify: Mutex::new(None),
            file,
            backoff_ms: 2000,
        }
    }

    pub fn set_notify(&self, cb: Notify) {
        *self.notify.lock().unwrap() = Some(cb);
    }

    /// 启动加载：读 market.json；上次会话的 Running 降级为 Paused。
    pub fn load(&self, deps: &dyn Deps) {
        let mut store = load_store(deps, &self.file);
        let changed = normalize(&mut store.tasks);
        *self.state.lock().unwrap() = store.clone();
        if changed {
            let _ = save_store(deps, &self.file, &store);
        }
    }

    pub fn tasks(&self) -> Vec<DownloadTask> {
        self.state.lock().unwrap().tasks.clone()
    }

    pub fn benchmarks(&self) -> Vec<BenchRecord> {
        self.state.lock().unwrap().benchmarks.clone()
    }

    pub fn benchmark_for(&self, model_path: &str) -> Option<BenchRecord> {
        self.state
            .lock()
            .unwrap()
            .benchmarks
            .iter()
            .find(|b| b.model_path == model_path)
            .cloned()
    }

    /// 模型被删除时清掉它的实测成绩。
    pub fn remove_benchmark(&self, deps: &dyn Deps, model_path: &str) {
        {
            let mut st = self.state.lock().unwrap();
            st.benchmarks.retain(|b| b.model_path != model_path);
        }
        let _ = self.persist(deps);
        self.announce();
    }

    pub fn add_benchmark(&self, deps: &dyn Deps, rec: BenchRecord) -> Result<(), AppError> {
        {
            let mut st = self.state.lock().unwrap();
            st.benchmarks.retain(|b| b.model_path != rec.model_path);
            st.benchmarks.push(rec);
        }
        let _ = self.persist(deps);
        self.announce();
        Ok(())
    }

    /// 入队一个任务。重复 id（任意状态）被拒绝。
    pub fn enqueue(&self, deps: &dyn Deps, task: DownloadTask) -> Result<(), AppError> {
        {
            let mut st = self.state.lock().unwrap();
            if st.tasks.iter().any(|t| t.id == task.id) {
                return Err(AppError::new(
                    AppErrorKind::MarketFailed,
                    format!("任务已存在：{}", task.id),
                ));
            }
            self.flags
                .lock()
                .unwrap()
                .entry(task.id.clone())
                .or_default();
            st.tasks.push(task);
        }
        let _ = self.persist(deps);
        self.announce();
        Ok(())
    }

    /// 暂停：置旗标（跑动中的任务在下一个块边界停下）。
    pub fn pause(&self, id: &str) {
        if let Some(f) = self.flags.lock().unwrap().get(id) {
            f.store(true, Ordering::SeqCst);
        }
    }

    /// 恢复：Paused/Failed → Queued，清旗标，并拉起工作线程。
    pub fn resume(self: &Arc<Self>, deps: impl Deps + Send + Sync + 'static, id: &str) {
        self.requeue(id);
        self.spawn_worker(deps);
    }

    /// `resume` 的同步半步：状态回 Queued + 清旗标，不起线程（测试用，
    /// 或配合 `run_one` 手动驱动）。
    pub fn requeue(&self, id: &str) {
        {
            let mut st = self.state.lock().unwrap();
            if let Some(t) = st.tasks.iter_mut().find(|t| t.id == id) {
                if t.state == TaskState::Paused || t.state == TaskState::Failed {
                    t.state = TaskState::Queued;
                    t.error = None;
                }
            }
        }
        if let Some(f) = self.flags.lock().unwrap().get(id) {
            f.store(false, Ordering::SeqCst);
        }
        self.announce();
    }

    /// 取消：跑动中的置旗标等收场后删除；未跑的直接删除（含 `.part`）。
    pub fn cancel(self: &Arc<Self>, deps: &dyn Deps, id: &str) {
        let running = self
            .state
            .lock()
            .unwrap()
            .tasks
            .iter()
            .any(|t| t.id == id && t.state == TaskState::Running);
        if running {
            self.pending_cancel.lock().unwrap().insert(id.to_string());
            self.pause(id);
            return;
        }
        if let Some(task) = self.find(id) {
            self.remove_task_files(deps, &task);
        }
        self.remove_task(deps, id);
    }

    /// 起工作线程：线程不断认领 Queued 任务直到队列为空。
    pub fn spawn_worker(self: &Arc<Self>, deps: impl Deps + Send + Sync + 'static) {
        let mgr = Arc::clone(self);
        std::thread::spawn(move || {
            while mgr.run_one(&deps) {}
        });
    }

    /// 认领并同步执行一个 Queued 任务。返回 `false` 表示队列已空。
    /// 测试直接调用它（不起线程）驱动整个状态机。
    pub fn run_one(&self, deps: &dyn Deps) -> bool {
        let Some(task) = self.claim_next() else { return false };
        let flag = self.flags.lock().unwrap().get(&task.id).cloned();
        let mut base: u64 = 0;
        let mut stopped = false; // Paused / Failed 之后不再标 Done

        for file in &task.files {
            // 目标已存在且大小一致：跳过（续传的文件级粒度）。
            if deps.file_size(&file.dest) == Ok(Some(file.size)) {
                base += file.size;
                continue;
            }
            let pause_flag = flag.clone().unwrap_or_default();
            let id = task.id.clone();
            let mut throttle = Throttle::default();
            let plan = DownloadPlan {
                url: file.url.clone(),
                dest: file.dest.clone(),
                expected_sha256: file.sha256.clone(),
                expected_total: Some(file.size),
                backoff_ms: self.backoff_ms,
            };
            match download(deps, &plan, &mut |recv, total| {
                if pause_flag.load(Ordering::SeqCst) {
                    return false;
                }
                if let Some(speed) = throttle.on_progress(recv) {
                    self.update_progress(&id, base + recv, total, speed);
                }
                true
            }) {
                Ok(Outcome::Done) => base += file.size,
                Ok(Outcome::Paused) => {
                    self.set_state(deps, &task.id, TaskState::Paused, None);
                    stopped = true;
                    break;
                }
                Err(e) => {
                    self.set_state(deps, &task.id, TaskState::Failed, Some(e.message));
                    stopped = true;
                    break;
                }
            }
        }

        if !stopped && self.state_of(&task.id) == Some(TaskState::Running) {
            self.set_state(deps, &task.id, TaskState::Done, None);
        }
        if self.pending_cancel.lock().unwrap().remove(&task.id) {
            self.remove_task_files(deps, &task);
            self.remove_task(deps, &task.id);
        }
        self.flags.lock().unwrap().remove(&task.id);
        true
    }

    // ---- internals ----

    fn find(&self, id: &str) -> Option<DownloadTask> {
        self.state.lock().unwrap().tasks.iter().find(|t| t.id == id).cloned()
    }

    fn claim_next(&self) -> Option<DownloadTask> {
        let snapshot = {
            let mut st = self.state.lock().unwrap();
            let t = st.tasks.iter_mut().find(|t| t.state == TaskState::Queued)?;
            t.state = TaskState::Running;
            t.error = None;
            t.clone()
        };
        self.announce();
        Some(snapshot)
    }

    fn update_progress(&self, id: &str, received: u64, total: u64, speed_bps: u64) {
        {
            let mut st = self.state.lock().unwrap();
            let Some(t) = st.tasks.iter_mut().find(|t| t.id == id) else { return };
            t.received = received;
            t.total = total;
            t.speed_bps = speed_bps;
        }
        self.announce();
    }

    fn set_state(&self, deps: &dyn Deps, id: &str, state: TaskState, error: Option<String>) {
        {
            let mut st = self.state.lock().unwrap();
            let Some(t) = st.tasks.iter_mut().find(|t| t.id == id) else { return };
            t.state = state;
            t.error = error;
            if state == TaskState::Done {
                t.received = t.total;
                t.speed_bps = 0;
            }
        }
        let _ = self.persist(deps);
        self.announce();
    }

    fn state_of(&self, id: &str) -> Option<TaskState> {
        self.state.lock().unwrap().tasks.iter().find(|t| t.id == id).map(|t| t.state)
    }

    fn remove_task(&self, deps: &dyn Deps, id: &str) {
        {
            let mut st = self.state.lock().unwrap();
            if let Some(p) = st.tasks.iter().position(|t| t.id == id) {
                st.tasks.remove(p);
            }
        }
        let _ = self.persist(deps);
        self.announce();
    }

    fn remove_task_files(&self, deps: &dyn Deps, task: &DownloadTask) {
        for f in &task.files {
            let _ = deps.remove_file(&f.dest);
            let _ = deps.remove_file(&part_path(&f.dest));
        }
    }

    /// 把当前状态写盘。失败静默：下载继续，下次状态变化再写。
    fn persist(&self, deps: &dyn Deps) -> Result<(), AppError> {
        let st = self.state.lock().unwrap().clone();
        save_store(deps, &self.file, &st)
    }

    fn announce(&self) {
        let tasks = self.tasks();
        if let Some(cb) = self.notify.lock().unwrap().as_ref() {
            cb(&tasks);
        }
    }
}

/// 上次会话的 Running → Paused。返回是否有变化（有则值得重写文件）。
fn normalize(tasks: &mut [DownloadTask]) -> bool {
    let mut changed = false;
    for t in tasks.iter_mut() {
        if t.state == TaskState::Running {
            t.state = TaskState::Paused;
            t.speed_bps = 0;
            changed = true;
        }
    }
    changed
}

/// 进度节流：首块必推，之后每 300ms 推一次，速度按上次推进窗口折算。
#[derive(Default)]
struct Throttle {
    mark: Option<(Instant, u64)>,
}

impl Throttle {
    /// `Some(speed)` = 该推了；`None` = 还没到窗口。
    fn on_progress(&mut self, received: u64) -> Option<u64> {
        let now = Instant::now();
        let Some((t0, b0)) = self.mark else {
            self.mark = Some((now, received));
            return Some(0);
        };
        let dt = now.duration_since(t0);
        if dt.as_millis() < 300 {
            return None;
        }
        let speed = if received >= b0 && !dt.is_zero() {
            ((received - b0) as f64 / dt.as_secs_f64()) as u64
        } else {
            0
        };
        self.mark = Some((now, received));
        Some(speed)
    }
}

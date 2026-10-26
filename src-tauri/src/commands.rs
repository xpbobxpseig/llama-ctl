//! The tauri command surface: every domain operation the frontend can invoke.
//!
//! This module is a thin adapter and nothing else. Each command:
//!
//! 1. takes the `App` out of managed state (Rust holds the truth),
//! 2. calls one function in [`llama_ctl_commands::snapshot`],
//! 3. wraps the result in the [`ipc`] envelope.
//!
//! No domain logic lives here, and no state is cached on this side: the
//! frontend caches form edits locally and re-fetches a Snapshot whenever it
//! needs to know anything. That one-way rule is what keeps "the UI shows
//! applied but the service did not change" impossible.
//!
//! Every command returns `Result<OkPayload, ErrorPayload>` rather than a bare
//! `Result<T, AppError>`, so the frontend can branch on `ok` without guessing
//! which shape came back. See [`ipc`] for the wire contract.
//!
//! **Every command runs on a blocking worker, never on the main thread.** A
//! synchronous (non-`async`) Tauri command executes on the window's main
//! thread, and the whole `AppState` is one mutex — so the old layout froze the
//! window the moment any command waited on that mutex while a long operation
//! (`restart`, `install_update`, a stalled `check_update`) held it. The main
//! thread now only pumps the event loop; a command that has to queue behind a
//! long install merely makes *its own* result late, which is survivable.

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use llama_ctl_commands::ipc::{self, ErrorPayload, OkPayload};
use llama_ctl_commands::snapshot as cmd;
use llama_ctl_core::deps::{AppError, AppErrorKind};
use llama_ctl_core::deps::Deps as _;
use llama_ctl_core::market::{self, DownloadManager, DownloadTask, HubKind, TaskFile};
use llama_ctl_core::persist::Settings;
use llama_ctl_core::real::RealDeps;
use llama_ctl_core::service::StartMode;
use serde::Deserialize;
use tauri::{AppHandle, Emitter, Manager};

/// The authoritative state, shared by every command.
pub struct AppState {
    inner: Mutex<cmd::App>,
}

impl AppState {
    pub fn new(app: cmd::App) -> Self {
        Self { inner: Mutex::new(app) }
    }

    /// Run `f` against the app. A poisoned mutex means a command panicked
    /// mid-write; keep answering anyway, because a dead lock would freeze the
    /// whole UI.
    pub fn with<T>(&self, f: impl FnOnce(&mut cmd::App) -> T) -> T {
        let mut guard = self.inner.lock().unwrap_or_else(|p| p.into_inner());
        f(&mut guard)
    }
}

/// The real `Deps`, injected as managed state so the command layer keeps its
/// `&impl Deps` signature (and so a test could hand it a `FakeDeps` instead).
pub struct DepsHandle {
    deps: RealDeps,
}

impl DepsHandle {
    pub fn new() -> Self {
        Self { deps: RealDeps::new() }
    }
    pub fn deps(&self) -> &RealDeps {
        &self.deps
    }
}

impl Default for DepsHandle {
    fn default() -> Self {
        Self::new()
    }
}

// ---- payloads the frontend sends ----

/// The form: the only thing the frontend owns. Rust never treats it as truth.
pub type FormValues = BTreeMap<String, String>;

#[derive(Debug, Clone, Deserialize)]
pub struct ApplyArgs {
    pub values: FormValues,
    #[serde(default)]
    pub extras: Vec<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct SwitchArgs {
    pub service: String,
    pub values: Option<FormValues>,
    /// Store the abandoned form as a timestamped preset first (Auto backup).
    #[serde(default)]
    pub backup: bool,
}

#[derive(Debug, Clone, Deserialize)]
pub struct PresetArgs {
    pub name: String,
    pub values: FormValues,
}

/// The event names progress streams on. The frontend subscribes once and
/// renders lines as they arrive.
pub const EVENT_RESTART: &str = "llama-ctl://restart-progress";
pub const EVENT_UPDATE: &str = "llama-ctl://update-progress";
/// 模型市场下载进度：payload 是**全量**任务列表（前端零 diff 逻辑）。
pub const EVENT_MARKET: &str = "llama-ctl://download-progress";
/// 实测进度：行流（停服/恢复/llama-bench 日志）。
pub const EVENT_BENCH: &str = "llama-ctl://bench-progress";

/// 下载管理器：独立于 `AppState` 的锁（ADR-0004 红线）。
pub struct MarketHandle(pub Arc<DownloadManager>);

fn hub_kind(s: &str) -> HubKind {
    match s {
        "hf" => HubKind::Hf,
        _ => HubKind::Ms,
    }
}

fn default_limit() -> u32 {
    50
}

#[derive(Debug, Clone, Deserialize)]
pub struct BenchArgs {
    pub model_path: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct LocalDeleteArgs {
    pub model: llama_ctl_core::market::LocalModel,
    /// 当前服务的 --model 值（删除守卫）。
    #[serde(default)]
    pub current_model: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct MarketListArgs {
    pub hub: String,
    #[serde(default)]
    pub query: String,
    #[serde(default = "default_limit")]
    pub limit: u32,
}

#[derive(Debug, Clone, Deserialize)]
pub struct EnqueueFile {
    pub path: String,
    pub size: u64,
    #[serde(default)]
    pub sha256: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct EnqueueArgs {
    pub hub: String,
    pub repo: String,
    pub label: String,
    /// 下载根目录（settings 里的 market.download_root）。
    pub root: String,
    pub files: Vec<EnqueueFile>,
}

fn emit(app: &AppHandle, event: &str, line: &str) {
    // A closed or unsubscribed window is not an error — the operation it was
    // watching continues regardless.
    let _ = app.emit(event, line);
}

// ---- reads ----

/// The whole-state Snapshot. One fetch, everything one screen needs.
#[tauri::command]
pub async fn get_snapshot(
    handle: AppHandle,
    values: Option<FormValues>,
) -> Result<OkPayload, ErrorPayload> {
    run_worker(handle, move |d, a| Ok(cmd::snapshot(d, a, values.as_ref()))).await
}

/// The tail of the selected service's `server.err`, plus the path it came
/// from so the UI can label the region. Costs one file read; the log region
/// polls it, it is not part of every Snapshot.
#[tauri::command]
pub async fn tail_log(handle: AppHandle) -> Result<OkPayload, ErrorPayload> {
    #[derive(serde::Serialize)]
    struct Tail {
        lines: Vec<String>,
        path: Option<String>,
    }
    run_worker(handle, move |d, a| {
        Ok(Tail { lines: cmd::tail_log(d, a), path: cmd::log_path(d, a) })
    })
    .await
}

/// Re-enumerate the NSSM services. Costs one powershell call (~0.6 s), so call
/// it off the frame that paints the dropdown.
#[tauri::command]
pub async fn refresh_services(handle: AppHandle) -> Result<OkPayload, ErrorPayload> {
    run_worker(handle, |d, a| cmd::refresh_services(d, a)).await
}

/// Switch the form to another service, optionally auto-backing-up the edits.
#[tauri::command]
pub async fn switch_service(
    handle: AppHandle,
    args: SwitchArgs,
) -> Result<OkPayload, ErrorPayload> {
    run_worker(handle, move |d, a| {
        cmd::switch_service(d, a, &args.service, args.values.as_ref(), args.backup)
    })
    .await
}

// ---- write-back ----

/// Apply the form: rebuild `AppParameters` and write it back.
#[tauri::command]
pub async fn apply_changes(
    handle: AppHandle,
    args: ApplyArgs,
) -> Result<OkPayload, ErrorPayload> {
    run_worker(handle, move |d, a| cmd::apply(d, a, &args.values, &args.extras)).await
}

/// Revert: discard the form and read the service again. Never writes.
#[tauri::command]
pub async fn revert(handle: AppHandle) -> Result<OkPayload, ErrorPayload> {
    run_worker(handle, |d, a| cmd::revert(d, a)).await
}

// ---- service control ----

/// `sc start` / `sc stop`.
#[tauri::command]
pub async fn service_action(
    handle: AppHandle,
    action: String,
) -> Result<OkPayload, ErrorPayload> {
    run_worker(handle, move |d, a| cmd::service_action(d, a, &action)).await
}

/// Set the boot start mode. `mode` is `StartMode`'s own wire value (`"auto"` /
/// `"manual"` / `"disabled"`), the same spelling the Snapshot returns; an
/// unrecognised one falls back to `manual`, as the domain layer does.
#[tauri::command]
pub async fn set_start_mode(
    handle: AppHandle,
    mode: String,
) -> Result<OkPayload, ErrorPayload> {
    let mode = match mode.as_str() {
        "auto" => StartMode::Auto,
        "disabled" => StartMode::Disabled,
        _ => StartMode::Manual,
    };
    run_worker(handle, move |d, a| cmd::set_start_mode(d, a, mode)).await
}

/// Restart: stop, start, wait for the health probe — streaming one line per
/// step on [`EVENT_RESTART`].
///
/// Runs on a blocking worker: the wait can legitimately take a minute, and
/// doing that on the webview's thread would look like a frozen window.
#[tauri::command]
pub async fn restart(
    handle: AppHandle,
    values: Option<FormValues>,
) -> Result<OkPayload, ErrorPayload> {
    let form = values.unwrap_or_default();
    run_blocking(handle, EVENT_RESTART, move |d, a, sink| {
        cmd::restart(d, a, &form, sink).map(Some)
    })
    .await
}

// ---- presets ----

/// Load a preset into the form. Reads only — the service is untouched.
#[tauri::command]
pub async fn load_preset(handle: AppHandle, name: String) -> Result<OkPayload, ErrorPayload> {
    run_worker(handle, move |d, a| cmd::load_preset(d, a, &name)).await
}

/// Save the form as a preset. `false` when the name already exists.
#[tauri::command]
pub async fn save_preset(handle: AppHandle, args: PresetArgs) -> Result<OkPayload, ErrorPayload> {
    run_worker(handle, move |d, a| cmd::save_preset(d, a, &args.name, &args.values)).await
}

/// Delete a preset.
#[tauri::command]
pub async fn delete_preset(handle: AppHandle, name: String) -> Result<OkPayload, ErrorPayload> {
    run_worker(handle, move |d, a| cmd::delete_preset(d, a, &name)).await
}

// ---- settings ----

/// Persist preferences. A language change returns the new string table.
#[tauri::command]
pub async fn save_settings(
    handle: AppHandle,
    settings: Settings,
) -> Result<OkPayload, ErrorPayload> {
    run_worker(handle, move |d, a| cmd::save_settings(d, a, &settings)).await
}

// ---- updates ----

/// Check for a newer official build. **Never installs** (ADR-0001).
///
/// On a worker: this is two HTTPS round-trips to GitHub, which on a bad route
/// can take tens of seconds — on the main thread that was a frozen window the
/// moment the app opened (the startup auto-check) or the user pressed 检查.
#[tauri::command]
pub async fn check_update(handle: AppHandle) -> Result<OkPayload, ErrorPayload> {
    run_worker(handle, |d, a| cmd::check_update(d, a)).await
}

/// Install the release the last check found, streaming progress on
/// [`EVENT_UPDATE`].
#[tauri::command]
pub async fn install_update(handle: AppHandle) -> Result<OkPayload, ErrorPayload> {
    run_blocking(handle, EVENT_UPDATE, |d, a, sink| {
        cmd::install_update(d, a, sink).map(Some)
    })
    .await
}

/// Startup cleanup of stale download / backup directories.
#[tauri::command]
pub async fn prune_update_dirs(handle: AppHandle) -> Result<OkPayload, ErrorPayload> {
    run_worker(handle, |d, a| Ok(cmd::prune_update_dirs(d, a))).await
}

/// `true` when the form differs semantically from the service — lets the
/// frontend decide whether to offer Revert without a whole snapshot.
#[tauri::command]
pub async fn is_dirty(handle: AppHandle, values: FormValues) -> Result<OkPayload, ErrorPayload> {
    run_worker(handle, move |d, a| Ok(cmd::is_dirty(d, a, &values))).await
}

// ---- market（模型市场）----

/// 市场命令不走 `AppState`：搜索/详情是纯读，下载走 DownloadManager 自己的
/// 锁（ADR-0004）。`run_market` 只借 `DepsHandle` 与 `MarketHandle`。
async fn run_market<T, F>(handle: AppHandle, f: F) -> Result<OkPayload, ErrorPayload>
where
    T: serde::Serialize + Send + 'static,
    F: FnOnce(&RealDeps, &Arc<DownloadManager>) -> Result<T, AppError> + Send + 'static,
{
    let out = tauri::async_runtime::spawn_blocking(move || {
        let d = handle.state::<DepsHandle>();
        let m = handle.state::<MarketHandle>();
        f(d.deps(), &m.0)
    })
    .await
    .unwrap_or_else(|e| Err(AppError::new(AppErrorKind::Refused, format!("worker failed: {e}"))));

    ipc::envelope(out)
}

/// 热门榜：按下载量排序的 GGUF 仓库。
#[tauri::command]
pub async fn market_hot(
    handle: AppHandle,
    hub: String,
    limit: Option<u32>,
) -> Result<OkPayload, ErrorPayload> {
    let kind = hub_kind(&hub);
    let limit = limit.unwrap_or(50);
    run_market(handle, move |d, _| market::hub(kind).hot(d, limit)).await
}

/// 关键词搜索（空查询退化为热门榜）。
#[tauri::command]
pub async fn market_search(
    handle: AppHandle,
    args: MarketListArgs,
) -> Result<OkPayload, ErrorPayload> {
    let kind = hub_kind(&args.hub);
    let query = args.query.trim().to_string();
    let limit = args.limit;
    run_market(handle, move |d, _| {
        if query.is_empty() {
            market::hub(kind).hot(d, limit)
        } else {
            market::hub(kind).search(d, &query, limit)
        }
    })
    .await
}

/// 仓库详情：量化档归组 + gguf 元数据 + gated 标注。
#[tauri::command]
pub async fn market_repo(
    handle: AppHandle,
    hub: String,
    id: String,
) -> Result<OkPayload, ErrorPayload> {
    let kind = hub_kind(&hub);
    run_market(handle, move |d, _| {
        let mut repo = market::hub(kind).detail(d, &id)?;
        let hw = market::detect(d);
        for v in &mut repo.variants {
            let sz = v.total_size + v.mmproj.as_ref().map(|m| m.size).unwrap_or(0);
            v.fit = Some(market::assess(&hw, sz));
        }
        Ok(repo)
    })
    .await
}

/// 当前下载任务全量列表（市场页轮询兜底 + 事件之外的一致性来源）。
#[tauri::command]
pub async fn market_tasks(handle: AppHandle) -> Result<OkPayload, ErrorPayload> {
    run_market(handle, move |_, m| Ok::<_, AppError>(m.tasks())).await
}

/// 入队一个量化档的下载（分片 + mmproj 由前端一次给全），随即起工作线程。
#[tauri::command]
pub async fn market_enqueue(
    handle: AppHandle,
    args: EnqueueArgs,
) -> Result<OkPayload, ErrorPayload> {
    let kind = hub_kind(&args.hub);
    run_market(handle, move |d, m| {
        let dir = market::display_name(&args.repo);
        let files: Vec<TaskFile> = args
            .files
            .iter()
            .map(|f| TaskFile {
                url: market::hub(kind).download_url(&args.repo, &f.path),
                dest: PathBuf::from(&args.root).join(dir).join(&f.path),
                sha256: f.sha256.clone(),
                size: f.size,
            })
            .collect();
        let total = files.iter().map(|f| f.size).sum();
        let task = DownloadTask {
            id: format!("{}:{}:{}", args.hub, args.repo, args.label),
            hub: kind,
            repo: args.repo.clone(),
            label: args.label.clone(),
            received: 0,
            speed_bps: 0,
            state: market::TaskState::Queued,
            error: None,
            added_at_ms: d.now_millis(),
            files,
            total,
        };
        m.enqueue(d, task)?;
        m.spawn_worker(*d);
        Ok(m.tasks())
    })
    .await
}

#[tauri::command]
pub async fn market_pause(handle: AppHandle, id: String) -> Result<OkPayload, ErrorPayload> {
    run_market(handle, move |_, m| {
        m.pause(&id);
        Ok::<_, AppError>(m.tasks())
    })
    .await
}

#[tauri::command]
pub async fn market_resume(handle: AppHandle, id: String) -> Result<OkPayload, ErrorPayload> {
    run_market(handle, move |d, m| {
        m.resume(*d, &id);
        Ok::<_, AppError>(m.tasks())
    })
    .await
}

#[tauri::command]
pub async fn market_cancel(handle: AppHandle, id: String) -> Result<OkPayload, ErrorPayload> {
    run_market(handle, move |d, m| {
        m.cancel(d, &id);
        Ok::<_, AppError>(m.tasks())
    })
    .await
}

/// 实测一个本地模型：停服→bench→恢复，行流走 [`EVENT_BENCH`]，
/// 成绩写入 market.json（同模型覆盖）。
#[tauri::command]
pub async fn bench_run(handle: AppHandle, args: BenchArgs) -> Result<OkPayload, ErrorPayload> {
    let h = handle.clone();
    run_blocking(handle, EVENT_BENCH, move |d, a, sink| {
        let out = cmd::bench_run(d, a, std::path::Path::new(&args.model_path), sink)?;
        let m = h.state::<MarketHandle>();
        m.0.add_benchmark(
            d,
            llama_ctl_core::market::BenchRecord {
                model_path: args.model_path.clone(),
                pp_tps: out.pp_tps,
                tg_tps: out.tg_tps,
                ngl: out.ngl,
                benched_at_ms: d.now_millis(),
            },
        )?;
        Ok(Some(out))
    })
    .await
}

/// 扫描本地模型 + 硬件检测结果 + 实测成绩，市场页「已下载区」一次拉全。
#[tauri::command]
pub async fn local_scan(handle: AppHandle, root: String) -> Result<OkPayload, ErrorPayload> {
    run_market(handle, move |d, m| {
        let hw = market::detect(d);
        let models = market::local::scan(d, std::path::Path::new(&root), &hw)?;
        #[derive(serde::Serialize)]
        struct LocalScan {
            hardware: market::Hardware,
            models: Vec<market::LocalModel>,
            benchmarks: Vec<llama_ctl_core::market::BenchRecord>,
        }
        Ok::<_, AppError>(LocalScan { models, hardware: hw, benchmarks: m.benchmarks() })
    })
    .await
}

/// 删除本地模型：当前服务正在用的拒绝；分片与 mmproj 一起删，实测成绩一并清。
#[tauri::command]
pub async fn local_delete(handle: AppHandle, args: LocalDeleteArgs) -> Result<OkPayload, ErrorPayload> {
    run_market(handle, move |d, m| {
        if market::local::is_current_model(args.current_model.as_deref(), &args.model.path) {
            return Err(AppError::new(
                AppErrorKind::MarketFailed,
                "该模型正被当前服务使用：先在参数页换模型并 Apply，再删除",
            ));
        }
        market::local::delete(d, &args.model)?;
        m.remove_benchmark(d, &args.model.path.to_string_lossy());
        Ok::<_, AppError>(m.tasks())
    })
    .await
}

// ---- the worker path -------------------------------------------------------

/// Run one command's body on a blocking worker.
///
/// The body closes over the managed state inside the worker (Tauri's async
/// commands may not borrow `State` across the `await`), so the signatures here
/// take an [`AppHandle`] instead. A panic in the body surfaces as a `Refused`
/// envelope rather than taking the window down.
async fn run_worker<T, F>(handle: AppHandle, f: F) -> Result<OkPayload, ErrorPayload>
where
    T: serde::Serialize + Send + 'static,
    F: FnOnce(&RealDeps, &mut cmd::App) -> Result<T, AppError> + Send + 'static,
{
    let out = tauri::async_runtime::spawn_blocking(move || {
        let d = handle.state::<DepsHandle>();
        let app = handle.state::<AppState>();
        app.with(|a| f(d.deps(), a))
    })
    .await
    .unwrap_or_else(|e| Err(AppError::new(AppErrorKind::Refused, format!("worker failed: {e}"))));

    ipc::envelope(out)
}

/// [`run_worker`] plus a progress sink that streams one line per step.
///
/// The command returns `Option<T>` so one that yields a snapshot and one that
/// reports only through its log can share this path.
async fn run_blocking<T>(
    handle: AppHandle,
    event: &'static str,
    f: impl FnOnce(&RealDeps, &mut cmd::App, &mut dyn FnMut(&str)) -> Result<Option<T>, AppError>
        + Send
        + 'static,
) -> Result<OkPayload, ErrorPayload>
where
    T: serde::Serialize + Send + 'static,
{
    let out = tauri::async_runtime::spawn_blocking(move || {
        let d = handle.state::<DepsHandle>();
        let app = handle.state::<AppState>();
        let mut sink = |line: &str| emit(&handle, event, line);
        app.with(|a| f(d.deps(), a, &mut sink))
    })
    .await
    .unwrap_or_else(|e| Err(AppError::new(AppErrorKind::Refused, format!("worker failed: {e}"))));

    match out {
        Ok(Some(v)) => Ok(OkPayload::new(&v)),
        Ok(None) => Ok(OkPayload::new(&serde_json::Value::Null)),
        Err(e) => Err(ErrorPayload::new(e)),
    }
}

/// The command list, for `invoke_handler`. Adding a command here is the only
/// thing needed to expose it.
pub fn handlers() -> impl Fn(tauri::ipc::Invoke<tauri::Wry>) -> bool + Send + Sync + 'static {
    tauri::generate_handler![
        get_snapshot,
        tail_log,
        refresh_services,
        switch_service,
        apply_changes,
        revert,
        service_action,
        set_start_mode,
        restart,
        load_preset,
        save_preset,
        delete_preset,
        save_settings,
        check_update,
        install_update,
        prune_update_dirs,
        is_dirty,
        market_hot,
        market_search,
        market_repo,
        market_tasks,
        market_enqueue,
        market_pause,
        market_resume,
        market_cancel,
        bench_run,
        local_scan,
        local_delete,
    ]
}

/// Kept so the wire types stay visibly serialisable: `OkPayload` /
/// `ErrorPayload` are what the frontend parses.
#[allow(dead_code)]
fn _wire_types_are_serializable() {
    fn is<T: serde::Serialize>() {}
    is::<OkPayload>();
    is::<ErrorPayload>();
}

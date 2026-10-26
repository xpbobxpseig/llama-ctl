//! M3 集成测试：DownloadManager 状态机（入队/暂停/恢复/取消/失败/持久化/
//! 启动降级），全部经 `FakeDeps` + 同步 `run_one` 驱动，不起线程。

use std::path::Path;
use std::sync::atomic::AtomicUsize;
use std::sync::Arc;

use llama_ctl_core::fake::FakeDeps;
use llama_ctl_core::market::manager::{DownloadManager, DownloadTask, TaskFile, TaskState};
use llama_ctl_core::market::store::{load_store, MarketStore};
use llama_ctl_core::market::HubKind;

const URL: &str = "https://modelscope.cn/models/Qwen/Qwen3-0.6B-GGUF/resolve/master/f.gguf";
const DEST: &str = r"F:\AI_Model\Qwen3-0.6B-GGUF\f.gguf";
const STORE: &str = r"C:\store\market.json";

fn payload(len: usize) -> Vec<u8> {
    (0..len).map(|i| (i % 251) as u8).collect()
}

fn sha256_hex(bytes: &[u8]) -> String {
    use sha2::Digest;
    let mut h = sha2::Sha256::new();
    h.update(bytes);
    h.finalize().iter().map(|b| format!("{b:02x}")).collect()
}

fn task(data: &[u8]) -> DownloadTask {
    DownloadTask {
        id: "ms:Qwen/Qwen3-0.6B-GGUF:Q8_0".into(),
        hub: HubKind::Ms,
        repo: "Qwen/Qwen3-0.6B-GGUF".into(),
        label: "Q8_0".into(),
        files: vec![TaskFile {
            url: URL.into(),
            dest: DEST.into(),
            sha256: Some(sha256_hex(data)),
            size: data.len() as u64,
        }],
        state: TaskState::Queued,
        received: 0,
        total: data.len() as u64,
        speed_bps: 0,
        error: None,
        added_at_ms: 1,
    }
}

#[test]
fn enqueue_run_done_and_persisted() {
    let data = payload(5000);
    let deps = FakeDeps::new().with_http_range(URL, data.clone());
    let mut mgr = DownloadManager::new(STORE.into());
    mgr.backoff_ms = 0;
    let notify_hits = Arc::new(AtomicUsize::new(0));
    let hits = Arc::clone(&notify_hits);
    mgr.set_notify(Arc::new(move |_| {
        hits.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
    }));

    mgr.enqueue(&deps, task(&data)).unwrap();
    assert!(mgr.run_one(&deps));
    assert_eq!(mgr.tasks()[0].state, TaskState::Done);
    assert_eq!(mgr.tasks()[0].received, data.len() as u64);
    assert_eq!(deps.file(DEST.as_ref()).unwrap(), data);
    // market.json 落了盘且任务为 Done
    let store: MarketStore = load_store(&deps, STORE.as_ref());
    assert_eq!(store.tasks[0].state, TaskState::Done);
    assert!(notify_hits.load(std::sync::atomic::Ordering::SeqCst) >= 2);
    // 队列空了
    assert!(!mgr.run_one(&deps));
}

#[test]
fn pause_mid_download_then_resume() {
    // 300KB > CHUNK(256KB)：第一块之后才会检查到暂停旗标
    let data = payload(300 * 1024);
    let deps = FakeDeps::new().with_http_range(URL, data.clone());
    let mut mgr = DownloadManager::new(STORE.into());
    mgr.backoff_ms = 0;
    let t = task(&data);
    mgr.enqueue(&deps, t.clone()).unwrap();

    mgr.pause(&t.id);
    assert!(mgr.run_one(&deps));
    assert_eq!(mgr.tasks()[0].state, TaskState::Paused);
    // .part 保留且不足全量
    let part_size = deps.file(Path::new(&format!("{DEST}.part"))).unwrap().len();
    assert!(part_size < data.len(), "part={part_size}");

    mgr.requeue(&t.id);
    assert!(mgr.run_one(&deps));
    assert_eq!(mgr.tasks()[0].state, TaskState::Done);
    assert_eq!(deps.file(DEST.as_ref()).unwrap(), data);
}

#[test]
fn cancel_running_removes_task_and_part() {
    let data = payload(300 * 1024);
    let deps = FakeDeps::new().with_http_range(URL, data.clone());
    let mut inner = DownloadManager::new(STORE.into());
    inner.backoff_ms = 0;
    let mgr = Arc::new(inner);
    let t = task(&data);

    // 未运行：直接删除
    mgr.enqueue(&deps, t.clone()).unwrap();
    mgr.cancel(&deps, &t.id);
    assert!(mgr.tasks().is_empty());
    assert!(deps.file(DEST.as_ref()).is_none());

    // 跑到一半（Paused、.part 存在）：取消要连 .part 一起清
    mgr.enqueue(&deps, t.clone()).unwrap();
    mgr.pause(&t.id);
    mgr.run_one(&deps);
    assert_eq!(mgr.tasks()[0].state, TaskState::Paused);
    assert!(deps.file(Path::new(&format!("{DEST}.part"))).is_some());
    mgr.cancel(&deps, &t.id);
    assert!(mgr.tasks().is_empty());
    assert!(deps.file(Path::new(&format!("{DEST}.part"))).is_none());
    assert!(deps.file(DEST.as_ref()).is_none());
}

#[test]
fn failed_download_persists_error() {
    let data = payload(100);
    let deps = FakeDeps::new(); // URL 未脚本化 → 网络错误 → 重试耗尽
    let mut mgr = DownloadManager::new(STORE.into());
    mgr.backoff_ms = 0;
    let mut t = task(&data);
    t.files[0].size = 100; // 与 expected_total 一致
    mgr.enqueue(&deps, t).unwrap();
    // backoff_ms 默认 2000ms，10 次重试会睡很久 → 这里直接接受耗时，
    // 但为了测试速度改走无重试路径：预期错误信息包含「重试」
    let state = mgr.tasks()[0].state;
    let _ = mgr.run_one(&deps);
    let after = &mgr.tasks()[0];
    assert_eq!(after.state, TaskState::Failed);
    assert!(after.error.as_deref().unwrap_or_default().contains("重试"));
    assert_eq!(state, TaskState::Queued);
}

#[test]
fn startup_normalizes_running_to_paused() {
    let data = payload(10);
    let raw = format!(
        r#"{{"tasks":[{{"id":"ms:R:Q8_0","hub":"ms","repo":"R","label":"Q8_0",
        "files":[{{"url":"{URL}","dest":"F:/AI_Model/R/f.gguf","sha256":null,"size":10}}],
        "state":"running","received":5,"total":10,"speed_bps":999,"error":null,"added_at_ms":1}}],
        "benchmarks":[]}}"#
    );
    let deps = FakeDeps::new()
        .with_http_range(URL, data)
        .with_file(STORE, raw.into_bytes());
    let mut mgr = DownloadManager::new(STORE.into());
    mgr.backoff_ms = 0;
    mgr.load(&deps);
    assert_eq!(mgr.tasks()[0].state, TaskState::Paused);
    // 重写回文件
    let store: MarketStore = load_store(&deps, STORE.as_ref());
    assert_eq!(store.tasks[0].state, TaskState::Paused);
    assert_eq!(store.tasks[0].speed_bps, 0);
}

#[test]
fn completed_files_are_skipped_on_resume() {
    let data = payload(5000);
    let deps = FakeDeps::new()
        .with_http_range(URL, data[..2500].to_vec())
        .with_file(DEST, data.clone()); // 第一个（也是唯一）文件已在盘上且大小一致
    let mut mgr = DownloadManager::new(STORE.into());
    mgr.backoff_ms = 0;
    mgr.enqueue(&deps, task(&data)).unwrap();
    assert!(mgr.run_one(&deps));
    assert_eq!(mgr.tasks()[0].state, TaskState::Done);
    // 没有发起任何下载
    assert!(deps
        .calls()
        .iter()
        .all(|c| !matches!(c, llama_ctl_core::fake::Call::HttpOpenRange { .. })));
}

#[test]
fn duplicate_enqueue_rejected() {
    let data = payload(10);
    let deps = FakeDeps::new();
    let mut mgr = DownloadManager::new(STORE.into());
    mgr.backoff_ms = 0;
    mgr.enqueue(&deps, task(&data)).unwrap();
    let e = mgr.enqueue(&deps, task(&data)).unwrap_err();
    assert!(e.message.contains("已存在"));
}

#[test]
fn benchmark_records_replaced_per_model() {
    let deps = FakeDeps::new();
    let mut mgr = DownloadManager::new(STORE.into());
    mgr.backoff_ms = 0;
    let rec = llama_ctl_core::market::BenchRecord {
        model_path: DEST.into(),
        pp_tps: 2234.0,
        tg_tps: 43.5,
        ngl: 99,
        benched_at_ms: 7,
    };
    mgr.add_benchmark(&deps, rec.clone()).unwrap();
    mgr.add_benchmark(&deps, rec.clone()).unwrap(); // 同模型覆盖
    assert_eq!(mgr.benchmarks().len(), 1);
    assert_eq!(mgr.benchmark_for(DEST).unwrap().tg_tps, 43.5);
}

#[test]
fn enqueue_prechecks_disk_space_and_states_the_gap() {
    let data = payload(5000);
    // 剩余 1KB < 需要 5000B：直接拒绝，错误里明示需要 / 剩余 / 缺口，且不入队
    let deps = FakeDeps::new()
        .with_http_range(URL, data.clone())
        .with_disk_free(DEST, Some(1024));
    let mut mgr = DownloadManager::new(STORE.into());
    mgr.backoff_ms = 0;
    let err = mgr.enqueue(&deps, task(&data)).unwrap_err();
    assert!(err.message.contains("5000"), "错误给出需要空间：{}", err.message);
    assert!(err.message.contains("1024"), "错误给出剩余空间：{}", err.message);
    assert!(err.message.contains("磁盘空间不足"), "错误点明原因：{}", err.message);
    assert!(mgr.tasks().is_empty(), "被拒的任务绝不入队");

    // 剩余充足：照常入队
    let deps_ok = FakeDeps::new()
        .with_http_range(URL, data.clone())
        .with_disk_free(DEST, Some(1 << 40));
    mgr.enqueue(&deps_ok, task(&data)).unwrap();
    assert_eq!(mgr.tasks().len(), 1);

    // 卷不可知（None）：不拦——口径拿不准不该变成硬错误
    let mut mgr2 = DownloadManager::new(STORE.into());
    let deps_unknown = FakeDeps::new().with_http_range(URL, data.clone());
    mgr2.enqueue(&deps_unknown, task(&data)).unwrap();
    assert_eq!(mgr2.tasks().len(), 1);
}

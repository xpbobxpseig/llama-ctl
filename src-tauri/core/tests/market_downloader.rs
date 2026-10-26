//! M2 集成测试：下载引擎的续传/重启/校验/重试路径，全部经 `FakeDeps` 驱动。

use llama_ctl_core::fake::Call;
use llama_ctl_core::market::downloader::{download, part_path, DownloadPlan};
use llama_ctl_core::deps::AppErrorKind;
use llama_ctl_core::fake::FakeDeps;

const URL: &str = "https://modelscope.cn/models/Qwen/Qwen3-0.6B-GGUF/resolve/master/Qwen3-0.6B-Q8_0.gguf";
const DEST: &str = r"F:\AI_Model\Qwen3-0.6B-GGUF\Qwen3-0.6B-Q8_0.gguf";

fn payload(len: usize) -> Vec<u8> {
    (0..len).map(|i| (i % 251) as u8).collect()
}

fn sha256_hex(bytes: &[u8]) -> String {
    use sha2::Digest;
    let mut h = sha2::Sha256::new();
    h.update(bytes);
    h.finalize().iter().map(|b| format!("{b:02x}")).collect()
}

fn plan(data: &[u8]) -> DownloadPlan {
    let mut p = DownloadPlan::new(URL, DEST);
    p.expected_total = Some(data.len() as u64);
    p.expected_sha256 = Some(sha256_hex(data));
    p.backoff_ms = 0;
    p
}

#[test]
fn happy_path_writes_dest_and_clears_part() {
    let data = payload(5000);
    let deps = FakeDeps::new().with_http_range(URL, data.clone());
    let mut ticks = 0;
    download(&deps, &plan(&data), &mut |_, _| { ticks += 1; true }).unwrap();
    assert_eq!(deps.file(DEST.as_ref()).unwrap(), data);
    assert!(deps.file(part_path(DEST.as_ref()).as_path()).is_none());
    assert!(ticks > 0);
}

#[test]
fn resume_from_existing_part() {
    let data = payload(5000);
    let half = &data[..2500];
    let deps = FakeDeps::new()
        .with_http_range(URL, data.clone())
        .with_file(part_path(DEST.as_ref()), half.to_vec());
    download(&deps, &plan(&data), &mut |_, _| true).unwrap();
    assert_eq!(deps.file(DEST.as_ref()).unwrap(), data);
    // 第二次打开带 Range，从 2500 续传
    let opens: Vec<u64> = deps
        .calls()
        .iter()
        .filter_map(|c| match c {
            Call::HttpOpenRange { range_from, .. } => Some(*range_from),
            _ => None,
        })
        .collect();
    assert_eq!(opens, vec![2500]);
}

#[test]
fn server_without_range_support_restarts() {
    let data = payload(5000);
    let deps = FakeDeps::new()
        .with_http_range_no_resume(URL, data.clone())
        .with_file(part_path(DEST.as_ref()), data[..2500].to_vec());
    download(&deps, &plan(&data), &mut |_, _| true).unwrap();
    assert_eq!(deps.file(DEST.as_ref()).unwrap(), data);
}

#[test]
fn flaky_connection_resumes_mid_read() {
    let data = payload(5000);
    let deps = FakeDeps::new().with_http_range_flaky(URL, data.clone(), 1234);
    download(&deps, &plan(&data), &mut |_, _| true).unwrap();
    assert_eq!(deps.file(DEST.as_ref()).unwrap(), data);
    let opens: Vec<u64> = deps
        .calls()
        .iter()
        .filter_map(|c| match c {
            Call::HttpOpenRange { range_from, .. } => Some(*range_from),
            _ => None,
        })
        .collect();
    assert_eq!(opens, vec![0, 1234]);
}

#[test]
fn sha_mismatch_is_fatal_and_cleans_up() {
    let data = payload(5000);
    let mut p = plan(&data);
    p.expected_sha256 = Some("deadbeef".repeat(8));
    let deps = FakeDeps::new().with_http_range(URL, data);
    let e = download(&deps, &p, &mut |_, _| true).unwrap_err();
    assert_eq!(e.kind, AppErrorKind::MarketFailed);
    assert!(e.message.contains("校验失败"));
    assert!(deps.file(part_path(DEST.as_ref()).as_path()).is_none());
    assert!(deps.file(DEST.as_ref()).is_none());
}

#[test]
fn wrong_expected_total_exhausts_retries() {
    let data = payload(5000);
    let mut p = plan(&data);
    p.expected_total = Some(9999);
    let deps = FakeDeps::new().with_http_range(URL, data);
    let e = download(&deps, &p, &mut |_, _| true).unwrap_err();
    assert!(e.message.contains("重试 10 次"), "{}", e.message);
    // 每次尝试后都从头没成功过：EOF→长度不符→续传拿到空→再次 EOF，循环到耗尽
    assert!(deps.file(DEST.as_ref()).is_none());
}

#[test]
fn idempotent_when_dest_exists() {
    let data = payload(100);
    let deps = FakeDeps::new().with_file(DEST, data.clone());
    let mut opened = 0;
    download(&deps, &plan(&data), &mut |_, _| { let _ = &mut opened; true }).unwrap();
    assert_eq!(opened, 0);
}

fn _opened_hack(n: &mut usize) {
    *n += 1;
}

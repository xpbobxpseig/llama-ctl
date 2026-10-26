//! 真网下载冒烟（默认忽略）：`cargo test --test market_real -- --ignored`
//! 验证生产链路：302→CDN 重定向、Range、逐块落盘。约 639MB / ~20s。

use llama_ctl_core::market::downloader::{download, DownloadPlan};
use llama_ctl_core::real::RealDeps;

#[test]
#[ignore]
fn real_ms_download() {
    let deps = RealDeps::new();
    let dest = std::env::temp_dir().join("llama-ctl-real-dl.gguf");
    let _ = std::fs::remove_file(&dest);
    let mut plan = DownloadPlan::new(
        "https://modelscope.cn/models/Qwen/Qwen3-0.6B-GGUF/resolve/master/Qwen3-0.6B-Q8_0.gguf",
        &dest,
    );
    plan.backoff_ms = 1000;
    let mut ticks = 0;
    download(&deps, &plan, &mut |_, _| { ticks += 1; true }).unwrap();
    assert!(std::fs::metadata(&dest).unwrap().len() > 600_000_000);
    std::fs::remove_file(&dest).ok();
}

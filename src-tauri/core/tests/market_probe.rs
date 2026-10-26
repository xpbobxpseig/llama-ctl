//! 真网探针（默认忽略）：与生产完全相同的 ureq + MsHub/HfHub 路径，
//! 把真实错误抓出来。`cargo test --test market_probe -- --ignored --nocapture`

use llama_ctl_core::deps::Deps as _;
use llama_ctl_core::market::{hub, HubKind};
use llama_ctl_core::real::RealDeps;

#[test]
#[ignore]
fn probe_ms_hot() {
    let d = RealDeps::new();
    match hub(HubKind::Ms).hot(&d, 5) {
        Ok(list) => println!("MS OK: {} 条, 第一条 {:?}", list.len(), list.first().map(|r| &r.id)),
        Err(e) => panic!("MS hot 失败: kind={:?} msg={}", e.kind, e.message),
    }
}

#[test]
#[ignore]
fn probe_hf_hot() {
    let d = RealDeps::new();
    match hub(HubKind::Hf).hot(&d, 5) {
        Ok(list) => println!("HF OK: {} 条", list.len()),
        Err(e) => panic!("HF hot 失败: kind={:?} msg={}", e.kind, e.message),
    }
}

#[test]
#[ignore]
fn probe_raw_put() {
    let d = RealDeps::new();
    match d.http_request(
        "PUT",
        "https://modelscope.cn/api/v1/dolphin/models",
        Some(r#"{"PageSize":3,"PageNumber":1,"SortBy":"DownloadsCount"}"#),
    ) {
        Ok(b) => println!("RAW PUT OK: {} bytes, head: {}", b.len(), String::from_utf8_lossy(&b[..b.len().min(120)])),
        Err(e) => panic!("RAW PUT 失败: {:?}", e),
    }
}

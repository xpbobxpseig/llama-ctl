//! M1 集成测试：Hub 双源经 `FakeDeps` 驱动，锁定 URL 契约与解析/归组行为。

use llama_ctl_core::deps::{AppErrorKind, DepsError, DepsErrorKind};
use llama_ctl_core::fake::{Call, FakeDeps};
use llama_ctl_core::market::{hub, HubKind};

fn net_err(msg: &str) -> DepsError {
    DepsError::new(DepsErrorKind::Network, msg.to_string())
}

const HF_LIST: &str = r#"[
    {"id":"unsloth/Qwen3.8-27B-GGUF","downloads":5857773,"likes":210,"pipeline_tag":"text-generation"},
    {"id":"Qwen/Qwen3-0.6B-GGUF","downloads":120000,"likes":88}
]"#;

const HF_DETAIL: &str = r#"{
    "id":"unsloth/Qwen3.8-27B-GGUF","downloads":5857773,"gated":"manual",
    "gguf":{"total":26955292672,"architecture":"qwen3","context_length":40960}
}"#;

const HF_TREE: &str = r#"[
    {"type":"file","path":"README.md","size":1024},
    {"type":"file","path":"Qwen3.8-27B-UD-IQ1_S.gguf","size":6192222208,"lfs":{"oid":"sha256:aa11","size":6192222208}},
    {"type":"file","path":"Qwen3.8-27B-Q4_K_M-00001-of-00002.gguf","size":15000000000,"lfs":{"oid":"sha256:bb22","size":15000000000}},
    {"type":"file","path":"Qwen3.8-27B-Q4_K_M-00002-of-00002.gguf","size":12000000000,"lfs":{"oid":"sha256:cc33","size":12000000000}},
    {"type":"file","path":"mmproj-Qwen3.8-27B-f16.gguf","size":931145952,"lfs":{"oid":"sha256:dd44","size":931145952}}
]"#;

const MS_PAGE: &str = r#"{"Success":true,"Data":{"Model":{"TotalCount":3215,"Models":[
    {"Path":"Qwen","Name":"Qwen3-0.6B-GGUF","Downloads":120000,"Stars":88,"LicenseName":"Apache-2.0","Libraries":["gguf"],"StorageSize":1300000000},
    {"Path":"someorg","Name":"PytorchOnly","Downloads":99999,"Libraries":["pytorch"]}
]}}}"#;

const MS_FILES: &str = r#"{"Success":true,"Data":{"Files":[
    {"Path":"README.md","Size":900,"Sha256":null},
    {"Path":"Qwen3-0.6B-Q8_0.gguf","Size":639446688,"Sha256":"9465e63a","IsLFS":true}
]}}"#;

#[test]
fn hf_search_hits_gguf_filtered_url_and_parses() {
    let url = "https://huggingface.co/api/models?filter=gguf&sort=downloads&direction=-1&limit=50&search=qwen3%20gguf";
    let deps = FakeDeps::new().with_http_req("GET", url, Ok(HF_LIST.as_bytes().to_vec()));
    let out = hub(HubKind::Hf).search(&deps, "qwen3 gguf", 50).unwrap();
    assert_eq!(out.len(), 2);
    let top = &out[0];
    assert_eq!(top.id, "unsloth/Qwen3.8-27B-GGUF");
    assert_eq!(top.downloads, 5857773);
    assert_eq!(top.params_b, Some(27.0));
    // 请求被记录，且没有任何子进程 spawn
    assert_eq!(deps.spawn_count(), 0);
}

#[test]
fn hf_detail_builds_variants_gated_and_meta() {
    let base = "https://huggingface.co/api/models/unsloth/Qwen3.8-27B-GGUF";
    let deps = FakeDeps::new()
        .with_http_req("GET", &format!("{base}?blobs=true"), Ok(HF_DETAIL.as_bytes().to_vec()))
        .with_http_req(
            "GET",
            &format!("{base}/tree/main?recursive=true"),
            Ok(HF_TREE.as_bytes().to_vec()),
        );
    let d = hub(HubKind::Hf).detail(&deps, "unsloth/Qwen3.8-27B-GGUF").unwrap();
    assert!(d.gated);
    let gguf = d.gguf.unwrap();
    assert_eq!(gguf.total_params, Some(26955292672));
    assert_eq!(gguf.context_length, Some(40960));
    // IQ1_S(6.2G) 在前，Q4_K_M 分片组(27G) 在后
    assert_eq!(d.variants.len(), 2);
    assert_eq!(d.variants[0].label, "UD-IQ1_S");
    assert_eq!(d.variants[1].label, "Q4_K_M");
    assert!(d.variants[1].is_sharded);
    assert_eq!(d.variants[1].files[0].sha256.as_deref(), Some("bb22"));
    for v in &d.variants {
        assert!(v.mmproj.is_some());
    }
}

#[test]
fn hf_network_error_maps_to_market_failed() {
    let deps = FakeDeps::new(); // 未脚本化 → Network 错
    let e = hub(HubKind::Hf).hot(&deps, 50).unwrap_err();
    assert_eq!(e.kind, AppErrorKind::MarketFailed);
}

#[test]
fn ms_hot_sorts_by_downloadscount_and_filters_client_side() {
    let url = "https://modelscope.cn/api/v1/dolphin/models";
    let deps = FakeDeps::new().with_http_req("PUT", url, Ok(MS_PAGE.as_bytes().to_vec()));
    let out = hub(HubKind::Ms).hot(&deps, 50).unwrap();
    assert_eq!(out.len(), 1); // pytorch-only 被客户端过滤
    assert_eq!(out[0].id, "Qwen/Qwen3-0.6B-GGUF");
    // 请求体带排序参数
    let body = deps
        .calls()
        .iter()
        .filter_map(|c| match c {
            Call::HttpRequest { url, body, .. } if url.ends_with("/dolphin/models") => {
                Some(body.clone())
            }
            _ => None,
        })
        .next()
        .flatten()
        .expect("PUT dolphin call recorded");
    assert!(body.contains("\"SortBy\":\"DownloadsCount\""), "body={body}");
    assert!(
    body.contains("\"Name\":\"gguf\""),
    "热榜必须带 gguf 搜索词，否则全站榜头部是 pytorch 语音模型，过滤后为空：body={body}"
    );
}

#[test]
fn ms_search_stops_when_no_new_results() {
    // TotalCount 很大但每页都返回同样 1 条有效数据 → 翻页在无新增处停住
    let url = "https://modelscope.cn/api/v1/dolphin/models";
    let deps = FakeDeps::new().with_http_req("PUT", url, Ok(MS_PAGE.as_bytes().to_vec()));
    let out = hub(HubKind::Ms).search(&deps, "qwen", 50).unwrap();
    assert_eq!(out.len(), 1);
    let put_calls = deps
        .calls()
        .iter()
        .filter(|c| matches!(c, llama_ctl_core::fake::Call::HttpRequest { method, .. } if method == "PUT"))
        .count();
    assert_eq!(put_calls, 2, "第 2 页无新增后停止，不再第 3 页");
}

#[test]
fn ms_error_payload_surfaces_message() {
    let url = "https://modelscope.cn/api/v1/dolphin/models";
    let body = r#"{"Code":10010202002,"Message":"参数错误：oneof","Success":false}"#.as_bytes().to_vec();
    let deps = FakeDeps::new().with_http_req("PUT", url, Ok(body));
    let e = hub(HubKind::Ms).hot(&deps, 50).unwrap_err();
    assert_eq!(e.kind, AppErrorKind::MarketFailed);
    assert!(e.message.contains("oneof"));
}

#[test]
fn ms_detail_maps_sha256() {
    let url = "https://modelscope.cn/api/v1/models/Qwen/Qwen3-0.6B-GGUF/repo/files?Revision=master&Root=";
    let deps = FakeDeps::new().with_http_req("GET", url, Ok(MS_FILES.as_bytes().to_vec()));
    let d = hub(HubKind::Ms).detail(&deps, "Qwen/Qwen3-0.6B-GGUF").unwrap();
    assert_eq!(d.variants.len(), 1);
    let v = &d.variants[0];
    assert_eq!(v.label, "Q8_0");
    assert_eq!(v.total_size, 639446688);
    assert_eq!(v.files[0].sha256.as_deref(), Some("9465e63a"));
    assert!(!d.gated);
}

#[test]
fn download_urls_are_resolve_forms() {
    assert_eq!(
        hub(HubKind::Hf).download_url("unsloth/Qwen3.8-27B-GGUF", "model.gguf"),
        "https://huggingface.co/unsloth/Qwen3.8-27B-GGUF/resolve/main/model.gguf"
    );
    assert_eq!(
        hub(HubKind::Ms).download_url("Qwen/Qwen3-0.6B-GGUF", "Qwen3-0.6B-Q8_0.gguf"),
        "https://modelscope.cn/models/Qwen/Qwen3-0.6B-GGUF/resolve/master/Qwen3-0.6B-Q8_0.gguf"
    );
}

#[test]
fn unscripted_url_is_a_clean_network_error() {
    let deps = FakeDeps::new();
    let e = hub(HubKind::Ms)
        .detail(&deps, "nope/nope")
        .unwrap_err();
    assert_eq!(e.kind, AppErrorKind::MarketFailed);
    assert!(!e.message.is_empty());
    let _ = net_err("unused helper keeps signature documented");
}

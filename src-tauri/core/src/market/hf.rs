//! HuggingFace Hub 适配。端点与字段形状全部来自 2026-10-25 本机实测：
//! 列表是裸数组；`filter=gguf` 才是 GGUF 过滤（`library=gguf` 被静默忽略）；
//! 详情 `?blobs=true` 带 gguf 元数据块；文件清单走 tree 接口，`lfs.oid` 即
//! sha256；`gated` 可能是 bool 或字符串。

use serde::Deserialize;
use serde_json::Value;

use super::hub::{
    dedup_files, display_name, group_files, market_err, parse_err, url_encode, GgufMeta, Hub,
    HubKind, MarketFile, RepoDetail, RepoSummary,
};
use crate::deps::{AppError, Deps};

pub struct HfHub;

const NAME: &str = "HuggingFace";

#[derive(Deserialize, Clone)]
struct HfRepo {
    id: String,
    #[serde(default)]
    downloads: u64,
    #[serde(default)]
    likes: u64,
    #[serde(default)]
    pipeline_tag: Option<String>,
    #[serde(default)]
    gated: Option<Value>,
}

#[derive(Deserialize)]
struct HfDetail {
    id: String,
    #[serde(default)]
    downloads: u64,
    #[serde(default)]
    gated: Option<Value>,
    #[serde(default)]
    gguf: Option<HfGguf>,
}

#[derive(Deserialize)]
struct HfGguf {
    #[serde(default)]
    architecture: Option<String>,
    #[serde(default)]
    context_length: Option<u64>,
    #[serde(default)]
    total: Option<u64>,
}

#[derive(Deserialize)]
struct HfTreeItem {
    #[serde(rename = "type")]
    kind: String,
    path: String,
    #[serde(default)]
    size: u64,
    #[serde(default)]
    lfs: Option<HfLfs>,
}

#[derive(Deserialize)]
struct HfLfs {
    #[serde(default)]
    oid: Option<String>,
}

fn is_gated(v: &Option<Value>) -> bool {
    match v {
        Some(Value::Bool(true)) => true,
        Some(Value::String(s)) => s == "auto" || s == "manual",
        _ => false,
    }
}

/// 非文本生成类任务不收录（「LLM 为主」，与 ms.rs 同一张词表）。
fn non_llm_task(tag: &Option<String>) -> bool {
    const NON_LLM: [&str; 6] = [
        "text-to-image",
        "image-text-to-text",
        "object-detection",
        "automatic-speech-recognition",
        "text-to-speech",
        "any-to-any",
    ];
    tag.as_deref()
        .map(|t| NON_LLM.contains(&t.to_ascii_lowercase().as_str()))
        .unwrap_or(false)
}

fn summary(hub_kind: HubKind, r: HfRepo) -> RepoSummary {
    let name = display_name(&r.id).to_string();
    RepoSummary {
        hub: hub_kind,
        params_b: super::hub::params_from_name(&name),
        gated: is_gated(&r.gated),
        id: r.id,
        name,
        downloads: r.downloads,
        likes: r.likes,
        license: None,
        task: r.pipeline_tag,
        size_hint: None,
    }
}

fn get(deps: &dyn Deps, url: &str) -> Result<Vec<u8>, AppError> {
    deps.http_request("GET", url, None)
        .map_err(|e| market_err(format!("{NAME} 请求失败：{e}")))
}

impl Hub for HfHub {
    fn kind(&self) -> HubKind {
        HubKind::Hf
    }

    fn search(&self, deps: &dyn Deps, query: &str, limit: u32) -> Result<Vec<RepoSummary>, AppError> {
        self.list(deps, Some(query), limit)
    }

    fn hot(&self, deps: &dyn Deps, limit: u32) -> Result<Vec<RepoSummary>, AppError> {
        self.list(deps, None, limit)
    }

    fn detail(&self, deps: &dyn Deps, id: &str) -> Result<RepoDetail, AppError> {
        let meta: HfDetail = serde_json::from_slice(
            &get(deps, &format!("{}/api/models/{}?blobs=true", super::hub::HF_BASE, id))?,
        )
        .map_err(|e| parse_err(NAME, e))?;

        let tree: Vec<HfTreeItem> = serde_json::from_slice(&get(
            deps,
            &format!("{}/api/models/{}/tree/main?recursive=true", super::hub::HF_BASE, id),
        )?)
        .map_err(|e| parse_err(NAME, e))?;

        let files: Vec<MarketFile> = dedup_files(
            tree.into_iter()
                .filter(|t| t.kind == "file" && t.path.to_ascii_lowercase().ends_with(".gguf"))
                .map(|t| MarketFile {
                    sha256: t.lfs.and_then(|l| l.oid).map(|o| o.trim_start_matches("sha256:").to_string()),
                    path: t.path,
                    size: t.size,
                })
                .collect(),
        );

        Ok(RepoDetail {
            gguf: meta.gguf.map(|g| GgufMeta {
                architecture: g.architecture,
                context_length: g.context_length,
                total_params: g.total,
            }),
            variants: group_files(&files),
            hub: HubKind::Hf,
            downloads: meta.downloads,
            gated: is_gated(&meta.gated),
            id: meta.id,
        })
    }

    fn download_url(&self, id: &str, file: &str) -> String {
        format!("{}/{}/resolve/main/{}", super::hub::HF_BASE, id, file)
    }
}

impl HfHub {
    fn list(&self, deps: &dyn Deps, query: Option<&str>, limit: u32) -> Result<Vec<RepoSummary>, AppError> {
        let mut url = format!(
            "{}/api/models?filter=gguf&sort=downloads&direction=-1&limit={limit}",
            super::hub::HF_BASE
        );
        if let Some(q) = query {
            url.push_str(&format!("&search={}", url_encode(q)));
        }
        let items: Vec<HfRepo> =
            serde_json::from_slice(&get(deps, &url)?).map_err(|e| parse_err(NAME, e))?;
        Ok(items
            .into_iter()
            .filter(|r| !non_llm_task(&r.pipeline_tag))
            .map(|r| summary(HubKind::Hf, r))
            .collect())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_list_array() {
        let items: Vec<HfRepo> = serde_json::from_str(
            r#"[
            {"id":"unsloth/Qwen3.8-27B-GGUF","downloads":5857773,"likes":210,"pipeline_tag":"text-generation"},
            {"id":"Qwen/Qwen3-0.6B-GGUF","downloads":120000,"likes":88}
        ]"#,
        )
        .unwrap();
        assert_eq!(items.len(), 2);
        let s = summary(HubKind::Hf, items[0].clone());
        assert_eq!(s.name, "Qwen3.8-27B-GGUF");
        assert_eq!(s.params_b, Some(27.0));
        assert!(!s.gated);
    }

    #[test]
    fn gated_string_and_bool() {
        assert!(is_gated(&Some(Value::String("manual".into()))));
        assert!(is_gated(&Some(Value::Bool(true))));
        assert!(!is_gated(&Some(Value::Bool(false))));
        assert!(!is_gated(&None));
    }

    #[test]
    fn parses_tree_with_shards_and_sha() {
        let tree: Vec<HfTreeItem> = serde_json::from_str(
            r#"[
            {"type":"file","path":"README.md","size":1024},
            {"type":"file","path":"model-Q4_K_M-00001-of-00002.gguf","size":150,"lfs":{"oid":"sha256:abc","size":150}},
            {"type":"file","path":"model-Q4_K_M-00002-of-00002.gguf","size":120,"lfs":{"oid":"sha256:def"}},
            {"type":"directory","path":"sub","size":0}
        ]"#,
        )
        .unwrap();
        let files: Vec<MarketFile> = tree
            .into_iter()
            .filter(|t| t.kind == "file" && t.path.ends_with(".gguf"))
            .map(|t| MarketFile {
                sha256: t.lfs.and_then(|l| l.oid).map(|o| o.trim_start_matches("sha256:").to_string()),
                path: t.path,
                size: t.size,
            })
            .collect();
        assert_eq!(files.len(), 2);
        assert_eq!(files[0].sha256.as_deref(), Some("abc"));
        let variants = group_files(&files);
        assert_eq!(variants.len(), 1);
        assert_eq!(variants[0].total_size, 270);
    }
}

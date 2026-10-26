//! ModelScope（魔搭）Hub 适配。实测要点（2026-10-25）：
//! - 搜索只有 `PUT /api/v1/dolphin/models`（GET 404），字段 PascalCase；
//! - 排序合法值是 `SortBy:"DownloadsCount"`（`"Downloads"` 会 400），默认相关性排序；
//! - 服务端没有 gguf 过滤，只能客户端按 `Libraries` 含 "gguf" 过滤；
//! - 文件清单 `repo/files` 直接给 Size+Sha256；同一请求偶发空响应，靠上层退避重试。
//!
//! 字段结果在 `Data.Model.Models[]`（不是 `Data.Models`）。

use std::collections::HashSet;

use serde::{Deserialize, Deserializer};
use serde_json::json;

/// 魔搭的字段缺得毫无规律：`"Tasks": null` / `"Libraries": null` 都出现过，
/// `#[serde(default)]` 只救缺字段不救 null——统一用这个把 null 归零。
fn null_to_vec<'de, D, T>(de: D) -> Result<Vec<T>, D::Error>
where
    D: Deserializer<'de>,
    T: Deserialize<'de>,
{
    Ok::<_, D::Error>(Option::<Vec<T>>::deserialize(de)?.unwrap_or_default())
}

use super::hub::{
    dedup_files, group_files, market_err, parse_err, Hub, HubKind, MarketFile, RepoDetail,
    RepoSummary,
};
use crate::deps::{AppError, Deps};

pub struct MsHub;

const NAME: &str = "魔搭";

#[derive(Deserialize)]
struct MsResp {
    #[serde(default, rename = "Success")]
    success: Option<bool>,
    #[serde(default, rename = "Message")]
    message: Option<String>,
    #[serde(default, rename = "Data")]
    data: Option<MsData>,
}

#[derive(Deserialize)]
struct MsData {
    #[serde(default, rename = "Model")]
    model: Option<MsModelWrap>,
}

#[derive(Deserialize)]
struct MsModelWrap {
    #[serde(default, rename = "Models")]
    models: Vec<MsModel>,
    #[serde(default, rename = "TotalCount")]
    total_count: u64,
}

#[derive(Deserialize, Clone)]
struct MsModel {
    #[serde(rename = "Path")]
    path: String,
    #[serde(rename = "Name")]
    name: String,
    #[serde(default, rename = "Downloads")]
    downloads: u64,
    #[serde(default, rename = "Stars")]
    stars: u64,
    #[serde(default, rename = "LicenseName")]
    license: Option<String>,
    #[serde(default, deserialize_with = "null_to_vec", rename = "Libraries")]
    libraries: Vec<String>,
    #[serde(default, rename = "StorageSize")]
    storage_size: Option<u64>,
    #[serde(default, deserialize_with = "null_to_vec", rename = "Tasks")]
    tasks: Vec<MsTask>,
}

#[derive(Deserialize, Clone)]
struct MsTask {
    #[serde(default, rename = "Name")]
    name: String,
}

/// 非文本生成类任务的词表：市场「LLM 为主」（spec 决策），图像生成 /
/// 视觉理解 / 检测 / 语音等一律不收录。未知或空任务不拦。
const NON_LLM_TASKS: [&str; 6] = [
    "text-to-image-synthesis",
    "image-text-to-text",
    "object-detection",
    "automatic-speech-recognition",
    "text-to-speech",
    "any-to-any",
];

fn non_llm_task(tasks: &[MsTask]) -> bool {
    tasks
        .iter()
        .any(|t| NON_LLM_TASKS.contains(&t.name.to_ascii_lowercase().as_str()))
}

#[derive(Deserialize)]
struct MsFilesResp {
    #[serde(default, rename = "Success")]
    success: Option<bool>,
    #[serde(default, rename = "Message")]
    message: Option<String>,
    #[serde(default, rename = "Data")]
    data: Option<MsFilesData>,
}

#[derive(Deserialize)]
struct MsFilesData {
    #[serde(default, rename = "Files")]
    files: Vec<MsFile>,
}

#[derive(Deserialize)]
struct MsFile {
    #[serde(rename = "Path")]
    path: String,
    #[serde(default, rename = "Size")]
    size: u64,
    #[serde(default, rename = "Sha256")]
    sha256: Option<String>,
}

fn is_gguf(m: &MsModel) -> bool {
    m.libraries.iter().any(|l| l.eq_ignore_ascii_case("gguf")) && !non_llm_task(&m.tasks)
}

fn summary(m: MsModel) -> RepoSummary {
    let id = format!("{}/{}", m.path, m.name);
    RepoSummary {
        hub: HubKind::Ms,
        params_b: super::hub::params_from_name(&m.name),
        gated: false,
        id,
        name: m.name,
        downloads: m.downloads,
        likes: m.stars,
        license: m.license,
        task: None,
        size_hint: m.storage_size,
    }
}

impl MsHub {
    /// 搜索/热门榜共用：翻页直到凑够 limit、没有新条目或翻完 5 页。
    /// 客户端 gguf 过滤会让单页产出少于 PageSize，所以必须翻页。
    fn list(
        &self,
        deps: &dyn Deps,
        query: Option<&str>,
        sort: Option<&str>,
        limit: u32,
    ) -> Result<Vec<RepoSummary>, AppError> {
        let url = format!("{}/api/v1/dolphin/models", super::hub::MS_BASE);
        let mut out: Vec<RepoSummary> = Vec::new();
        let mut seen: HashSet<String> = HashSet::new();
        for page in 1..=5u32 {
            let mut body = json!({ "PageSize": limit, "PageNumber": page });
            if let Some(q) = query {
                body["Name"] = json!(q);
            }
            if let Some(s) = sort {
                body["SortBy"] = json!(s);
            }
            let raw = deps
                .http_request("PUT", &url, Some(&body.to_string()))
                .map_err(|e| market_err(format!("{NAME} 请求失败：{e}")))?;
            let resp: MsResp =
                serde_json::from_slice(&raw).map_err(|e| parse_err(NAME, e))?;
            if resp.success == Some(false) {
                return Err(market_err(format!(
                    "{NAME} 返回错误：{}",
                    resp.message.unwrap_or_else(|| "未知错误".into())
                )));
            }
            let wrap = resp.data.and_then(|d| d.model);
            let Some(w) = wrap else { break };
            let before = out.len();
            for m in w.models {
                if !is_gguf(&m) {
                    continue;
                }
                if seen.insert(format!("{}/{}", m.path, m.name)) {
                    out.push(summary(m));
                }
                if out.len() >= limit as usize {
                    return Ok(out);
                }
            }
            // 本页没有新增（翻到重复页）或已越过总量：停。
            if out.len() == before || u64::from(page) * u64::from(limit) >= w.total_count {
                break;
            }
        }
        Ok(out)
    }
}

impl Hub for MsHub {
    fn kind(&self) -> HubKind {
        HubKind::Ms
    }

    fn search(&self, deps: &dyn Deps, query: &str, limit: u32) -> Result<Vec<RepoSummary>, AppError> {
        self.list(deps, Some(query), None, limit)
    }

    fn hot(&self, deps: &dyn Deps, limit: u32) -> Result<Vec<RepoSummary>, AppError> {
        // 必须带搜索词：不带 Name 的全站下载榜头部是语音/标点类 pytorch 模型
        // （下载量 2.9 亿 vs GGUF 头部几百万），客户端 gguf 过滤后空空如也。
        // "gguf" 命中几乎所有 GGUF 仓库（名字里都带 GGUF），热度排序随即正确。
        self.list(deps, Some("gguf"), Some("DownloadsCount"), limit)
    }

    fn detail(&self, deps: &dyn Deps, id: &str) -> Result<RepoDetail, AppError> {
        let url = format!("{}/api/v1/models/{id}/repo/files?Revision=master&Root=", super::hub::MS_BASE);
        let raw = deps
            .http_request("GET", &url, None)
            .map_err(|e| market_err(format!("{NAME} 请求失败：{e}")))?;
        let resp: MsFilesResp = serde_json::from_slice(&raw).map_err(|e| parse_err(NAME, e))?;
        if resp.success == Some(false) {
            return Err(market_err(format!(
                "{NAME} 返回错误：{}",
                resp.message.unwrap_or_else(|| "未知错误".into())
            )));
        }
        let files: Vec<MarketFile> = dedup_files(
            resp.data
                .map(|d| d.files)
                .unwrap_or_default()
                .into_iter()
                .filter(|f| f.path.to_ascii_lowercase().ends_with(".gguf"))
                .map(|f| MarketFile { path: f.path, size: f.size, sha256: f.sha256 })
                .collect(),
        );
        Ok(RepoDetail {
            hub: HubKind::Ms,
            id: id.to_string(),
            downloads: 0,
            gated: false,
            gguf: None,
            variants: group_files(&files),
        })
    }

    fn download_url(&self, id: &str, file: &str) -> String {
        format!("{}/models/{id}/resolve/master/{}", super::hub::MS_BASE, file)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_dolphin_payload() {
        let resp: MsResp = serde_json::from_str(
            r#"{"Success":true,"Data":{"Model":{"TotalCount":3215,"Models":[
                {"Path":"Qwen","Name":"Qwen3-0.6B-GGUF","Downloads":120000,"Stars":88,
                 "LicenseName":"Apache-2.0","Libraries":["gguf"],"StorageSize":1300000000},
                {"Path":"someorg","Name":"NotThis","Downloads":500,"Libraries":["pytorch"]}
            ]}}}"#,
        )
        .unwrap();
        let wrap = resp.data.unwrap().model.unwrap();
        assert_eq!(wrap.total_count, 3215);
        assert_eq!(wrap.models.len(), 2);
        assert!(is_gguf(&wrap.models[0]));
        assert!(!is_gguf(&wrap.models[1]));
        let s = summary(wrap.models[0].clone());
        assert_eq!(s.id, "Qwen/Qwen3-0.6B-GGUF");
        assert_eq!(s.size_hint, Some(1300000000));
        assert_eq!(s.params_b, Some(0.6));
    }

    #[test]
    fn null_libraries_and_tasks_are_tolerated() {
        let resp: MsResp = serde_json::from_str(
            r#"{"Success":true,"Data":{"Model":{"TotalCount":1,"Models":[
                {"Path":"o","Name":"m","Libraries":null,"Tasks":null}
            ]}}}"#,
        )
        .unwrap();
        let m = resp.data.unwrap().model.unwrap().models;
        assert_eq!(m.len(), 1);
        assert!(!is_gguf(&m[0])); // Libraries 为 null → 不算 gguf，静默跳过
    }

    #[test]
    fn error_payload_becomes_message() {
        let resp: MsResp = serde_json::from_str(
            r#"{"Code":10010202002,"Message":"参数错误，信息：SortBy failed on the 'oneof' tag","Success":false}"#,
        )
        .unwrap();
        assert_eq!(resp.success, Some(false));
        assert!(resp.message.unwrap().contains("oneof"));
    }

    #[test]
    fn parses_files_payload() {
        let resp: MsFilesResp = serde_json::from_str(
            r#"{"Success":true,"Data":{"Files":[
                {"Path":"README.md","Size":900,"Sha256":null},
                {"Path":"Qwen3-0.6B-Q8_0.gguf","Size":639446688,"Sha256":"9465e63a","IsLFS":true}
            ]}}"#,
        )
        .unwrap();
        let files: Vec<MarketFile> = resp
            .data
            .unwrap()
            .files
            .into_iter()
            .filter(|f| f.path.ends_with(".gguf"))
            .map(|f| MarketFile { path: f.path, size: f.size, sha256: f.sha256 })
            .collect();
        assert_eq!(files.len(), 1);
        assert_eq!(files[0].sha256.as_deref(), Some("9465e63a"));
        assert_eq!(group_files(&files)[0].label, "Q8_0");
    }
}

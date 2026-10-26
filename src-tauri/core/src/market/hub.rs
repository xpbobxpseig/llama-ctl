//! 市场类型、`Hub` seam 与纯逻辑（量化档归组、量化标签、参数量启发）。
//!
//! 归组规则（实测 F:\AI_Model 现状 + 主流 GGUF 仓库约定）：
//! - 只收 `.gguf`；文件名含 `mmproj` 的是视觉投影，归附到同仓库每个量化档；
//! - `-000NN-of-000NN` 分片按前缀归为一档，档标签从前缀提取；
//! - 其余单文件自成一档；档按体积升序（小模型在前，对齐 LM Studio）。

use std::collections::{BTreeMap, HashSet};

use serde::{Deserialize, Serialize};

use super::hwinfo::FitVerdict;
use crate::deps::{AppError, AppErrorKind, Deps};

pub const HF_BASE: &str = "https://huggingface.co";
pub const MS_BASE: &str = "https://modelscope.cn";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum HubKind {
    Hf,
    Ms,
}

impl HubKind {
    pub fn other(self) -> Self {
        match self {
            HubKind::Hf => HubKind::Ms,
            HubKind::Ms => HubKind::Hf,
        }
    }
}

/// 仓库摘要：搜索与热门榜的列表条目。
#[derive(Debug, Clone, Serialize)]
pub struct RepoSummary {
    pub hub: HubKind,
    /// `unsloth/Qwen3.8-27B-GGUF` 形式，对 HF 与魔搭通用。
    pub id: String,
    pub name: String,
    pub downloads: u64,
    pub likes: u64,
    pub license: Option<String>,
    pub task: Option<String>,
    /// 名称启发式估计的参数量（十亿为单位），详情页出现 gguf 元数据后被取代。
    pub params_b: Option<f64>,
    pub size_hint: Option<u64>,
    pub gated: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct MarketFile {
    pub path: String,
    pub size: u64,
    pub sha256: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct GgufMeta {
    pub architecture: Option<String>,
    pub context_length: Option<u64>,
    pub total_params: Option<u64>,
}

/// 一个量化档：一次「下载即可加载」的文件集合（单文件、分片组，或附 mmproj）。
#[derive(Debug, Clone, Serialize)]
pub struct QuantVariant {
    pub label: String,
    /// 分片按序号排列；单文件则恰一个元素。
    pub files: Vec<MarketFile>,
    pub total_size: u64,
    pub mmproj: Option<MarketFile>,
    pub is_sharded: bool,
    /// 适配等级：归组时未知（`None`），命令层组装 detail 时按本机硬件填上。
    #[serde(skip_serializing_if = "Option::is_none")]
    pub fit: Option<FitVerdict>,
}

#[derive(Debug, Clone, Serialize)]
pub struct RepoDetail {
    pub hub: HubKind,
    pub id: String,
    pub downloads: u64,
    pub gated: bool,
    pub gguf: Option<GgufMeta>,
    pub variants: Vec<QuantVariant>,
}

pub trait Hub: Sync {
    fn kind(&self) -> HubKind;
    fn search(&self, deps: &dyn Deps, query: &str, limit: u32) -> Result<Vec<RepoSummary>, AppError>;
    fn hot(&self, deps: &dyn Deps, limit: u32) -> Result<Vec<RepoSummary>, AppError>;
    fn detail(&self, deps: &dyn Deps, id: &str) -> Result<RepoDetail, AppError>;
    fn download_url(&self, id: &str, file: &str) -> String;
}

pub fn hub(kind: HubKind) -> &'static dyn Hub {
    match kind {
        HubKind::Hf => &super::hf::HfHub,
        HubKind::Ms => &super::ms::MsHub,
    }
}

pub fn display_name(id: &str) -> &str {
    id.rsplit('/').next().unwrap_or(id)
}

/// Percent-encode a URL *path*, preserving `/` separators. Repo ids and file
/// names regularly carry spaces / CJK / `#`-like bytes; unencoded they make
/// ureq reject the URL outright (or the CDN 404) — that class of repo was
/// simply undownloadable.
pub fn url_encode_path(p: &str) -> String {
    p.split('/').map(url_encode).collect::<Vec<_>>().join("/")
}

/// Minimal percent-encoding for query components. No regex/URL crate: the
/// alphabet these APIs see is names, and every reserved byte is escaped.
pub fn url_encode(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(b as char)
            }
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

/// 参数量启发：找第一个「数字+B」词元，`8x7B` 之类 MoE 记法取乘积。
/// `Qwen3.8` 不命中（无 B 后缀），`27B`→27.0，`0.6B`→0.6。
pub fn params_from_name(name: &str) -> Option<f64> {
    let lower = name.to_ascii_lowercase();
    for tok in lower.split(['-', '_', ' ', '/']) {
        let Some(num) = tok.strip_suffix('b') else { continue };
        let v = if let Some(xi) = num.find('x') {
            let (a, b) = (num[..xi].parse::<f64>().ok()?, num[xi + 1..].parse::<f64>().ok()?);
            a * b
        } else {
            num.parse::<f64>().ok()?
        };
        if (0.05..=2000.0).contains(&v) {
            return Some(v);
        }
    }
    None
}

/// 量化标签：从词元里找量化记法，可带社区前缀（UD-/CRACK-…）。
/// `Qwen3.8-27B-Q4_K_M` → `Q4_K_M`；`…-UD-IQ1_S` → `UD-IQ1_S`。
pub fn quant_tag(stem: &str) -> Option<String> {
    const PREFIXES: [&str; 6] = ["ud", "gsq", "crack", "imatrix", "icot", "tq"];
    let tokens: Vec<&str> = stem.split('-').collect();
    for i in (0..tokens.len()).rev() {
        if !looks_like_quant(tokens[i]) {
            continue;
        }
        if let Some(prev) = i
            .checked_sub(1)
            .and_then(|p| tokens.get(p))
            .filter(|p| PREFIXES.contains(&p.to_ascii_lowercase().as_str()))
        {
            return Some(format!("{prev}-{}", tokens[i]));
        }
        return Some(tokens[i].to_string());
    }
    None
}

/// `q4_k_m` / `iq4_xs` / `bf16` / `f16` / `q8_0` 这类记法。
fn looks_like_quant(token: &str) -> bool {
    let t = token.to_ascii_lowercase();
    let segs: Vec<&str> = t.split('_').collect();
    let head = segs[0];
    let digits = |s: &str| !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit());
    let head_ok = head
        .strip_prefix("iq")
        .or_else(|| head.strip_prefix("bf"))
        .or_else(|| head.strip_prefix("fp"))
        .or_else(|| head.strip_prefix('q'))
        .or_else(|| head.strip_prefix('f'))
        .map(digits)
        .unwrap_or(false);
    head_ok
        && segs[1..]
            .iter()
            .all(|s| !s.is_empty() && s.len() <= 3 && s.bytes().all(|b| b.is_ascii_alphanumeric()))
}

/// `-00001-of-00003` 分片解析：返回 (前缀, 序号, 总数)。
pub(crate) fn parse_shard(stem: &str) -> Option<(&str, u32, u32)> {
    let of = stem.rfind("-of-")?;
    let total_s = &stem[of + 4..];
    if total_s.len() != 5 || !total_s.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    let left = &stem[..of];
    if left.len() < 7 || !left.ends_with(|c: char| c.is_ascii_digit()) {
        return None;
    }
    let idx_s = &left[left.len() - 5..];
    if !idx_s.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    // left = "<prefix>-<5位序号>"：去掉最后 6 个字符（含那个 '-'）即前缀。
    let prefix = &left[..left.len() - 6];
    if prefix.is_empty() {
        return None;
    }
    Some((prefix, idx_s.parse().ok()?, total_s.parse().ok()?))
}

fn basename(path: &str) -> &str {
    path.rsplit('/').next().unwrap_or(path)
}

/// 把仓库文件清单归组为量化档。输入可以含非 GGUF（被忽略）。
pub fn group_files(files: &[MarketFile]) -> Vec<QuantVariant> {
    let mut mmprojs: Vec<&MarketFile> = Vec::new();
    let mut shard_groups: BTreeMap<String, Vec<(u32, &MarketFile)>> = BTreeMap::new();
    let mut singles: Vec<&MarketFile> = Vec::new();

    for f in files {
        let base = basename(&f.path);
        if !base.to_ascii_lowercase().ends_with(".gguf") {
            continue;
        }
        let stem = &base[..base.len() - 5];
        if stem.to_ascii_lowercase().contains("mmproj") {
            mmprojs.push(f);
            continue;
        }
        match parse_shard(stem) {
            Some((prefix, idx, _total)) => {
                shard_groups.entry(prefix.to_string()).or_default().push((idx, f));
            }
            None => singles.push(f),
        }
    }

    let mut variants: Vec<QuantVariant> = Vec::new();
    for (prefix, mut parts) in shard_groups {
        parts.sort_by_key(|(idx, _)| *idx);
        let files: Vec<MarketFile> = parts.into_iter().map(|(_, f)| f.clone()).collect();
        let total_size = files.iter().map(|f| f.size).sum();
        let label = quant_tag(&prefix).unwrap_or_else(|| prefix.clone());
        variants.push(QuantVariant { label, files, total_size, mmproj: None, is_sharded: true, fit: None });
    }
    for f in singles {
        let stem = &basename(&f.path)[..basename(&f.path).len() - 5];
        let label = quant_tag(stem).unwrap_or_else(|| stem.to_string());
        variants.push(QuantVariant {
            label,
            files: vec![f.clone()],
            total_size: f.size,
            mmproj: None,
            is_sharded: false,
            fit: None,
        });
    }

    // mmproj 归附：它是仓库级附件（视觉投影），不是模型类型——统一取字典序
    // 第一个，随任一量化档一并下载；多余的忽略，绝不让它变成一个假「模型」。
    variants.sort_by(|a, b| a.total_size.cmp(&b.total_size).then_with(|| a.label.cmp(&b.label)));
    mmprojs.sort_by(|a, b| a.path.cmp(&b.path));
    let primary = mmprojs.first().cloned();
    for v in &mut variants {
        v.mmproj = primary.cloned();
    }
    variants
}

/// Hub API 失败的统一错误形态：`message` 直接进 UI。
pub(crate) fn market_err(message: impl Into<String>) -> AppError {
    AppError::new(AppErrorKind::MarketFailed, message)
}

/// 响应体 → JSON 解析失败时的统一报错。
pub(crate) fn parse_err(hub: &str, e: serde_json::Error) -> AppError {
    market_err(format!("{hub} 响应解析失败：{e}"))
}

/// 防御分片清单里混入的重复文件（两个 shard 条目指向同一路径）。
pub(crate) fn dedup_files(files: Vec<MarketFile>) -> Vec<MarketFile> {
    let mut seen = HashSet::new();
    files.into_iter().filter(|f| seen.insert(f.path.clone())).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn f(path: &str, size: u64) -> MarketFile {
        MarketFile { path: path.to_string(), size, sha256: None }
    }

    #[test]
    fn params_heuristic() {
        assert_eq!(params_from_name("unsloth/Qwen3.8-27B-GGUF"), Some(27.0));
        assert_eq!(params_from_name("Qwen3-0.6B-GGUF"), Some(0.6));
        assert_eq!(params_from_name("mixtral-8x7b"), Some(56.0));
        assert_eq!(params_from_name("GLM-5.3-Flash-GGUF"), None);
        assert_eq!(params_from_name("deepseek-r1-671b"), Some(671.0));
    }

    #[test]
    fn quant_labels() {
        assert_eq!(quant_tag("Qwen3.8-27B-Q4_K_M"), Some("Q4_K_M".into()));
        assert_eq!(quant_tag("Qwen3.8-27B-UD-IQ1_S"), Some("UD-IQ1_S".into()));
        assert_eq!(quant_tag("Qwen3.8-27B-CRACK-IQ4_XS"), Some("CRACK-IQ4_XS".into()));
        assert_eq!(quant_tag("model-Q8_0"), Some("Q8_0".into()));
        assert_eq!(quant_tag("model-bf16"), Some("bf16".into()));
        assert_eq!(quant_tag("novelty"), None);
    }

    #[test]
    fn shard_parsing() {
        assert_eq!(
            parse_shard("Qwen3.8-27B-Q4_K_M-00001-of-00003"),
            Some(("Qwen3.8-27B-Q4_K_M", 1, 3))
        );
        assert_eq!(parse_shard("Qwen3.8-27B-Q4_K_M"), None);
        assert_eq!(parse_shard("model-0002-of-0003"), None); // 非 5 位序号不算分片
    }

    #[test]
    fn grouping_shards_single_mmproj_and_readme() {
        let files = vec![
            f("README.md", 1024),
            f("Qwen3.8-27B-UD-IQ1_S.gguf", 6_192_222_208),
            f("Qwen3.8-27B-Q4_K_M-00001-of-00002.gguf", 15_000_000_000),
            f("Qwen3.8-27B-Q4_K_M-00002-of-00002.gguf", 12_000_000_000),
            f("mmproj-Qwen3.8-27B-f16.gguf", 931_145_952),
        ];
        let v = group_files(&files);
        // 体积升序：IQ1_S 单文件 < Q4_K_M 分片组（27GB）
        assert_eq!(v.len(), 2);
        assert_eq!(v[0].label, "UD-IQ1_S");
        assert!(!v[0].is_sharded);
        assert_eq!(v[1].label, "Q4_K_M");
        assert!(v[1].is_sharded);
        assert_eq!(v[1].files.len(), 2);
        assert_eq!(v[1].total_size, 27_000_000_000);
        // mmproj 归附到每一档
        for x in &v {
            assert_eq!(x.mmproj.as_ref().map(|m| m.size), Some(931_145_952));
        }
    }

    #[test]
    fn extra_mmproj_never_becomes_a_model() {
        let files = vec![
            f("model-Q8_0.gguf", 700),
            f("mmproj-a-f16.gguf", 100),
            f("mmproj-b-f16.gguf", 110),
        ];
        let v = group_files(&files);
        // mmproj 是仓库级附件：归附主档，多余的不生成假「模型」条目。
        assert_eq!(v.len(), 1);
        assert_eq!(v[0].label, "Q8_0");
        assert_eq!(v[0].mmproj.as_ref().map(|m| m.path.contains('a')), Some(true));
    }

    #[test]
    fn url_encoding() {
        assert_eq!(url_encode("qwen3 gguf"), "qwen3%20gguf");
        assert_eq!(url_encode("GLM-5.3"), "GLM-5.3");
    }
}

//! 本地模型扫描（spec「User Stories 25–28」）。
//!
//! 扫描下载根目录**两层深**：兼容 `<模型名>/` 子目录与根目录平铺两种现有
//! 布局；`mmproj-` 文件归附同目录主模型；分片按前缀归组，`path` 指向第一片
//! （llama-server `-m` 的正确指向）。适配等级当场算好。

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use super::hub::{market_err, parse_shard, quant_tag};
use super::hwinfo::{assess, Hardware, FitVerdict};
use crate::deps::{AppError, Deps};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct LocalModel {
    /// 主文件（单文件本体或第一分片）——即 `-m` 该指的路径。
    pub path: PathBuf,
    /// 全部权重（含分片与 mmproj）体积。
    pub size: u64,
    pub label: String,
    pub is_sharded: bool,
    pub mmproj: Option<PathBuf>,
    pub fit: FitVerdict,
}

/// 扫描 `root`（两层深）。根目录不存在不算错误——返回空列表。
pub fn scan(deps: &dyn Deps, root: &Path, hw: &Hardware) -> Result<Vec<LocalModel>, AppError> {
    // dir → (文件名, 体积)，只收 .gguf
    let mut per_dir: BTreeMap<PathBuf, Vec<(String, u64)>> = BTreeMap::new();
    walk(deps, root, 2, &mut per_dir)?;

    let mut out = Vec::new();
    for (dir, files) in per_dir {
        let mut mmprojs: Vec<(String, u64)> = Vec::new();
        let mut shard_groups: BTreeMap<String, Vec<(u32, String, u64)>> = BTreeMap::new();
        let mut singles: Vec<(String, u64)> = Vec::new();
        for (name, size) in files {
            let stem = &name[..name.len() - 5]; // 去 .gguf（已过滤大小写）
            if stem.to_ascii_lowercase().contains("mmproj") {
                mmprojs.push((name, size));
                continue;
            }
            match parse_shard(stem) {
                Some((prefix, idx, _)) => {
                    shard_groups.entry(prefix.to_string()).or_default().push((idx, name, size));
                }
                None => singles.push((name, size)),
            }
        }

        mmprojs.sort_by(|a, b| a.0.cmp(&b.0));
        let primary_mmproj = mmprojs.first().cloned();

        let mut models: Vec<(u64, LocalModel)> = Vec::new();
        let mmproj_size = primary_mmproj.as_ref().map(|(_, s)| *s);
        let mut push = |path: PathBuf, size: u64, label: String, sharded: bool| {
            let mmproj = primary_mmproj.as_ref().map(|(n, _)| dir.join(n));
            let fit = assess(hw, size + mmproj_size.unwrap_or(0));
            models.push((size, LocalModel { path, size, label, is_sharded: sharded, mmproj, fit }));
        };

        for (prefix, mut parts) in shard_groups {
            parts.sort_by_key(|(idx, _, _)| *idx);
            let size: u64 = parts.iter().map(|(_, _, s)| s).sum();
            let label = quant_tag(&prefix).unwrap_or_else(|| prefix.clone());
            push(dir.join(&parts[0].1), size, label, true);
        }
        for (name, size) in singles {
            let stem = &name[..name.len() - 5];
            let label = quant_tag(stem).unwrap_or_else(|| stem.to_string());
            push(dir.join(&name), size, label, false);
        }
        // 多余 mmproj 是附件不是模型：忽略（首个已归附主模型）。
        models.sort_by(|a, b| b.0.cmp(&a.0).then_with(|| a.1.label.cmp(&b.1.label)));
        out.extend(models.into_iter().map(|(_, m)| m));
    }
    out.sort_by(|a, b| b.size.cmp(&a.size).then_with(|| a.path.cmp(&b.path)));
    Ok(out)
}

fn walk(
    deps: &dyn Deps,
    dir: &Path,
    depth: u32,
    out: &mut BTreeMap<PathBuf, Vec<(String, u64)>>,
) -> Result<(), AppError> {
    let entries = match deps.list_dir(dir) {
        Ok(e) => e,
        Err(_) => return Ok(()), // 不可读的目录跳过，不炸整个扫描
    };
    for e in entries {
        if e.is_dir {
            if depth > 1 {
                walk(deps, &e.path, depth - 1, out)?;
            }
        } else if e
            .path
            .to_string_lossy()
            .to_ascii_lowercase()
            .ends_with(".gguf")
        {
            let name = e.path.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
            let size = deps.file_size(&e.path)?.unwrap_or(0);
            out.entry(dir.to_path_buf()).or_default().push((name, size));
        }
    }
    Ok(())
}

/// 删除守卫：目标是否就是当前服务正在用的模型（路径写法归一后比较）。
pub fn is_current_model(current: Option<&str>, target: &Path) -> bool {
    let Some(cur) = current else { return false };
    let norm = |s: &str| s.replace('\\', "/").to_ascii_lowercase();
    norm(cur) == norm(&target.to_string_lossy())
}

/// 删除一个本地模型：主文件、分片兄弟与 mmproj 一起删。
pub fn delete(deps: &dyn Deps, model: &LocalModel) -> Result<(), AppError> {
    let dir = model.path.parent().unwrap_or(Path::new("."));
    let victims: Vec<PathBuf> = model
        .mmproj
        .iter()
        .cloned()
        .chain(std::iter::once(model.path.clone()))
        .chain(shard_siblings(deps, dir, &model.path))
        .collect();
    let mut any = false;
    for p in &victims {
        match deps.remove_file(p) {
            Ok(()) => any = true,
            Err(_) => {} // 已不存在也算删干净
        }
    }
    if !any {
        return Err(market_err("没有可删除的文件（可能已被手动删除）"));
    }
    Ok(())
}

/// 同目录下、与主文件同前缀的其余分片。
fn shard_siblings(deps: &dyn Deps, dir: &Path, primary: &Path) -> Vec<PathBuf> {
    let Some(name) = primary.file_name().and_then(|n| n.to_str()) else {
        return Vec::new();
    };
    let stem = name.strip_suffix(".gguf").unwrap_or(name);
    let prefix = match parse_shard(stem) {
        Some((p, _, _)) => p.to_string(),
        None => return Vec::new(),
    };
    let Ok(entries) = deps.list_dir(dir) else { return Vec::new() };
    entries
        .into_iter()
        .filter(|e| !e.is_dir)
        .filter_map(|e| {
            let n = e.path.file_name()?.to_string_lossy().into_owned();
            let s = n.strip_suffix(".gguf")?;
            (s != stem && (s.starts_with(&format!("{prefix}-")) || s.starts_with(&prefix)))
                .then_some(e.path)
        })
        .collect()
}

//! market.json — 下载任务与实测记录的持久化。
//!
//! 与 settings/presets 不同：这是应用生成的状态文件，不是用户手编的，
//! 所以损坏**整体降级为空库**并在下次写入时重写，绝不 panic。写入走
//! `persist::write_atomic`（`.tmp` → rename）。

use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::deps::{AppError, Deps};
use crate::persist::write_atomic;

use super::manager::{BenchRecord, DownloadTask};

#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct MarketStore {
    pub tasks: Vec<DownloadTask>,
    pub benchmarks: Vec<BenchRecord>,
}

/// 读库。缺失/损坏/非对象一律空库。
pub fn load_store(d: &dyn Deps, file: &Path) -> MarketStore {
    d.read_file(file)
        .ok()
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
        .unwrap_or_default()
}

/// 整库写回（原子）。
pub fn save_store(d: &dyn Deps, file: &Path, store: &MarketStore) -> Result<(), AppError> {
    let bytes = serde_json::to_vec_pretty(store).unwrap_or_default();
    write_atomic(d, file, &bytes)
}

/// `LLAMA_CTL_MARKET` > `%APPDATA%\llama-ctl\market.json`。
pub fn resolve_market_file(env: &crate::persist::Env) -> PathBuf {
    match env.market_override.as_deref().filter(|v| !v.is_empty()) {
        Some(p) => PathBuf::from(p),
        None => crate::persist::user_data_dir(env).join(crate::persist::MARKET_BASENAME),
    }
}

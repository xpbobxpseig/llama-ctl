//! 模型市场领域层（spec: docs/spec/model-marketplace.md）。
//!
//! `hub` 定义双源适配与量化档归组，`hf`/`ms` 是 HuggingFace 与魔搭的
//! 两个 `Hub` 实现，全部外效应经 [`crate::deps::Deps`]。

pub mod bench;
pub mod downloader;
pub mod hf;
pub mod hub;
pub mod hwinfo;
pub mod local;
pub mod manager;
pub mod ms;
pub mod store;

pub use bench::{bench_args, llama_dir, parse_json as parse_bench_json, BenchOutcome};
pub use downloader::{download, part_path, DownloadPlan};
pub use hub::{display_name, group_files, hub, params_from_name, quant_tag, GgufMeta, Hub, HubKind, MarketFile, QuantVariant, RepoDetail, RepoSummary};
pub use hwinfo::{assess, detect, FitTier, FitVerdict, Gpu, GpuVendor, Hardware};
pub use local::{is_current_model, LocalModel};
pub use manager::{BenchRecord, DownloadManager, DownloadTask, TaskFile, TaskState};
pub use store::MarketStore;

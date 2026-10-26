//! llama-bench 实测（spec「Implementation Decisions · bench_run 事务」）。
//!
//! 事务外壳（停服→测→恢复）在命令层（`cmd::bench_run`），这里只管：
//! 找到 `llama-bench.exe` → 按默认参数跑一次 → 从 `-o json` 解析
//! pp512/tg128 两个吞吐数。JSON 字段名（`test` / `avg_ts` / `ngl`）取自
//! 上游 `tools/llama-bench/llama-bench.cpp`。

use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use super::hub::market_err;
use crate::deps::{AppResult, Deps};
use crate::install::InstallEnv;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BenchOutcome {
    pub pp_tps: f64,
    pub tg_tps: f64,
    pub ngl: u32,
}

/// llama.cpp 根目录：`InstallEnv.llama_dir`，缺省 `F:\llama.cpp`（与更新事务一致）。
pub fn llama_dir(env: &InstallEnv) -> PathBuf {
    env.llama_dir
        .clone()
        .unwrap_or_else(|| PathBuf::from(r"F:\llama.cpp"))
}

/// 默认实测参数：全量 offload、flash-attn、pp512/tg128、单次重复。
/// 本机参照（bench.txt）：27B Q4_K_M 全 offload → pp512≈2235，tg128≈43.5 t/s。
pub fn bench_args(model: &Path) -> Vec<String> {
    vec![
        "-m".into(),
        model.to_string_lossy().into_owned(),
        "-ngl".into(),
        "99".into(),
        "-fa".into(),
        "on".into(),
        "-p".into(),
        "512".into(),
        "-n".into(),
        "128".into(),
        "-r".into(),
        "1".into(),
        "-o".into(),
        "json".into(),
    ]
}

/// 跑一次实测。stderr 的进度行逐行进 `sink`，stdout 按 JSON 解析。
pub fn run(
    deps: &dyn Deps,
    env: &InstallEnv,
    model: &Path,
    sink: &mut dyn FnMut(&str),
) -> AppResult<BenchOutcome> {
    let exe = llama_dir(env).join("llama-bench.exe");
    if deps.file_size(&exe)?.is_none() {
        return Err(market_err(format!("未找到 {}", exe.display())));
    }
    sink("加载模型并实测中（全量 offload，约需 1 分钟）…");
    let args_owned = bench_args(model);
    let args: Vec<&str> = args_owned.iter().map(String::as_str).collect();
    let (stdout, stderr) = deps
        .spawn_split(exe.to_string_lossy().as_ref(), &args)
        .map_err(|e| market_err(format!("llama-bench 运行失败：{e}")))?;
    for line in String::from_utf8_lossy(&stderr).lines() {
        let l = line.trim();
        if !l.is_empty() {
            sink(l);
        }
    }
    parse_json(&stdout)
}

/// 从 `llama-bench -o json` 输出解析 pp/tg 吞吐。
pub fn parse_json(bytes: &[u8]) -> AppResult<BenchOutcome> {
    let v: serde_json::Value = serde_json::from_slice(bytes)
        .map_err(|e| market_err(format!("llama-bench 输出解析失败：{e}")))?;
    let rows: Vec<serde_json::Value> = match v {
        serde_json::Value::Array(a) => a,
        serde_json::Value::Object(_) => vec![v],
        _ => return Err(market_err("llama-bench 输出不是 JSON 数组")),
    };
    let mut pp = None;
    let mut tg = None;
    let mut ngl = 99u32;
    for row in &rows {
        let test = row.get("test").and_then(|t| t.as_str()).unwrap_or("");
        let ts = row.get("avg_ts").and_then(|t| t.as_f64());
        if let Some(n) = row.get("ngl").and_then(|t| t.as_i64()) {
            if n >= 0 {
                ngl = n as u32;
            }
        }
        let Some(ts) = ts else { continue };
        if pp.is_none() && test.starts_with("pp") {
            pp = Some(ts);
        } else if tg.is_none() && test.starts_with("tg") {
            tg = Some(ts);
        }
    }
    match (pp, tg) {
        (Some(pp_tps), Some(tg_tps)) => Ok(BenchOutcome { pp_tps, tg_tps, ngl }),
        _ => Err(market_err(
            "llama-bench 输出里没有 pp/tg 吞吐数据（模型可能加载失败，见上方日志）",
        )),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_real_shape() {
        let out = parse_json(
            br#"[
            {"cpu_info":"AMD Ryzen 9 9950X","gpu_all":[{"gpu_name":"NVIDIA GeForce RTX 4090"}],
             "model_filename":"qwen.gguf","model_size":16000000000,"n_batch":2048,"n_ubatch":512,
             "fa":1,"ngl":99,"split_mode":1,"main_gpu":0,"tensor_split":[1.0],"test":"pp512",
             "n_prompt":512,"n_gen":0,"n_depth":0,"test_time":"2026-10-25",
             "avg_ns":229000000,"stddev_ns":0,"avg_ts":2234.87,"stddev_ts":0.0},
            {"test":"tg128","ngl":99,"avg_ts":43.53,"stddev_ts":0.0}
        ]"#,
        )
        .unwrap();
        assert_eq!(out.pp_tps, 2234.87);
        assert_eq!(out.tg_tps, 43.53);
        assert_eq!(out.ngl, 99);
    }

    #[test]
    fn missing_rows_is_a_clear_error() {
        let e = parse_json(br#"[]"#).unwrap_err();
        assert!(e.message.contains("pp/tg"));
    }

    #[test]
    fn default_args_are_documented_shape() {
        let args = bench_args(Path::new(r"F:\AI_Model\m.gguf"));
        let s = args.join(" ");
        assert!(s.contains("-ngl 99") && s.contains("-o json") && s.contains("-r 1"));
    }
}

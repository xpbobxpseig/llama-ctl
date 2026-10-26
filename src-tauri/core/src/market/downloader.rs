//! 流式下载引擎（ADR-0004）：Range 续传 + `.part` 中转 + Sha256 校验 + 退避重试。
//!
//! 状态机要点：
//! - 每次尝试以「已有 `.part` 大小」发 `Range`；服务器答 `200`（无视 Range）
//!   或声明的全长对不上预期 → 截断重下；
//! - EOF 时长度对不上预期视为「传输不完整」，保留进度下次续传；
//! - Sha256 不匹配是致命错误（清掉 `.part` 直接报错，不盲目重下 40GB）；
//! - 文件目标已存在时幂等跳过。

use std::path::{Path, PathBuf};

use super::hub::market_err;
use crate::deps::{AppError, Deps};

pub struct DownloadPlan {
    pub url: String,
    pub dest: PathBuf,
    pub expected_sha256: Option<String>,
    pub expected_total: Option<u64>,
    /// 重试退避毫秒；生产 2000，测试 0。
    pub backoff_ms: u64,
}

impl DownloadPlan {
    pub fn new(url: impl Into<String>, dest: impl Into<PathBuf>) -> Self {
        Self {
            url: url.into(),
            dest: dest.into(),
            expected_sha256: None,
            expected_total: None,
            backoff_ms: 2000,
        }
    }
}

pub type Progress<'a> = &'a mut dyn FnMut(u64, u64) -> bool;

/// 下载的两种正常收场：`Done` 完成，`Paused` 被进度回调中止（暂停/取消），
/// `.part` 原样保留供续传。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Outcome {
    Done,
    Paused,
}

const MAX_ATTEMPTS: u32 = 10;
const CHUNK: usize = 256 * 1024;

pub fn part_path(dest: &Path) -> PathBuf {
    let mut os = dest.as_os_str().to_os_string();
    os.push(".part");
    PathBuf::from(os)
}

/// 下载 `plan` 指向的文件。成功即 `.part` 已改名落定。
pub fn download(
    deps: &dyn Deps,
    plan: &DownloadPlan,
    progress: Progress<'_>,
) -> Result<Outcome, AppError> {
    if deps.file_size(&plan.dest)?.is_some() {
        return Ok(Outcome::Done); // 幂等：已存在
    }
    if let Some(dir) = plan.dest.parent() {
        deps.create_dir_all(dir)?;
    }
    let part = part_path(&plan.dest);
    let mut have = deps.file_size(&part)?.unwrap_or(0);
    let mut last_err = String::from("未知错误");

    for attempt in 1..=MAX_ATTEMPTS {
        match deps.http_open_range(&plan.url, have) {
            Err(e) => last_err = e.message,
            Ok(stream) => {
                let total_hint = stream.total.or(plan.expected_total).unwrap_or(0);
                let mut restart = have > 0 && !stream.resumed;
                if let (Some(t), Some(exp)) = (stream.total, plan.expected_total) {
                    restart |= t != exp; // 源已变更，续传没有意义
                }
                if restart {
                    deps.write_file(&part, &[])?;
                    have = 0;
                    continue; // 从零重开（不消耗退避）
                }

                let mut reader = stream.reader;
                let mut buf = vec![0u8; CHUNK];
                loop {
                    match reader.read(&mut buf) {
                        Ok(0) => {
                            if let Some(exp) = plan.expected_total {
                                if have != exp {
                                    // 传输不完整：保留进度，下次 Range 续传补尾巴。
                                    last_err = format!("传输不完整：{have}/{exp} 字节");
                                    break;
                                }
                            }
                            return finish(deps, plan, &part);
                        }
                        Ok(n) => {
                            deps.append_file(&part, &buf[..n])?;
                            have += n as u64;
                            if !progress(have, total_hint) {
                                // 暂停/取消：保留 `.part`，立即收场，不重试。
                                return Ok(Outcome::Paused);
                            }
                        }
                        Err(e) => {
                            last_err = format!("连接中断：{e}");
                            break;
                        }
                    }
                }
            }
        }
        if attempt < MAX_ATTEMPTS {
            std::thread::sleep(std::time::Duration::from_millis(plan.backoff_ms * u64::from(attempt)));
        }
    }
    Err(market_err(format!(
        "下载失败（重试 {MAX_ATTEMPTS} 次）：{last_err}"
    )))
}

/// EOF 之后的收尾：Sha256 校验 → 原子改名。
fn finish(deps: &dyn Deps, plan: &DownloadPlan, part: &Path) -> Result<Outcome, AppError> {
    if let Some(expected) = &plan.expected_sha256 {
        let actual = deps
            .hash_file(part)
            .map_err(|e| market_err(format!("校验读取失败：{e}")))?;
        if !actual.eq_ignore_ascii_case(expected) {
            deps.remove_file(part)?;
            return Err(market_err(format!(
                "校验失败：SHA-256 不匹配（期望 {expected}，实际 {actual}），已清理未完成文件"
            )));
        }
    }
    deps.rename_file(part, &plan.dest)?;
    Ok(Outcome::Done)
}

use std::io::Read as _;

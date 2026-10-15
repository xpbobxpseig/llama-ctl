//! Bilingual UI copy — the single source of truth (ticket 08).
//!
//! Decision settled by ticket 08: **Rust holds the one complete table**. Every
//! skeleton string (buttons, service labels, log lines, the update section)
//! lives here as `key -> (zh, en)`; the frontend asks for a key and renders
//! what comes back. The frontend never stores a second translation, so the two
//! languages cannot drift apart.
//!
//! Scope is the same as `strings.py` / ADR-0005: only short skeleton copy is
//! translated. Parameter explanations (`param.*`) stay Chinese in *both*
//! languages — that is existing behaviour, not an oversight.
//!
//! Fallback: a key the table does not have renders as the key itself, so a gap
//! is visible in the UI instead of a blank label.

use std::collections::BTreeMap;
use std::sync::atomic::{AtomicU8, Ordering};

use serde::{Deserialize, Serialize};

/// Interface language. `Zh` is the default, matching `strings.py`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Lang {
    #[default]
    Zh,
    En,
}

impl Lang {
    pub const ALL: [Lang; 2] = [Lang::Zh, Lang::En];

    /// The persisted setting value (`"zh"` / `"en"`).
    pub fn code(self) -> &'static str {
        match self {
            Lang::Zh => "zh",
            Lang::En => "en",
        }
    }

    pub fn from_code(code: &str) -> Option<Lang> {
        Lang::ALL.into_iter().find(|l| l.code() == code)
    }
}

/// Process-wide active language. One process serves one UI, so a single atomic
/// beats threading a language argument through every render path.
static LANG: AtomicU8 = AtomicU8::new(Lang::Zh as u8);

pub fn language() -> Lang {
    match LANG.load(Ordering::Relaxed) {
        1 => Lang::En,
        _ => Lang::Zh,
    }
}

pub fn set_language(lang: Lang) {
    LANG.store(lang as u8, Ordering::Relaxed);
}

/// Set the language from a persisted code; an unknown code falls back to `Zh`
/// (same tolerance as `strings.set_lang`) and the effective language is
/// returned so the caller can persist the correction.
pub fn set_language_code(code: &str) -> Lang {
    let lang = Lang::from_code(code).unwrap_or(Lang::Zh);
    set_language(lang);
    lang
}

/// The whole table: `(key, zh, en)`. Keys keep the existing `namespace.name`
/// shape (`svc.*`, `btn.*`, `log.*`, `upd.*`, `param.*`).
///
/// `param.*` entries are parameter explanations: deliberately identical in both
/// languages.
pub const STRINGS: &[(&str, &str, &str)] = &[
    // ---- 标题 / 卡片 ----
    ("app.title", "llama.cpp 服务控制台", "llama.cpp Service Console"),
    ("card.presets", "参数预设", "Presets"),
    ("card.params", "启动参数", "Launch Parameters"),
    // ---- 顶栏 ----
    ("svc.label", "服务", "Svc"),
    ("state.unknown", "服务 —", "Svc —"),
    ("health.idle", "探活 —", "Health —"),
    ("health.down", "探活 未运行", "Health down"),
    ("boot.label", "开机自启", "Auto-start"),
    ("boot.auto", "自动(开机)", "Auto (boot)"),
    ("boot.manual", "手动", "Manual"),
    ("boot.disabled", "禁用", "Disabled"),
    // ---- 参数区按钮 ----
    ("quick.label", "快捷：", "Quick:"),
    ("browse", "浏览", "Browse"),
    ("btn.start", "启动", "Start"),
    ("btn.stop", "停止", "Stop"),
    ("btn.restart", "重启", "Restart"),
    ("btn.revert", "还原", "Revert"),
    ("btn.apply2", "应用更改", "Apply changes"),
    ("btn.settings", "⚙ 设置", "Settings"),
    ("preset.delete", "删除", "Delete"),
    // ---- 设置窗口 ----
    ("settings.title", "设置", "Settings"),
    ("settings.lang", "界面语言（参数详解保持中文）", "Language (parameter guides stay Chinese)"),
    ("settings.close", "关闭", "Close"),
    // ---- 日志 ----
    ("log.collapsed", "日志尾随 server.err（已折叠）", "Tail server.err (collapsed)"),
    ("log.expanded", "日志尾随 server.err（点击折叠）", "Log tail: server.err (click to fold)"),
    ("log.restart.stop", ">>> 重启 {s}：停止...", ">>> Restarting {s}: stopping..."),
    ("log.restart.start", ">>> 启动...", ">>> Starting..."),
    ("log.restart.ready", ">>> 服务就绪：{d}", ">>> Service ready: {d}"),
    ("log.restart.unhealthy", ">>> 当前未探活，继续重启", ">>> Not healthy, restarting anyway"),
    ("log.restart.stopfail", ">>> 停止失败，已中止重启：{m}", ">>> Stop failed, restart aborted: {m}"),
    (
        "log.restart.stoptimeout",
        ">>> 停止超时（40×0.5s 未 STOPPED），已中止重启",
        ">>> Stop timed out, restart aborted",
    ),
    ("log.restart.alreadystopped", "（已是停止态，直接启动）", " (already stopped; starting directly)"),
    ("log.restart.startfail", ">>> 启动失败，已中止重启：{m}", ">>> Start failed, restart aborted: {m}"),
    // ---- 状态行 ----
    ("status.svc", "服务 {st}", "Svc {st}"),
    ("status.health.ok", "探活 OK · {d}", "Health OK · {d}"),
    ("status.health.bad", "探活 FAIL · {d}", "Health FAIL · {d}"),
    ("status.dirty", "● 有未应用的更改", "● Unapplied changes"),
    // ---- 官方更新（llama.cpp）----
    ("upd.section", "官方更新", "Official updates"),
    ("upd.channel", "二进制版本（替换 F:\\llama.cpp 下文件）", "Build variant (files under F:\\llama.cpp)"),
    ("upd.auto.label", "启动时自动检查（仅提示，绝不自动安装）", "Check on startup (notify only, never auto-install)"),
    ("upd.check", "立即检查更新", "Check for updates"),
    ("upd.status.now", "当前：{b}", "Installed: {b}"),
    ("upd.status.unknown", "当前版本未知（无法读取 llama-server.exe）", "Installed version unknown (llama-server.exe unreadable)"),
    ("upd.status.checking", "正在读取当前版本…", "Reading installed version…"),
    ("upd.status.none", "还未检查过更新", "Not checked yet"),
    ("upd.checking", "正在检查官方最新版本…", "Checking official releases…"),
    ("upd.check.done", "最新：{t}", "Latest: {t}"),
    ("upd.check.fail", "检查失败：{e}", "Check failed: {e}"),
    ("upd.uptodate", "已是最新", "Up to date"),
    ("upd.uptodate.msg", "当前 b{cur} 已是最新官方构建（b{new}）。", "Build b{cur} is already the latest official build (b{new})."),
    ("upd.title", "发现新版本：{t}", "Update available: {t}"),
    ("upd.prompt", "官方最新 b{n}（当前 b{c}）。是否查看更新日志并更新？", "Official latest b{n} (installed b{c}). Review the changelog and update?"),
    ("upd.changelog", "更新日志", "Changelog"),
    (
        "upd.no.changelog",
        "官方 nightly 构建不提供更新说明。\\n\\n本次更新：{t}（build {b}）\\n\\n将下载并替换下面列出的文件；旧文件会先备份，任一步失败自动回滚。",
        "Official nightly builds ship no release notes.\\n\\nThis update: {t} (build {b})\\n\\nThe files listed below will be downloaded and replaced; existing files are backed up first and any failure rolls back.",
    ),
    ("upd.assets", "下载内容：{a}", "Will download: {a}"),
    ("upd.install", "立即更新", "Install now"),
    (
        "upd.install.confirm",
        "将停止服务「{s}」并替换 llama.cpp 二进制。旧文件会备份到 {d}。\\n\\n继续？",
        "The service \"{s}\" will be stopped and llama.cpp binaries replaced. Old files are backed up to {d}.\\n\\nContinue?",
    ),
    ("upd.installing", "正在更新 llama.cpp…", "Updating llama.cpp…"),
    ("upd.stopping", "停止服务 {s}…", "Stopping service {s}…"),
    ("upd.stopped", "服务已停止。", "Service stopped."),
    ("upd.stop.fail", "停止服务失败：{m}", "Failed to stop service: {m}"),
    ("upd.downloading", "下载 {n}（{p}%）", "Downloading {n} ({p}%)"),
    ("upd.backing", "备份旧文件到 {d}", "Backing up old files to {d}"),
    ("upd.backup.fail", "备份旧文件失败：{m}（已中止，未替换任何文件）", "Backup failed: {m} (aborted; no files were replaced)"),
    ("upd.extracting", "解压替换二进制…", "Extracting and replacing binaries…"),
    ("upd.extract.fail", "解压替换失败：{e}", "Extract/replace failed: {e}"),
    ("upd.rollback", ">>> 检测到失败，正在回滚已替换的文件…", ">>> Failure detected, rolling back replaced files…"),
    ("upd.rollback.done", ">>> 回滚完成：旧文件已恢复。", ">>> Rollback complete: previous files restored."),
    ("upd.rollback.fail", ">>> 回滚失败：{e}（可手动从 {d} 恢复）", ">>> Rollback failed: {e} (restore manually from {d})"),
    ("upd.no.files", "没有需要替换的文件（更新包与目标目录不匹配）", "No files to replace (package does not match target directory)"),
    ("upd.not.running", "更新后服务 {s} 未进入 RUNNING，已回滚旧文件", "Service {s} did not reach RUNNING after update; previous files restored"),
    ("upd.wait.running", "等待服务进入 RUNNING…（已 {s} 秒）", "Waiting for the service to reach RUNNING… ({s}s)"),
    ("upd.starting", "重启服务 {s}…", "Restarting service {s}…"),
    ("upd.start.fail", "启动服务失败：{m}（已回滚旧文件并尝试恢复服务）", "Failed to start the service: {m} (previous files rolled back; recovery attempted)"),
    ("upd.done", "更新完成：{s} 已重启，当前 b{b}。", "Update complete: {s} restarted, now b{b}."),
    ("upd.err", "更新失败：{e}", "Update failed: {e}"),
    ("upd.err.title", "更新失败", "Update failed"),
    ("upd.required", "未找到匹配的官方资产。请确认二进制版本选择是否正确。", "No matching official asset found. Check the build variant setting."),
    ("upd.prune", "已清理 {n} 个陈旧目录：{d}", "Pruned {n} stale directories: {d}"),
    ("upd.cache.bad", "缓存已损坏，正在删除并重新下载：{n}", "Cached file is corrupt; deleting and re-downloading: {n}"),
    ("upd.cache.del.fail", "无法删除损坏的缓存 {n}：{e}。请手动删除该文件后重试。", "Cannot delete corrupt cache {n}: {e}. Please remove the file manually and retry."),
    (
        "upd.cache.still.bad",
        "重新下载后 {n} 仍不是有效的 zip，更新已中止。请检查网络后重试。",
        "After re-downloading, {n} is still not a valid zip. Update aborted; check your network and retry.",
    ),
    (
        "upd.zip.bad",
        "更新包无法读取（可能下载损坏）：{e}。缓存已清理，请重试；服务已尝试恢复运行。",
        "Update package is unreadable (possibly a corrupt download): {e}. Cache cleared, please retry; the service was restarted.",
    ),
    // ---- 参数详解：中英同文，不翻译（ADR-0005）----
    (
        "param.help.model",
        "要加载的 GGUF 模型文件路径。这是最核心的参数——决定用哪个开源模型（如 Qwen、Llama、DeepSeek、GLM 等）。 模型越大、量化越高，占显存越多、效果与速度各异。路径必须是本机存在的 .gguf 文件。",
        "要加载的 GGUF 模型文件路径。这是最核心的参数——决定用哪个开源模型（如 Qwen、Llama、DeepSeek、GLM 等）。 模型越大、量化越高，占显存越多、效果与速度各异。路径必须是本机存在的 .gguf 文件。",
    ),
    (
        "param.help.ngl",
        "把多少层模型权重放到显卡显存里。数值越大越快（显存够时尽量拉满）。 设 0 = 纯 CPU 推理（极慢）。设 99 表示尽量全部上 GPU。 若显存不足会 OOM 崩溃，此时调小。效果无影响，只影响速度。",
        "把多少层模型权重放到显卡显存里。数值越大越快（显存够时尽量拉满）。 设 0 = 纯 CPU 推理（极慢）。设 99 表示尽量全部上 GPU。 若显存不足会 OOM 崩溃，此时调小。效果无影响，只影响速度。",
    ),
    (
        "param.help.ctx_size",
        "上下文窗口大小，即可同时『记住』的最长对话长度（含历史）。 越大能处理的文档/对话越长，但占用显存越多、加载越慢。 常用档位：32K（轻量）/128K（本机 24G 稳妥）/256K（需配 KV 量化）/512K~1M（长文档，强烈建议 KV 量化）。 点下方快捷按钮即可一键跳到档位。注：旧参数里 '-c' 是 '--ctx-size' 简写，冲突时本工具只保留一个。",
        "上下文窗口大小，即可同时『记住』的最长对话长度（含历史）。 越大能处理的文档/对话越长，但占用显存越多、加载越慢。 常用档位：32K（轻量）/128K（本机 24G 稳妥）/256K（需配 KV 量化）/512K~1M（长文档，强烈建议 KV 量化）。 点下方快捷按钮即可一键跳到档位。注：旧参数里 '-c' 是 '--ctx-size' 简写，冲突时本工具只保留一个。",
    ),
    (
        "param.help.spec_type",
        "投机解码：让『草稿』先批量猜多个 token，主模型一次验证整批，从而提速。 常见选 draft-mtp（用模型自带的 MTP 头，无需额外文件）。 注意 MTP 会强制单槽（-np 1），且 LLM 类模型才有效；嵌入/小模型无需开。",
        "投机解码：让『草稿』先批量猜多个 token，主模型一次验证整批，从而提速。 常见选 draft-mtp（用模型自带的 MTP 头，无需额外文件）。 注意 MTP 会强制单槽（-np 1），且 LLM 类模型才有效；嵌入/小模型无需开。",
    ),
    ("param.opt.spec_type.none", "不启用投机解码（标准单 token 生成）。", "不启用投机解码（标准单 token 生成）。"),
    (
        "param.opt.spec_type.draft_mtp",
        "MTP：用模型内置的『预测下一 token』头做草稿，提速明显，无需额外文件。推荐 27B 类模型。",
        "MTP：用模型内置的『预测下一 token』头做草稿，提速明显，无需额外文件。推荐 27B 类模型。",
    ),
    (
        "param.opt.spec_type.ngram_simple",
        "n-gram 草稿：基于历史 token 的统计预测，零额外成本但提速有限。",
        "n-gram 草稿：基于历史 token 的统计预测，零额外成本但提速有限。",
    ),
];

/// `(zh, en)` for a key, or `None` when the table has no such key.
pub fn entry(key: &str) -> Option<(&'static str, &'static str)> {
    // ponytail: linear scan over ~90 entries; fine for once-per-render. If the
    // table ever grows by an order of magnitude, keep it sorted and bisect.
    STRINGS.iter().find(|(k, _, _)| *k == key).map(|(_, zh, en)| (*zh, *en))
}

/// The copy for a key in one specific language, `None` if the key is unknown.
pub fn t_in(key: &str, lang: Lang) -> Option<&'static str> {
    let (zh, en) = entry(key)?;
    Some(match lang {
        Lang::Zh => zh,
        Lang::En => en,
    })
}

/// The copy for a key in the active language.
///
/// A missing key renders as the key itself — never blank, and the gap is
/// obvious in the UI. An empty key has nothing to echo, so it renders `?`.
pub fn t(key: &str) -> &str {
    match t_in(key, language()) {
        Some(s) => s,
        None if key.is_empty() => "?",
        None => key,
    }
}

/// The whole table for one language, ready to cross the IPC boundary: the
/// frontend fetches this once and looks keys up. It is a cache of this table,
/// not a second translation — nothing here may be edited on the other side.
pub fn snapshot(lang: Lang) -> BTreeMap<&'static str, &'static str> {
    STRINGS
        .iter()
        .map(|(k, zh, en)| (*k, if lang == Lang::Zh { *zh } else { *en }))
        .collect()
}

/// Copy with `{name}` placeholders filled. An unknown placeholder is left
/// visible rather than dropped, so a missing argument shows up as text instead
/// of vanishing silently.
pub fn fmt(key: &str, fields: &[(&str, &str)]) -> String {
    let src = t(key);
    let mut out = String::with_capacity(src.len());
    let mut rest = src;
    while let Some(at) = rest.find('{') {
        let (before, after) = rest.split_at(at);
        out.push_str(before);
        match after.find('}') {
            Some(end) if end > 1 => {
                let name = &after[1..end];
                match fields.iter().find(|(k, _)| *k == name) {
                    Some((_, v)) => out.push_str(v),
                    None => out.push_str(&after[..=end]),
                }
                rest = &after[end + 1..];
            }
            _ => {
                out.push_str(after);
                rest = "";
            }
        }
    }
    out.push_str(rest);
    out
}

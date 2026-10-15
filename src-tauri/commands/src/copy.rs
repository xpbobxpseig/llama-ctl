//! Strings this layer produces that `core::i18n::STRINGS` does not carry.
//!
//! Ticket 08 settled that Rust owns the *skeleton* copy, and that table lives in
//! `core::i18n`. It covers the labels, buttons, log lines and the update
//! section — but not the message-box copy this layer returns inside
//! `AppError` (the `msg.*` family of `strings.py`), which ticket 08 did not
//! migrate. Rather than ship untranslated keys or English-only errors, they
//! live here in the same `(key, zh, en)` shape.
//!
//! [`t`] looks in `core::i18n` **first**, so anything ticket 08 already owns is
//! answered from there and the two tables cannot disagree; this one is only the
//! fallback. Folding these into `core::i18n::STRINGS` is a one-line-per-entry
//! move once that table may grow — the shape is deliberately identical.
//!
//! A key neither table has renders as the key itself, as in `core::i18n`: a gap
//! is visible instead of blank.

use llama_ctl_core::i18n;

pub const EXTRA: &[(&str, &str, &str)] = &[
    ("msg.no.service", "还没有选中服务。", "No service selected."),
    ("msg.svc.notfound", "{s} 不是本机的 NSSM 服务。", "{s} is not an NSSM service on this machine."),
    ("msg.write.fail", "写入服务参数失败：{o}", "Failed to write service parameters: {o}"),
    ("msg.sc.fail", "执行 sc {a} 失败：{m}", "sc {a} failed: {m}"),
    ("msg.auto.fail", "切换开机自启失败：{o}", "Failed to change the start mode: {o}"),
    ("msg.preset.miss", "预设「{n}」不存在。", "Preset \"{n}\" does not exist."),
    ("msg.preset.empty", "预设名不能为空。", "Preset name cannot be empty."),
    ("msg.bad.action", "不支持的操作：{a}", "Unsupported action: {a}"),
    ("msg.channel.changed", "二进制版本已变更，请重新检查更新。", "The build variant changed since the last check; re-check for updates."),
    (
        "log.restart.waiting",
        "等待服务就绪…（已 {s} 秒）",
        "Waiting for the service to answer… ({s}s)",
    ),
    (
        "log.restart.notready",
        "等待超时：{s} 未在预期时间内探活成功（可能仍在加载模型）。",
        "Timed out: {s} did not answer the probe in time (it may still be loading the model).",
    ),
    // CONTEXT.md: an Auto backup is a **preset** with a timestamped name, not
    // the file Backup an update makes.
    ("preset.autobackup", "自动备份 {t}", "Auto backup {t}"),
];

/// The copy for `key` in the active language: `core::i18n` first, this table
/// second, the key itself as a last resort.
pub fn t(key: &str) -> String {
    match i18n::t_in(key, i18n::language()) {
        Some(s) => s.to_string(),
        None => EXTRA
            .iter()
            .find(|(k, _, _)| *k == key)
            .map(|(_, zh, en)| if i18n::language() == i18n::Lang::Zh { *zh } else { *en })
            .unwrap_or(key)
            .to_string(),
    }
}

/// [`t`] with `{name}` placeholders filled. An unknown placeholder is left
/// visible rather than dropped, so a missing argument shows up as text instead
/// of vanishing silently.
pub fn fmt(key: &str, fields: &[(&str, &str)]) -> String {
    let src = t(key);
    let mut out = String::with_capacity(src.len());
    let mut rest = src.as_str();
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

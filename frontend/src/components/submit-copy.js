/**
 * Copy for the submit side: Apply / Revert / presets (ticket 17).
 *
 * Rust owns the copy (ADR-0005), so [`pt`] asks the Snapshot's string table
 * *first*, then `SHELL_COPY`, then this table — the same shape ticket 14's
 * [`ct`] uses, and for the same reason: the day these keys move into
 * `core::i18n::STRINGS` (or `commands::copy::EXTRA`) this file becomes dead
 * code that can be deleted wholesale, with no component edit.
 *
 * What is missing upstream, checked key by key against
 * `src-tauri/core/src/i18n.rs` and `src-tauri/commands/src/copy.rs`:
 *   - `mb.unchanged` / `mb.success` / `mb.hint` / `mb.confirm` — the message
 *     box chrome. Python has them in `strings.py`; neither Rust table does.
 *   - `msg.nochange` / `msg.written` — Apply's two outcomes. `msg.nochange` is
 *     the **textual** verdict Rust returns as `written: false`.
 *   - `msg.apply.run` / `msg.apply.stop` are deliberately *not* reused: Python
 *     filled `{n}` / `{o}` with the whole parameter strings, and this ticket
 *     renders the old text and a per-field diff instead (a 300-character diff
 *     is unreadable). The new keys carry only `{s}`.
 *   - `msg.preset.del` / `msg.svc.dirty` / `preset.autobackup` — `strings.py`
 *     L87 / L103 and `copy.rs`; `preset.autobackup` is in `copy::EXTRA` but
 *     **not** in `Snapshot.strings`, so a client-side copy is unavoidable.
 *   - `btn.save`, `preset.loaded`, `guard.*`, `apply.*` — new to this ticket.
 */

import * as store from '../stores/snapshot.js'

export const SUBMIT_COPY = {
  'mb.unchanged': { zh: '无需改动', en: 'No changes' },
  'mb.success': { zh: '成功', en: 'Success' },
  'mb.hint': { zh: '提示', en: 'Hint' },
  'mb.confirm': { zh: '确认', en: 'Confirm' },

  // Apply's own verdict. `written === false` is Rust's **textual** comparison,
  // not a semantic one: Apply is the normalisation pass (CONTEXT.md).
  'msg.nochange': {
    zh: '参数与当前服务一致。',
    en: 'Parameters already match the service.',
  },
  'msg.written': {
    zh: '已写回。服务未运行，下次启动即生效。',
    en: 'Written. Service not running; takes effect on next start.',
  },
  'msg.apply.needs_restart': {
    zh: '已写回。服务仍在运行，需重启后才生效。',
    en: 'Written. The service is running; restart for it to take effect.',
  },
  'msg.apply.synced': {
    zh: '预设「{n}」已同步为当前值。',
    en: 'Preset "{n}" synced to the current values.',
  },
  'msg.apply.same': {
    zh: '表单与服务参数一致；写回只做规范化（统一写法与顺序）。',
    en: 'The form already matches the service; writing only normalises the text.',
  },
  'apply.intro.run': {
    zh: '服务「{s}」正在运行：写回后需重启才生效。下面是新旧参数对比：',
    en: 'Service "{s}" is running: restart it after the write. Old vs new:',
  },
  'apply.intro.stop': {
    zh: '即将写回服务「{s}」的 NSSM AppParameters。下面是新旧参数对比：',
    en: 'About to write NSSM AppParameters for "{s}". Old vs new:',
  },
  'apply.old': { zh: '服务当前参数（原文）', en: 'Current parameters (verbatim)' },
  'apply.changed': { zh: '改动 {n} 项', en: 'Changed ({n})' },
  'apply.from': { zh: '原值', en: 'Old' },
  'apply.to': { zh: '新值', en: 'New' },
  'apply.blank': { zh: '（空）', en: '(empty)' },

  'msg.preset.del': { zh: '删除预设「{n}」？', en: 'Delete preset "{n}"?' },
  'msg.preset.name': {
    zh: '请先输入或选择一个预设名。',
    en: 'Type or pick a preset name first.',
  },
  'msg.preset.saved': { zh: '已保存为预设「{n}」。', en: 'Saved as preset "{n}".' },
  'msg.preset.exists': {
    zh: '预设「{n}」已存在，未覆盖（保存为 no-op）。',
    en: 'Preset "{n}" already exists; nothing was overwritten (a no-op).',
  },
  'msg.preset.deleted': { zh: '预设「{n}」已删除。', en: 'Preset "{n}" deleted.' },
  'msg.preset.noload': {
    zh: '预设「{n}」不存在。',
    en: 'Preset "{n}" does not exist.',
  },
  'preset.loaded': { zh: '已载入「{n}」', en: 'Loaded "{n}"' },
  'preset.placeholder': { zh: '输入或选择预设名', en: 'Type or pick a preset name' },
  'btn.save': { zh: '保存', en: 'Save' },

  // Switching away from a form with unapplied changes. Both are confirmations,
  // and the auto-backup is a *preset* with a timestamped name (CONTEXT.md),
  // not the file Backup an update makes.
  'msg.svc.dirty': {
    zh: '当前表单有未应用的更改，切换服务将丢失。',
    en: 'The form has unapplied changes. Switching the service discards them.',
  },
  'msg.preset.dirty': {
    zh: '当前表单有未应用的更改，载入预设将覆盖它们。',
    en: 'The form has unapplied changes. Loading a preset overwrites them.',
  },
  'guard.backup': { zh: '先备份再继续', en: 'Auto-backup and continue' },
  'guard.discard': { zh: '不备份，继续', en: 'Continue without backup' },
  'guard.target': { zh: '目标：{t}', en: 'Target: {t}' },
  'preset.autobackup': { zh: '自动备份 {t}', en: 'Auto backup {t}' },
}

/** Fill `{name}` placeholders; an unknown one stays visible. */
function fill(raw, fields) {
  return raw.replace(/\{(\w+)\}/g, (whole, name) =>
    name in fields ? String(fields[name]) : whole,
  )
}

/**
 * Translate `key` for this ticket's controls.
 *
 * Upstream first: when Rust (or the shell table) answers, this returns that
 * answer unchanged, so nothing here can contradict what Rust decided to say.
 */
export function pt(key, fields) {
  const upstream = store.t(key, fields)
  if (upstream !== key) return upstream
  const local = SUBMIT_COPY[key]?.[store.lang.value] ?? key
  return fields ? fill(local, fields) : local
}

/**
 * The Auto-backup preset name: `preset.autobackup` with the clock filled in.
 *
 * Python built it from `time.strftime('%m-%d %H:%M:%S')`; this is the same
 * shape from the browser's clock. It is a *name*, not a decision — Rust still
 * decides whether the backup is stored at all (it skips a form that is
 * semantically identical to the service).
 */
export function autoBackupName(now = new Date()) {
  const p = (n) => String(n).padStart(2, '0')
  const t = `${p(now.getMonth() + 1)}-${p(now.getDate())} ${p(now.getHours())}:${p(
    now.getMinutes(),
  )}:${p(now.getSeconds())}`
  return pt('preset.autobackup', { t })
}

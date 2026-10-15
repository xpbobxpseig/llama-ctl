/**
 * Copy for the official-update section (ticket 15).
 *
 * Rust owns the copy (ADR-0005), and it owns almost all of this ticket's: the
 * whole `upd.*` family lives in `core::i18n::STRINGS` (checked key by key). The
 * handful below is what the section needs on top of that — the transcript's own
 * label, the "where the old files go" line the confirmation shows, and the
 * variant hint. [`ut`] therefore asks the Snapshot's string table *first*, then
 * `SHELL_COPY`, and only then this table, so the day these keys move into Rust
 * this file becomes dead code and can be deleted with no component edit.
 *
 * Deliberately *not* duplicated here: `upd.section`, `upd.channel`,
 * `upd.check`, `upd.status.*`, `upd.changelog`, `upd.assets`, `upd.install`,
 * `upd.install.confirm`, `upd.uptodate*` — Rust has all of them, in both
 * languages, and a second copy could drift from what Rust decided to say.
 */

import * as store from '../stores/snapshot.js'

export const UPDATE_COPY = {
  // The progress transcript's own chrome.
  'upd.progress': { zh: '更新进度', en: 'Install progress' },
  'upd.progress.empty': {
    zh: '更新开始后，每一步都会实时显示在这里。',
    en: 'Every step appears here live, as the install runs.',
  },
  // The confirmation's second half: where the old files are going.
  'upd.backup.where': { zh: '旧文件备份到：', en: 'Old files are backed up to:' },
  'upd.backup.preview': {
    zh: '（备份目录由 Rust 按时间戳创建，形如上面路径下的 年-月-日_时-分-秒）',
    en: '(Rust creates the backup directory from its own timestamp, as YYYY-MM-DD_HH-MM-SS under the path above)',
  },
  // What the install did, once it is done.
  'upd.result': {
    zh: '更新完成：替换 {r} 个文件，新增 {a} 个，下载 {d} 个资产。',
    en: 'Update complete: {r} replaced, {a} added, {d} assets downloaded.',
  },
  // The variant hint: the replacement target is the service's own directory.
  'upd.channel.hint': {
    zh: '选择与显卡匹配的构建线；切换后需要重新检查。',
    en: 'Pick the build matching your GPU; changing it requires a re-check.',
  },
  // The startup check's own switch. Rust has the label (`upd.auto.label`), so
  // only the two states are local.
  'upd.auto.on': { zh: '开', en: 'On' },
  'upd.auto.off': { zh: '关', en: 'Off' },
  // "Check" in flight vs at rest — Rust's `upd.checking` is the busy hint, and
  // this is the button's own label while it runs.
  'upd.check.now': { zh: '检查中…', en: 'Checking…' },
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
export function ut(key, fields) {
  const upstream = store.t(key, fields)
  if (upstream !== key) return upstream
  const local = UPDATE_COPY[key]?.[store.lang.value] ?? key
  return fields ? fill(local, fields) : local
}

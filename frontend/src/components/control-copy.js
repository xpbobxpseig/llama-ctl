/**
 * Copy for the service control bar and the log tail (ticket 14).
 *
 * Rust owns the copy (ADR-0005). [`ct`] therefore asks the Snapshot's string
 * table *first*, then `SHELL_COPY`, and only then this table — so the day these
 * keys move into `core::i18n::STRINGS` (or `commands::copy::EXTRA`) this file
 * becomes dead code and can be deleted wholesale, with no component edit.
 *
 * They live here rather than in `src/api/shell-copy.js` because that file is
 * ticket 13's working set; the shape is identical, so migrating them is the
 * same one-line-per-entry move.
 *
 * What is missing upstream, checked key by key against
 * `src-tauri/core/src/i18n.rs` and `src-tauri/commands/src/copy.rs`:
 *   - `mb.doublecheck` / `btn.cancel` / `btn.confirm` — the confirmation
 *     dialog's own chrome. Python has them in `strings.py`; neither Rust table
 *     does.
 *   - `msg.restart.confirm` — Python never confirmed a restart (it just
 *     started the worker); spec item 44 requires it.
 *   - `msg.auto.confirm` — `strings.py` L102; Rust has `msg.auto.fail` but not
 *     the question.
 *   - `msg.restarting` — `strings.py` L93; the busy hint the bar already used.
 *   - `log.path` / `log.empty` / `log.demo` — the log region's own labels.
 */

import * as store from '../stores/snapshot.js'

export const CONTROL_COPY = {
  'mb.doublecheck': { zh: '二次确认', en: 'Double-check' },
  'btn.cancel': { zh: '取消', en: 'Cancel' },
  'btn.confirm': { zh: '确定', en: 'OK' },
  'msg.restarting': { zh: '重启进行中，请稍候…', en: 'Restart in progress…' },
  'msg.restart.confirm': {
    zh: '重启服务「{s}」？服务会先停止再启动，期间推理请求会中断。',
    en: 'Restart "{s}"? The service is stopped and started again; in-flight requests are dropped.',
  },
  'msg.auto.confirm': {
    zh: '将开机自启设为「{m}」？',
    en: 'Set auto-start to "{m}"?',
  },
  'log.path': { zh: '文件：{p}', en: 'File: {p}' },
  'log.empty': { zh: '暂无日志输出', en: 'No output yet' },
  'log.demo': {
    zh: '演示日志：未连接 Rust 后端，下面是 server.err 的示例内容',
    en: 'Demo log: not connected to the Rust backend; sample server.err content below',
  },
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
export function ct(key, fields) {
  const upstream = store.t(key, fields)
  if (upstream !== key) return upstream
  const local = CONTROL_COPY[key]?.[store.lang.value] ?? key
  return fields ? fill(local, fields) : local
}

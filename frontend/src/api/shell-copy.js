/**
 * Shell copy for keys Rust does not own yet.
 *
 * Ticket 08 migrated the skeleton table into `core::i18n::STRINGS`, and ticket
 * 11 added the `msg.*` family in `commands::copy::EXTRA`. The handful below is
 * what the shell needs but neither table carries — checked by key against both
 * (`src-tauri/core/src/i18n.rs`, `src-tauri/commands/src/copy.rs`).
 *
 * They are listed here rather than invented as different keys, so migrating
 * them is a one-line-per-entry move into Rust and a delete here. Until then
 * `t()` answers them from this table instead of rendering a raw key.
 *
 * ADR-0005 still holds: these are *skeleton* strings (labels and buttons), not
 * parameter explanations, and no component ships a translation of its own
 * beyond this file.
 */
export const SHELL_COPY = {
  'settings.appear': { zh: '外观', en: 'Appearance' },
  'settings.motion': {
    zh: '动效（关闭后所有动画直跳终态）',
    en: 'Motion (off = instant, no animation)',
  },
  'settings.note': {
    zh: '几何与预设记忆自动生效，无需设置。',
    en: 'Geometry & last-preset memory are automatic.',
  },
  'appear.system': { zh: '跟随系统', en: 'System' },
  'appear.light': { zh: '浅色', en: 'Light' },
  'appear.dark': { zh: '深色', en: 'Dark' },
  'mb.error': { zh: '错误', en: 'Error' },
  // The shell's own actions, not in the Python string table either.
  'shell.retry': { zh: '重试', en: 'Retry' },
  'shell.rescan': { zh: '重新扫描', en: 'Rescan' },
  'shell.no_service': { zh: '尚未发现 NSSM 服务', en: 'No NSSM service found yet' },
  'shell.demo': {
    zh: '演示数据：未连接到 Rust 后端',
    en: 'Demo data: not connected to the Rust backend',
  },
}

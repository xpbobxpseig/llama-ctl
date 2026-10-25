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
 * beyond this file. The `param.*` explanations ticket 13 needs live in
 * `src/api/field-copy.js` for the same reason.
 */
export const SHELL_COPY = {
  'preset.delete': { zh: '删除', en: 'Delete' },
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
  // Ticket 13: the parameter form's expand/collapse-all.
  'shell.expand_all': { zh: '全部展开', en: 'Expand all' },
  'shell.collapse_all': { zh: '全部收起', en: 'Collapse all' },
  'shell.demo': {
    zh: '演示数据：未连接到 Rust 后端',
    en: 'Demo data: not connected to the Rust backend',
  },
  // The rail / workspace chrome (this redesign). Rust does not own these yet.
  'rail.status': { zh: '服务状态', en: 'Service status' },
  'rail.args': { zh: '启动参数', en: 'Launch args' },
  'params.search': { zh: '搜索参数', en: 'Search parameters' },
  'params.no_results': { zh: '没有匹配的参数', en: 'No matching parameters' },
  'log.clear': { zh: '清空', en: 'Clear' },
  'settings.desc': {
    zh: '界面、外观与官方更新',
    en: 'Interface, appearance and official updates',
  },
  'settings.section.interface': { zh: '界面', en: 'Interface' },
  'settings.section.motion': { zh: '动效', en: 'Motion' },
  'settings.language.label': { zh: '界面语言', en: 'Language' },
  'settings.language.note': {
    zh: '参数详解保持中文',
    en: 'Parameter guides stay Chinese',
  },
  'settings.appearance.note': {
    zh: '跟随系统时随 Windows 切换',
    en: 'Follows Windows while set to System',
  },
  'settings.motion.label': { zh: '界面动效', en: 'Interface motion' },
  'settings.motion.note': {
    zh: '关闭后所有动画直跳终态',
    en: 'Off = instant, no animation',
  },
}

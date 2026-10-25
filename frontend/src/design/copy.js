/**
 * 设计层的文案表（拉马管家）。
 *
 * zh 是基准稿文案，en 是同一句的英文，保证双语能力不丢；弹层与新增
 * 控件（半透明材质 / 缩放滑条 / 关于页 / 清空日志）按稿中令牌延伸。
 */
export const C = {
  appName: ['拉马管家', '拉马管家'],
  params: ['参数', 'Params'],
  logs: ['日志', 'Logs'],
  presets: ['预设', 'Presets'],
  settings: ['设置', 'Settings'],
  about: ['关于', 'About'],
  svc: ['服务', 'Services'],
  all: ['全部', 'All'],
  changed: ['已改', 'Changed'],
  switchService: ['切换服务', 'Switch service'],
  startSvc: ['启动服务', 'Start service'],
  stopSvc: ['停止服务', 'Stop service'],
  restartSvc: ['重启服务', 'Restart service'],
  openDir: ['打开安装目录', 'Open install folder'],
  more: ['更多', 'More'],
  minimize: ['最小化', 'Minimize'],
  maximize: ['最大化', 'Maximize'],
  close: ['关闭', 'Close'],
  following: ['跟随中 · {t}', 'Following · {t}'],
  paused: ['已暂停', 'Paused'],
  mine: ['我的预设', 'My presets'],
  backups: ['自动备份', 'Auto backups'],
  autobackup: ['自动备份 {t}', 'Auto backup {t}'],
  load: ['载入', 'Load'],
  loaded: ['已载入', 'Loaded'],
  del: ['删除', 'Delete'],
  version: ['版本', 'Version'],
  current: ['当前', 'Current'],
  latest: ['最新', 'Latest'],
  startup: ['启动', 'Startup'],
  autoStart: ['开机自启', 'Start at boot'],
  advanced: ['高级信息', 'Advanced'],
  appDir: ['安装目录', 'Install folder'],
  appParams: ['启动参数', 'Launch parameters'],
  view: ['查看', 'View'],
  update: ['更新', 'Update'],
  checkNow: ['检查', 'Check'],
  upToDate: ['已是最新', 'Up to date'],
  ui: ['界面', 'Interface'],
  lang: ['语言', 'Language'],
  appearance: ['外观', 'Appearance'],
  font: ['字体', 'Font'],
  uiScale: ['界面缩放', 'UI scale'],
  uiFont: ['界面字体', 'UI font'],
  monoFont: ['等宽字体', 'Monospace font'],
  fontDefault: ['默认', 'Default'],
  motion: ['界面动效', 'Motion'],
  mica: ['半透明材质', 'Translucent material'],
  micaHint: ['Acrylic 材质，可透出桌面；关闭后界面不透明', 'Acrylic material; off = opaque'],
  updates: ['更新', 'Updates'],
  checkOnStart: ['启动时检查', 'Check on startup'],
  license: ['许可', 'Licenses'],
  system: ['跟随系统', 'System'],
  light: ['浅色', 'Light'],
  dark: ['深色', 'Dark'],
  appTagline: ['让 llama.cpp 成为随手可用的本地服务', 'Make llama.cpp a ready-to-use local service'],
  appVersion: ['拉马管家 版本', '拉马管家 version'],
  llamaBuild: ['llama.cpp 构建', 'llama.cpp build'],
  stackSec: ['技术栈', 'Tech stack'],
  quickSec: ['快捷入口', 'Quick links'],
  checkUpdates: ['检查更新', 'Check for updates'],
  homepage: ['llama.cpp 主页', 'llama.cpp homepage'],
  devBy: ['由 llama_ctl 开发 · © 2026 拉马管家', 'Developed by llama_ctl · © 2026 拉马管家'],
  copyBtn: ['复制', 'Copy'],
  copied: ['已复制', 'Copied'],
  clearLog: ['清空', 'Clear'],
  healthOk: ['探活 OK', 'Probe OK'],
  stopped: ['已停止', 'Stopped'],
  healthIdle: ['探活 —', 'Probe —'],
  dirtyN: ['{n} 项未应用', '{n} unapplied'],
  revert: ['还原', 'Revert'],
  apply: ['应用更改', 'Apply changes'],
  cancel: ['取消', 'Cancel'],
  confirm: ['继续', 'Continue'],
  savePreset: ['保存为预设', 'Save as preset'],
  name: ['名称', 'Name'],
  changes: ['更改内容', 'Changes'],
  backupAndSwitch: ['另存并切换', 'Back up & switch'],
  discard: ['放弃更改', 'Discard'],
  guardService: ['「{n}」有未应用的更改。切换会丢掉这些编辑。', '{n} has unapplied changes. Switching discards them.'],
  guardPreset: ['有未应用的更改。载入预设会丢掉这些编辑。', 'There are unapplied changes. Loading a preset discards them.'],
  restartAsk: ['重启会中断正在进行的推理，服务会短暂离线。继续？', 'Restarting interrupts in-flight inference and the service goes offline briefly. Continue?'],
  stopAsk: ['停止后服务不再响应请求。继续？', 'The service stops answering requests. Continue?'],
  deleteAsk: ['删除预设「{n}」？', 'Delete preset {n}?'],
  autoAsk: ['开机自启将改为「{m}」。继续？', 'Start at boot will be set to {m}. Continue?'],
  installAsk: ['将停止服务并替换 llama.cpp 二进制，旧文件会先备份。继续？', 'The service stops and the llama.cpp binaries are replaced; old files are backed up first. Continue?'],
  noService: ['还没有选中服务。', 'No service selected.'],
  working: ['正在执行…', 'Working…'],
  noChanges: ['没有未应用的更改。', 'No unapplied changes.'],
  presetSaved: ['已保存「{n}」', 'Saved {n}'],
  presetExists: ['「{n}」已存在', '{n} already exists'],
  presetDeleted: ['已删除「{n}」', 'Deleted {n}'],
  needsRestart: ['已写入服务，重启后生效。', 'Written; takes effect after a restart.'],
  applied: ['已应用。', 'Applied.'],
  licenseBody: [
    'Tauri 2 · MIT / Apache-2.0\nVue 3 · MIT\n\n随包字体（SIL OFL 1.1）：Cascadia Code',
    'Tauri 2 · MIT / Apache-2.0\nVue 3 · MIT\n\nBundled font (SIL OFL 1.1): Cascadia Code',
  ],
}

/**
 * 取一条文案并填充 `{name}` 占位。
 * @param {string} key C 的键
 * @param {'zh'|'en'} lang 界面语言（来自 Snapshot，前端不猜）
 * @param {Record<string, unknown>} [fields]
 */
export function t(key, lang, fields) {
  const entry = C[key]
  const raw = entry ? (lang === 'en' ? entry[1] : entry[0]) : key
  if (!fields) return raw
  return raw.replace(/\{(\w+)\}/g, (whole, name) => (name in fields ? String(fields[name]) : whole))
}

/**
 * 自动备份名（切换服务/载入预设前存一份当前表单）。
 * 与 PresetsView 的备份分组前缀一致：`自动备份 MM-DD HH:MM:SS`。
 * @param {Date} [now]
 */
export function autoBackupName(now = new Date()) {
  const p = (n) => String(n).padStart(2, '0')
  const stamp = `${p(now.getMonth() + 1)}-${p(now.getDate())} ${p(now.getHours())}:${p(now.getMinutes())}:${p(now.getSeconds())}`
  return t('autobackup', 'zh', { t: stamp })
}

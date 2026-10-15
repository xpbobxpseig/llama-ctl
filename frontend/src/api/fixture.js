/**
 * Fixture Snapshot — **demo data**, used when the app runs outside the Tauri
 * shell (a plain browser, or the component tests tickets 13-17 add).
 *
 * Its shape is ticket 11's `Snapshot` contract exactly, so a component fed
 * this renders the same tree it renders in production. It is never sent to
 * Rust and never shown as authoritative: the demo banner in `App.vue` says so
 * on screen.
 */

const STRINGS = {
  'app.title': 'llama.cpp 服务控制台',
  'card.params': '启动参数',
  'card.presets': '参数预设',
  'svc.label': '服务',
  'state.unknown': '服务 —',
  'health.idle': '探活 —',
  'boot.label': '开机自启',
  'boot.auto': '自动(开机)',
  'boot.manual': '手动',
  'boot.disabled': '禁用',
  'btn.start': '启动',
  'btn.stop': '停止',
  'btn.restart': '重启',
  'btn.revert': '还原',
  'btn.apply2': '应用更改',
  'btn.settings': '⚙ 设置',
  'settings.title': '设置',
  'settings.lang': '界面语言（参数详解保持中文）',
  'settings.appear': '外观',
  'settings.motion': '动效（关闭后所有动画直跳终态）',
  'settings.note': '几何与预设记忆自动生效，无需设置。',
  'settings.close': '关闭',
  'appear.system': '跟随系统',
  'appear.light': '浅色',
  'appear.dark': '深色',
  'status.svc': '服务 {st}',
  'status.health.ok': '探活 OK · {d}',
  'status.health.bad': '探活 FAIL · {d}',
  'status.dirty': '● 有未应用的更改',
  'log.collapsed': '日志尾随 server.err（已折叠）',
  'log.expanded': '日志尾随 server.err（点击折叠）',
  'upd.section': '官方更新',
  'upd.check': '立即检查更新',
  'upd.status.now': '当前：{b}',
  'upd.status.unknown': '当前版本未知（无法读取 llama-server.exe）',
  'upd.status.none': '还未检查过更新',
  'upd.uptodate': '已是最新',
}

/** A Snapshot as Rust would return it, for the demo service `QwenLLM`. */
export function demoSnapshot(overrides = {}) {
  return {
    services: ['QwenLLM', 'QwenVL', 'llama-bench'],
    selected: 'QwenLLM',
    facts: {
      app_dir: 'F:\\llama.cpp',
      app_params:
        '-m F:\\models\\Qwen3-32B-Q4_K_M.gguf --host 127.0.0.1 --port 8080 -c 131072 -ngl 999 --no-mmap',
      start: 'auto',
      dirty: false,
    },
    status: { state: 'RUNNING', ok: true, detail: 'healthz ok · 127.0.0.1:8080 · b5527' },
    values: {
      model: 'F:\\models\\Qwen3-32B-Q4_K_M.gguf',
      mmproj: '',
      ngl: '999',
      ctx: '131072',
      host: '127.0.0.1',
      port: '8080',
      threads: '16',
      temp: '0.8',
      'no-mmap': 'true',
      'mlock': 'false',
    },
    extras: [],
    warnings: [],
    preset_loaded: '',
    presets: ['32B 长上下文', '7B 快速', '自动备份 03-14 09:12:41'],
    settings: {
      language: 'zh',
      appearance: 'system',
      geometry: null,
      last_preset: '',
      motion_enabled: true,
      upd_check_on_startup: true,
      upd_channel: 'win-cuda-13.4-x64',
      services: ['QwenLLM', 'QwenVL', 'llama-bench'],
    },
    channels: [
      ['win-cuda-13.4-x64', 'CUDA 13.4'],
      ['win-cuda-12.4-x64', 'CUDA 12.4'],
      ['win-vulkan-x64', 'Vulkan'],
      ['win-cpu-x64', 'CPU'],
    ],
    strings: STRINGS,
    lang: 'zh',
    ...overrides,
  }
}

/** The empty case: no service known, so the shell renders its empty state. */
export function emptySnapshot() {
  return demoSnapshot({
    services: [],
    selected: '',
    facts: null,
    status: { state: 'UNKNOWN', ok: false, detail: 'not probed' },
    values: {},
    presets: [],
    settings: { ...demoSnapshot().settings, geometry: null, services: [] },
  })
}

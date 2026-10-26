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
  'btn.revert': '还原',
  'btn.restart': '重启',
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
  // Ticket 15: the whole `upd.*` family, exactly as Rust's `core::i18n` sends
  // it. The update section renders every one of these straight from the string
  // table, so the fixture has to carry them or the demo screen shows raw keys.
  'upd.section': '官方更新',
  'upd.channel': '二进制版本（替换 F:\\llama.cpp 下文件）',
  'upd.auto.label': '启动时自动检查（仅提示，绝不自动安装）',
  'upd.check': '立即检查更新',
  'upd.status.now': '当前：{b}',
  'upd.status.unknown': '当前版本未知（无法读取 llama-server.exe）',
  'upd.status.none': '还未检查过更新',
  'upd.checking': '正在检查官方最新版本…',
  'upd.check.done': '最新：{t}',
  'upd.uptodate': '已是最新',
  'upd.uptodate.msg': '当前 b{cur} 已是最新官方构建（b{new}）。',
  'upd.title': '发现新版本：{t}',
  'upd.prompt': '官方最新 b{n}（当前 b{c}）。是否查看更新日志并更新？',
  'upd.changelog': '更新日志',
  'upd.no.changelog':
    '官方 nightly 构建不提供更新说明。\n\n本次更新：{t}（build {b}）\n\n将下载并替换下面列出的文件；旧文件会先备份，任一步失败自动回滚。',
  'upd.assets': '下载内容：{a}',
  'upd.install': '立即更新',
  'upd.install.confirm':
    '将停止服务「{s}」并替换 llama.cpp 二进制。旧文件会备份到 {d}。\n\n继续？',
  'upd.installing': '正在更新 llama.cpp…',
  'upd.done': '更新完成：{s} 已重启，当前 b{b}。',
  'upd.err': '更新失败：{e}',
  'upd.required': '未找到匹配的官方资产。请确认二进制版本选择是否正确。',
  'msg.no.service': '还没有选中服务。',
  'btn.revert': '还原',
  'browse': '浏览',
}

/** A Snapshot as Rust would return it, for the demo service `QwenLLM`. */
export function demoSnapshot(overrides = {}) {
  return {
    services: ['QwenLLM', 'QwenVL', 'llama-bench'],
    selected: 'QwenLLM',
    facts: {
      app_dir: 'F:\\llama.cpp',
      app_params:
        '-m "F:\\models\\Qwen3-32B-Q4_K_M.gguf" -a qwen3-32b -ngl 99 --spec-type draft-mtp' +
        ' --ctx-size 131072 -ctk q8_0 -ctv q8_0 -fa auto -np 1 -b 2048 -ub 512 -t 16' +
        ' --temp 0.8 --min-p 0.05 --top-k 40 --top-p 0.95 --jinja --host 127.0.0.1' +
        ' --port 8080 --no-mmap',
      start: 'auto',
      dirty: false,
    },
    status: { state: 'RUNNING', ok: true, detail: 'healthz ok · 127.0.0.1:8080 · b5527' },
    values: {
      model: 'F:\\models\\Qwen3-32B-Q4_K_M.gguf',
      mmproj: '',
      alias: 'qwen3-32b',
      ngl: '99',
      spec_type: 'draft-mtp',
      spec_draft_model: '',
      spec_draft_n_max: '3',
      ctx_size: '131072',
      ctk: 'q8_0',
      ctv: 'q8_0',
      flash_attn: 'auto',
      parallel: '1',
      batch_size: '2048',
      ubatch_size: '512',
      threads: '16',
      temperature: '0.8',
      min_p: '0.05',
      top_k: '40',
      top_p: '0.95',
      seed: '',
      jinja: '1',
      chat_template_kwargs: '',
      host: '127.0.0.1',
      port: '8080',
      no_mmap: '1',
      mlock: '',
      no_kv_offload: '',
      cpu_moe: '',
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
      mica_enabled: true,
      upd_channel: 'win-cuda-13.4-x64',
      upd_check_on_startup: true,
      services: ['QwenLLM', 'QwenVL', 'llama-bench'],
    },
    // `updater::channels()` — Rust's own order and labels, verbatim, so the
    // demo dropdown is the list the window will really show.
    channels: [
      ['win-cuda-13.4-x64', 'CUDA 13.4 (x64)'],
      ['win-cuda-12.4-x64', 'CUDA 12.4 (x64)'],
      ['win-cpu-x64', 'CPU (x64)'],
      ['win-vulkan-x64', 'Vulkan (x64)'],
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

/**
 * An `UpdateCheck` as `check_update` returns it — **demo data**, in the same
 * shape Rust sends (`commands::snapshot::UpdateCheck`): the release, the
 * installed build, and whether the installed one already covers it.
 *
 * The asset *names* are the ones `updater::select_assets` produces for a
 * `b<N>` tag; the URLs are omitted entirely, because the renderer never uses
 * them and ADR-0001 keeps them out of the bundle.
 */
export function demoUpdateCheck(overrides = {}) {
  const build = 10819
  return {
    release: {
      tag: `b${build}`,
      name: `b${build}`,
      html_url: '',
      body: '',
      build,
      published_at: '',
      assets: [
        { name: `llama-b${build}-bin-win-cuda-13.4-x64.zip` },
        { name: `cudart-llama-b${build}-bin-win-cuda-13.4-x64.zip` },
      ],
    },
    installed: 10813,
    up_to_date: false,
    ...overrides,
  }
}


// ---- market（模型市场 demo 数据，spec: docs/spec/model-marketplace.md）----

export const demoMarket = {
  list: [
    {
      hub: 'ms', id: 'Qwen/Qwen3-0.6B-GGUF', name: 'Qwen3-0.6B-GGUF', downloads: 120000,
      likes: 88, license: 'Apache-2.0', task: 'text-generation', params_b: 0.6,
      size_hint: 639446688, gated: false,
    },
    {
      hub: 'ms', id: 'unsloth/Qwen3.8-27B-GGUF', name: 'Qwen3.8-27B-GGUF', downloads: 430000,
      likes: 150, license: 'apache-2.0', task: 'text-generation', params_b: 27,
      size_hint: 62000000000, gated: false,
    },
    {
      hub: 'ms', id: 'unsloth/Qwen3-30B-A3B-Instruct-GGUF', name: 'Qwen3-30B-A3B-Instruct-GGUF', downloads: 96000,
      likes: 77, license: 'apache-2.0', task: 'text-generation', params_b: 30,
      size_hint: 31000000000, gated: false,
    },
    {
      hub: 'ms', id: 'meta-llama/Llama-3.3-70B-Instruct-GGUF', name: 'Llama-3.3-70B-Instruct-GGUF', downloads: 185000,
      likes: 210, license: 'llama-3.3', task: 'text-generation', params_b: 70,
      size_hint: 42000000000, gated: true,
    },
  ],
  detail: {
    hub: 'ms', id: 'unsloth/Qwen3.8-27B-GGUF', downloads: 430000, gated: false,
    gguf: { architecture: 'qwen3', context_length: 40960, total_params: 26955292672 },
    variants: [
      {
        label: 'UD-IQ1_S', is_sharded: false, total_size: 6192222208,
        files: [{ path: 'Qwen3.8-27B-UD-IQ1_S.gguf', size: 6192222208, sha256: 'aa11' }],
        mmproj: { path: 'mmproj-Qwen3.8-27B-f16.gguf', size: 931145952, sha256: 'dd44' },
        fit: { tier: 'full_gpu', reason: '权重 6.2GB（含 1.5GB 余量）≈ 显存 24.0GB 的 32%，可全量 offload', offload_ratio: 100 },
      },
      {
        label: 'Q4_K_M', is_sharded: true, total_size: 27000000000,
        files: [
          { path: 'Qwen3.8-27B-Q4_K_M-00001-of-00002.gguf', size: 15000000000, sha256: 'bb22' },
          { path: 'Qwen3.8-27B-Q4_K_M-00002-of-00002.gguf', size: 12000000000, sha256: 'cc33' },
        ],
        mmproj: { path: 'mmproj-Qwen3.8-27B-f16.gguf', size: 931145952, sha256: 'dd44' },
        fit: { tier: 'partial_gpu', reason: '权重 27.0GB 超出显存 24.0GB，约 88% 可进显存，其余走内存（速度受 CPU/带宽限制）', offload_ratio: 88 },
      },
    ],
  },
  tasks: [
    {
      id: 'ms:Qwen/Qwen3-0.6B-GGUF:Q8_0', hub: 'ms', repo: 'Qwen/Qwen3-0.6B-GGUF', label: 'Q8_0',
      files: [], state: 'done', received: 639446688, total: 639446688, speed_bps: 0,
      error: null, added_at_ms: 1,
    },
  ],
  local: {
    hardware: {
      gpus: [{ name: 'NVIDIA GeForce RTX 4090', vendor: 'nvidia', vram_bytes: 25769803776 }],
      ram_total: 68719476736,
      cpu_name: 'AMD Ryzen 9 9950X',
    },
    models: [
      {
        path: 'F:/AI_Model/Qwen3.8/Qwen3.8-27B-CRACK-IQ4_XS.gguf', size: 15546361472,
        label: 'CRACK-IQ4_XS', is_sharded: false,
        mmproj: 'F:/AI_Model/Qwen3.8/mmproj-Qwen3.8-27B-f16.gguf',
        fit: { tier: 'full_gpu', reason: '权重 15.5GB（含 1.5GB 余量）≈ 显存 24.0GB 的 66%，可全量 offload', offload_ratio: 100 },
      },
      {
        path: 'F:/AI_Model/Qwen3.8-27B-Abliterated-Q4_K_M.gguf', size: 16810714496,
        label: 'Q4_K_M', is_sharded: false, mmproj: null,
        fit: { tier: 'full_gpu', reason: '权重 16.8GB（含 1.5GB 余量）≈ 显存 24.0GB 的 72%，可全量 offload', offload_ratio: 100 },
      },
    ],
    benchmarks: [
      { model_path: 'F:/AI_Model/Qwen3.8/Qwen3.8-27B-CRACK-IQ4_XS.gguf', pp_tps: 2234.87, tg_tps: 43.53, ngl: 99, benched_at_ms: 1 },
    ],
  },
}

/**
 * 模型市场 store — 发现/下载/已下载三区的状态与动作。
 *
 * 权威状态在 Rust（DownloadManager），这里只镜像：
 *  - 任务列表经 `EVENT_MARKET` 全量推送（payload 就是列表，零 diff）；
 *  - 实测行流经 `EVENT_BENCH`，直接落日志页（store.pushLog）；
 *  - 已下载区每次动作后重新 localScan，让 Rust 的扫描结果说话。
 * 浏览器 demo（非 Tauri）用内置静态数据，动作只改本地状态不发包。
 */
import { computed, reactive, readonly } from 'vue'
import * as ipc from '../api/ipc.js'
import { demoMarket } from '../api/fixture.js'
import * as snapshot from './snapshot.js'

const state = reactive({
  hub: 'ms',
  query: '',
  minB: 1, // 量级档位（0=全部）：默认 ≥1B，筛掉下载榜里的小模型
  list: [],
  detail: null,
  tasks: [],
  local: null, // { hardware, models, benchmarks }
  error: '',
  loaded: false,
  benchBusy: '',
  applyError: '',
  orderError: '',
})

const demo = demoMarket

function demoTasks() {
  return demoMarket.tasks
}

export const hub = computed(() => state.hub)
export const query = computed(() => state.query)
export const minB = computed(() => state.minB)
export const list = computed(() => {
  if (!state.minB) return state.list
  return state.list.filter((r) =>
    r.params_b != null
      ? r.params_b >= state.minB
      : (r.size_hint ?? 0) > 1.5 * 1024 ** 3,
  )
})
export const detail = computed(() => state.detail)
export const tasks = computed(() => state.tasks)
export const local = computed(() => state.local)
export const benchBusy = computed(() => state.benchBusy)
export const applyError = computed(() => state.applyError)
export const orderError = computed(() => state.orderError)
export const error = computed(() => state.error)
export const loaded = computed(() => state.loaded)

const settingsRoot = () => snapshot.settings.value?.market_download_root || 'F:\\AI_Model'

export function saveHub(h) {
  state.hub = h
  state.list = [] // 切源先清空：绝不让旧源的列表看起来「没刷新」
  state.orderError = 
  state.detail = null // 也退出详情：别让上一个源的详情盖住新源的结果
  const s = snapshot.settings.value
  if (s && ipc.isTauri()) {
    snapshot.run('save_settings', () =>
      ipc.saveSettings({ ...s, market_last_hub: h }).then(() => null))
  }
  return loadList()
}

export async function setQuery(q) {
  state.query = q
  state.detail = null // 同上：搜索时结果必须可见
  return loadList()
}

export function setMinB(n) {
  state.minB = Number(n) || 0
}

export async function loadList() {
  state.error = ''
  if (!ipc.isTauri()) {
    // demo 也要能搜：浏览器里搜索无反应会让整个演示不可信
    const q = state.query.trim().toLowerCase()
    state.list = q
      ? demo.list.filter((r) => `${r.id} ${r.name}`.toLowerCase().includes(q))
      : demo.list
    state.loaded = true
    return
  }
  const q = state.query.trim()
  const r = await snapshot.run('market_search', () =>
    q ? ipc.marketSearch(state.hub, q, 50) : ipc.marketHot(state.hub, 50))
  if (r) {
    state.list = r
    state.loaded = true
  } else {
    // 失败要可见：snapshot.error 已经是 errorLine() 出的展示串，直接用
    state.error = snapshot.error.value || 'market load failed'
  }
}

export async function openDetail(id) {
  if (!ipc.isTauri()) {
    state.detail = demo.detail
    return
  }
  const r = await snapshot.run('market_repo', () => ipc.marketRepo(state.hub, id))
  if (r) state.detail = r
}

export function closeDetail() {
  state.detail = null
}

export async function enqueue(variant, repoId) {
  const files = [...variant.files]
  if (variant.mmproj) files.push(variant.mmproj)
  const args = {
    hub: state.hub,
    repo: repoId,
    label: variant.label,
    root: settingsRoot(),
    files: files.map((f) => ({ path: f.path, size: f.size, sha256: f.sha256 ?? null })),
  }
  if (!ipc.isTauri()) {
    state.tasks = [...state.tasks, { ...demoTasks()[0], id: args.id ?? 'demo', state: 'running', received: 0, total: variant.total_size }]
    return null
  }
  const r = await snapshot.run('market_enqueue', () => ipc.marketEnqueue(args))
  if (r) {
    state.tasks = r
    state.orderError = '' // 下单成功清掉上一次的预检拒绝
  } else {
    // 磁盘预检拒绝等下单失败：就地可见（工单 36），不能只落日志页
    state.orderError = snapshot.error || 'enqueue failed'
  }
  return r
}

export async function pauseTask(id) {
  const r = await snapshot.run('market_pause', () => ipc.marketPause(id))
  if (r) state.tasks = r
}

export async function resumeTask(id) {
  const r = await snapshot.run('market_resume', () => ipc.marketResume(id))
  if (r) state.tasks = r
}

export async function cancelTask(id) {
  const r = await snapshot.run('market_cancel', () => ipc.marketCancel(id))
  if (r) {
    state.tasks = r
    return scanLocal()
  }
  return null
}

export async function scanLocal() {
  if (!ipc.isTauri()) {
    state.local = demo.local
    return
  }
  const r = await snapshot.run('local_scan', () => ipc.localScan(settingsRoot()))
  if (r) state.local = r
}

/** 实测：确认在视图层做（要弹「会停服务」），这里只发命令。行流进日志页。 */
export async function bench(modelPath) {
  if (state.benchBusy) return null
  state.benchBusy = modelPath
  try {
    return await snapshot.run('bench_run', () => ipc.benchRun(modelPath))
  } finally {
    state.benchBusy = ''
    if (ipc.isTauri()) return scanLocal()
    return null
  }
}

/** 一键启用：回填 --model / --mmproj 到表单并走 Apply（AppParameters 唯一真源）。
 *  返回 ApplyResult（含 written / needs_restart），失败返回 null 并置 applyError。 */
export async function enable(model) {
  // 基底用服务现状（快照值），而不是表单缓冲区——启用只负责换模型，
  // 不应该顺手把参数页里未应用的编辑一起写进服务。
  const values = { ...(snapshot.snapshot.snap?.values ?? {}), model: model.path }
  if (model.mmproj) values.mmproj = model.mmproj
  const r = await snapshot.run(
    'apply_changes',
    () => ipc.applyChanges(values, snapshot.snapshot.snap?.extras ?? []),
    (res) => {
      snapshot.setSnapshot(res.snapshot)
      snapshot.clearForm()
    },
  )
  if (r) {
    // 诊断模式：启用的关键结果落日志页，可回溯
    snapshot.pushLog(
      `[诊断] 启用 ${model.path} · written=${r.written} needs_restart=${r.needs_restart}`,
    )
  }
  // snapshot.error 是 errorLine() 出的展示串，直接用，绝不吞成兜底文案
  state.applyError = r ? '' : snapshot.error.value || 'apply failed'
  return r
}

/** 启用后立即重启服务，让新参数生效（行流进日志页）。 */
export async function restartNow() {
  snapshot.clearLog()
  const r = await snapshot.run('restart', () => ipc.restart(snapshot.values.value))
  return r
}

export function removeLocal(model, currentModel) {
  if (!ipc.isTauri()) {
    state.local = { ...state.local, models: state.local.models.filter((m) => m.path !== model.path) }
    return Promise.resolve()
  }
  return snapshot
    .run('local_delete', () => ipc.localDelete(model, currentModel ?? null))
    .then((r) => {
      if (r) state.tasks = r
      return scanLocal()
    })
}

/** 订阅两条事件流；返回 unlisten 数组（挂载时调用）。
 *  浏览器 demo 没有事件流（listen 会 reject），直接跳过——否则
 *  onMounted 里 subscribe 抛错，后面的 init() 永远跑不到，市场页空转。 */
export async function subscribe() {
  if (!ipc.isTauri()) return []
  const un = []
  un.push(await ipc.onMarketTasks((tasks) => {
    const before = JSON.stringify(state.tasks.map((t) => [t.id, t.state]))
    state.tasks = tasks
    const after = JSON.stringify(tasks.map((t) => [t.id, t.state]))
    if (before !== after) scanLocal()
  }))
  un.push(await ipc.onBenchLine((line) => snapshot.pushLog(line)))
  return un
}

/** 挂载时初始化：上次使用的源 + 任务列表 + 已下载区。 */
export async function init() {
  state.hub = snapshot.settings.value?.market_last_hub || 'ms'
  // 顺序执行：并发 run 会互相覆盖 busy 状态，也让错误归属变糊
  await loadList()
  await scanLocal()
  if (ipc.isTauri()) {
    const r = await snapshot.run('market_tasks', () => ipc.marketTasks())
    if (r) state.tasks = r
  } else {
    state.tasks = demoTasks()
  }
}

/** 完成的下载任务 → 已下载条目（路径含 repo 目录且档名一致），找不到给 null。
 *  分隔符归一：Rust 的 PathBuf 给反斜杠，demo 与拼接规则给正斜杠。 */
export function taskToLocal(task) {
  const seg = `/${task.repo}/`
  return (
    (state.local?.models ?? []).find(
      (m) => m.label === task.label && m.path.replaceAll('\\', '/').includes(seg),
    ) ?? null
  )
}

export const store = readonly(state)

/**
 * 市场页纯逻辑：格式化、匹配与展示映射。不碰 store、不发 IPC，
 * smoke 在 node 侧直接断言——视图层只负责把结果摆上屏。
 */

const UNITS = ['B', 'KB', 'MB', 'GB', 'TB']

/** 字节 → 「610MB / 26.0GB」；缺失给占位符。 */
export function fmtBytes(n) {
  if (n == null) return '—'
  let v = n
  let i = 0
  while (v >= 1024 && i < UNITS.length - 1) {
    v /= 1024
    i++
  }
  return `${v >= 100 || i === 0 ? v.toFixed(0) : v.toFixed(1)}${UNITS[i]}`
}

/** 下载量 → 「43.0w」；缺失给占位符。 */
export function fmtCount(n) {
  if (n == null) return '—'
  return n >= 10000 ? `${(n / 10000).toFixed(1)}w` : String(n)
}

/** 剩余秒数 → 「6分18秒」；算不出（无速度/已完成）给空串，不显示。 */
export function fmtEta(s) {
  if (!Number.isFinite(s) || s <= 0) return ''
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = Math.round(s % 60)
  if (h > 0) return `${h}小时${m}分`
  if (m > 0) return `${m}分${sec}秒`
  return `${sec}秒`
}

/** 进度百分比，封顶 100；总量未知给 0。 */
export function pct(t) {
  return t.total > 0 ? Math.min(100, Math.round((t.received * 100) / t.total)) : 0
}

const LIVE_STATES = ['queued', 'running', 'paused']

/** 某仓库某档当前是否已有活跃任务；有则返回任务（下载钮转「排队中」并禁用）。 */
export function taskFor(tasks, repo, label) {
  return tasks.find((t) => t.repo === repo && t.label === label && LIVE_STATES.includes(t.state)) || null
}

/** 完成的下载任务 → 已下载条目（路径含 repo 目录且档名一致），找不到给 null。
 *  分隔符归一：Rust 的 PathBuf 给反斜杠，demo 与拼接规则给正斜杠。 */
export function matchTaskToLocal(models, task) {
  const seg = `/${task.repo}/`
  return (
    (models ?? []).find(
      (m) => m.label === task.label && m.path.replaceAll('\\', '/').includes(seg),
    ) ?? null
  )
}

/** 任务状态 → 文案键（copy.js）。 */
export const STATE_TEXT = {
  queued: 'dlQueued',
  running: 'dlRunning',
  paused: 'dlPaused',
  done: 'dlFin',
  failed: 'dlFail',
}

/** 适配等级 → 文案键 / 状态色类。 */
export const TIER_TEXT = {
  full_gpu: 'fitFull',
  partial_gpu: 'fitPartial',
  cpu_only: 'fitCpu',
  not_recommended: 'fitNo',
}

export const TIER_CLASS = {
  full_gpu: 'fit-full',
  partial_gpu: 'fit-partial',
  cpu_only: 'fit-cpu',
  not_recommended: 'fit-no',
}

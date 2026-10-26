/**
 * 日志尾随的自适应轮询策略（纯函数，smoke 直接 node 断言）。
 *
 * 日志页长挂是常驻开销：每次 tick 都是一次 tail_log IPC + 文件尾读。
 * 服务安静时行不再增长，没必要保持 1.5s 的紧跟档——静默三拍后退到 3s、
 * 六拍后封顶 5s；任何新行（探活行、报错、重启流）立刻回到紧跟档，
 * 保证「日志在动」的观感不降级。
 */

/** 紧跟档：与旧行为一致，日志活跃时观感不变。 */
export const POLL_ACTIVE_MS = 1500

/** 静默上限：再安静也不慢于 5s（探活行 30s 一跳也能及时跟上）。 */
export const POLL_IDLE_MAX_MS = 5000

/**
 * 下一次轮询的间隔。
 *
 * @param {boolean} changed 本次轮询读到了新行（或文件被截断重写）
 * @param {number} idlePolls 连续无新行的轮询次数（changed 时会被归零）
 * @returns {number} setTimeout 的毫秒数
 */
export function nextPollMs(changed, idlePolls) {
  if (changed) return POLL_ACTIVE_MS
  const idle = Math.max(0, idlePolls)
  if (idle < 3) return POLL_ACTIVE_MS
  if (idle < 6) return 3000
  return POLL_IDLE_MAX_MS
}

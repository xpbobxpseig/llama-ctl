/**
 * 字体接口 · 运行时修改字体样式的唯一入口。
 *
 * 三个可调项（都落在 `<html>` 的自定义属性上，`.d5` 的字体族与 zoom 读它们）：
 *
 *   - **scale**  界面缩放：五档（0.85 / 0.925 / 1 / 1.1 / 1.2）。走 CSS `zoom`，
 *     布局随字一起缩，不会出现「字大了、行高夹住」的裁切。
 *   - **ui**     界面字体族：自定义族插到栈首，中文等未覆盖字形仍落回
 *     Segoe UI / Microsoft YaHei UI，不会出现豆腐块。设置页用下拉选。
 *   - **mono**   等宽字体族：同样插到栈首，数据 / 日志立即换脸。
 *
 * 使用方式：
 *   - 设置页「字体」区的控件走的就是这里；
 *   - 任意场合（DevTools 控制台、脚本）：
 *       window.llamaFont.setScale('large')
 *       window.llamaFont.setUIFamily('Maple Mono NF CN')
 *       window.llamaFont.setMonoFamily('Cascadia Code')
 *       window.llamaFont.reset()
 *
 * 偏好持久化在 localStorage（`llama-ctl.font`），与 Rust 的 settings.json
 * 无关——字体是呈现层偏好，不该让服务的配置文件跟着动。`main.js` 在挂载前
 * 调 `applySaved()`，首帧即生效。
 */

import { reactive } from 'vue'

const KEY = 'llama-ctl.font'

/** 缩放档位。factor 是乘在 zoom 上的系数；设置页的五档滑条就是这张表。 */
export const SCALE_STEPS = [
  { value: 'small', factor: 0.85 },
  { value: 'medium', factor: 0.925 },
  { value: 'normal', factor: 1 },
  { value: 'large', factor: 1.1 },
  { value: 'xlarge', factor: 1.2 },
]

/** 当前字体偏好（响应式，设置页直接绑定）。 */
export const state = reactive({ scale: 'normal', ui: '', mono: '' })

const factor = () => SCALE_STEPS.find((s) => s.value === state.scale)?.factor ?? 1

/** 字体名只留安全的字符：引号会被剥掉，长度封顶。 */
const safe = (name) => String(name ?? '').replace(/["'\\]/g, '').trim().slice(0, 64)

/** 自定义族永远只是「插到栈首」，中文字形交给后面的系统族兜底。 */
function uiStack(name) {
  return `"${name}", "Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI", "PingFang SC", system-ui, sans-serif`
}
function monoStack(name) {
  return `"${name}", llama-mono, "Cascadia Mono", "Cascadia Code", Consolas, "DejaVu Sans Mono", monospace`
}

function persist() {
  try {
    localStorage.setItem(KEY, JSON.stringify({ scale: state.scale, ui: state.ui, mono: state.mono }))
  } catch {
    // 隐私模式 / 存储被禁：本次会话内仍然生效，只是不记忆。
  }
}

/** 把当前状态写到 <html>。幂等；字体接口的全部副作用都在这里。 */
export function apply() {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.style.setProperty('--d5-zoom', String(factor()))
  if (state.ui) root.style.setProperty('--d5-ui-custom', uiStack(state.ui))
  else root.style.removeProperty('--d5-ui-custom')
  if (state.mono) root.style.setProperty('--d5-mono-custom', monoStack(state.mono))
  else root.style.removeProperty('--d5-mono-custom')
  persist()
}

/** 启动时读回上次的偏好并生效（main.js 在 createApp 之前调用）。 */
export function applySaved() {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw) {
      const saved = JSON.parse(raw)
      if (saved && SCALE_STEPS.some((s) => s.value === saved.scale)) state.scale = saved.scale
      state.ui = safe(saved?.ui)
      state.mono = safe(saved?.mono)
    }
  } catch {
    // 损坏的存储当作没有。
  }
  apply()
}

/**
 * 设缩放档位（SCALE_STEPS 里的 value）。
 * @param {string} value
 */
export function setScale(value) {
  if (!SCALE_STEPS.some((s) => s.value === value)) return
  state.scale = value
  apply()
}

/** 覆盖界面字体族；空串恢复默认。 */
export function setUIFamily(name) {
  state.ui = safe(name)
  apply()
}

/** 覆盖等宽字体族；空串恢复默认。 */
export function setMonoFamily(name) {
  state.mono = safe(name)
  apply()
}

/** 三项全部回到默认。 */
export function reset() {
  state.scale = 'normal'
  state.ui = ''
  state.mono = ''
  apply()
}

// 开发接口：控制台与自动化可以直接调。
if (typeof window !== 'undefined') {
  window.llamaFont = { state, SCALE_STEPS, setScale, setUIFamily, setMonoFamily, reset }
}

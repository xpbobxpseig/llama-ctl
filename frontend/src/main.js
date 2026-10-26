/**
 * Boot.
 *
 * The order here is the app's contract with the window:
 *   1. the global stylesheet lands before the first paint, so there is no flash
 *      of an unthemed frame;
 *   2. Vue mounts;
 *   3. `DesignApp.vue` fetches the Snapshot and applies the remembered geometry.
 *
 * ADR-0001: nothing is fetched. `global.css`, `design.css` and the subset fonts
 * under `src/assets/fonts` are bundled, and no module here opens a socket.
 */
import { createApp } from 'vue'
import DesignApp from './design/DesignApp.vue'
import * as font from './design/font.js'
import './styles/global.css'

// 字体偏好（缩放 / 字体族）在首帧之前生效，避免挂载后再跳一次字号。
font.applySaved()

const app = createApp(DesignApp)

// Outside the Tauri shell `window.__TAURI_INTERNALS__` is absent and every
// command would reject; the store swaps in the fixture instead, and the shell
// labels it as demo data on screen. Nothing else changes.
app.mount('#app')

// 开发专用的界面标注层：`?annotate=1` 时在真实界面上浮一层评审工具
// （点选元素写反馈、导出 Markdown）。生产壳不带 query 且非 DEV，分支
// 不可达；动态 import 让它永远不进主包。
if (import.meta.env.DEV && new URLSearchParams(location.search).has('annotate')) {
  import('./design/annotate.js')
    .then((m) => m.startAnnotate())
    .catch(() => {})
}

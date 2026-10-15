/**
 * Boot.
 *
 * The order here is the app's contract with the window:
 *   1. the global stylesheet and the theme's custom properties land before the
 *      first paint, so there is no flash of an unthemed frame;
 *   2. Vue mounts;
 *   3. `App.vue` fetches the Snapshot and applies the remembered geometry.
 *
 * ADR-0001: nothing is fetched. `global.css` is bundled, the fonts are the
 * system's own, and no module here opens a socket.
 */
import { createApp } from 'vue'
import App from './App.vue'
import './styles/global.css'

const app = createApp(App)

// Outside the Tauri shell `window.__TAURI_INTERNALS__` is absent and every
// command would reject; the store swaps in the fixture instead, and the shell
// labels it as demo data on screen. Nothing else changes.
app.mount('#app')

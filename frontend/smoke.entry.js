/**
 * Ticket 12 smoke entry — bundled and run inside jsdom by `smoke.mjs`.
 *
 * It mounts the real app the way `main.js` does and hangs the pieces the
 * assertions need off `window`. Everything the checks touch lives here so
 * `smoke.mjs` stays pure Node: no bundling in the assertion pass, and no
 * second build for the verifier to drift from.
 */
import { createApp } from 'vue'
import App from './src/App.vue'
import * as store from './src/stores/snapshot.js'
import * as theme from './src/stores/theme.js'
import { naiveOverrides, cssVars, TYPE, RADIUS, PALETTES } from './src/theme/index.js'
import { parseGeometry, formatGeometry } from './src/window/geometry.js'

const app = createApp(App)
app.mount('#app')

window.__SMOKE__ = { app, store, theme, naiveOverrides, cssVars, TYPE, RADIUS, PALETTES, parseGeometry, formatGeometry }

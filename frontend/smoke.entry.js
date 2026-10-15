/**
 * Smoke entry — bundled and run inside jsdom by `smoke.mjs`.
 *
 * It mounts the real app the way `main.js` does and hangs the pieces the
 * assertions need off `window`. Everything the checks touch lives here so
 * `smoke.mjs` stays pure Node: no bundling in the assertion pass, and no
 * second build for the verifier to drift from.
 *
 * Tickets 12/13/14 each added what they assert on; the object below is the
 * union, so one bundle serves every ticket's checks.
 */
import { createApp } from 'vue'
// `main.js` imports this before mounting; the smoke bundle must do the same, or
// it runs without the app's own stylesheet.
import './src/styles/global.css'
import App from './src/App.vue'
import * as store from './src/stores/snapshot.js'
import * as theme from './src/stores/theme.js'
import { naiveOverrides, cssVars, TYPE, RADIUS, PALETTES } from './src/theme/index.js'
import { parseGeometry, formatGeometry } from './src/window/geometry.js'
// Ticket 13.
import { FIELDS, GROUP_ORDER, OPTIONS, paramHelp, optionHelp } from './src/api/field-copy.js'
import ParamForm from './src/components/ParamForm.vue'
// Ticket 14: the control bar, the breathing dot and the log tail.
import ServiceControls from './src/components/ServiceControls.vue'
import StatusDot from './src/components/StatusDot.vue'
import LogTail from './src/components/LogTail.vue'
import ConfirmDialog from './src/components/ConfirmDialog.vue'
import { CONTROL_COPY, ct } from './src/components/control-copy.js'

const app = createApp(App)
app.mount('#app')

window.__SMOKE__ = {
  app,
  store,
  theme,
  naiveOverrides,
  cssVars,
  TYPE,
  RADIUS,
  PALETTES,
  parseGeometry,
  formatGeometry,
  // Ticket 13.
  FIELDS,
  GROUP_ORDER,
  OPTIONS,
  paramHelp,
  optionHelp,
  ParamForm,
  // Ticket 14.
  ServiceControls,
  StatusDot,
  LogTail,
  ConfirmDialog,
  CONTROL_COPY,
  ct,
}

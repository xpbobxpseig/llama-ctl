import * as motion from './src/motion/index.js'
/**
 * Smoke entry — bundled and run inside jsdom by `smoke.mjs`.
 *
 * It mounts the real app the way `main.js` does and hangs the pieces the
 * assertions need off `window`. Everything the checks touch lives here so
 * `smoke.mjs` stays pure Node: no bundling in the assertion pass, and no
 * second build for the verifier to drift from.
 *
 * Tickets 12/13/14/15 each added what they assert on; the object below is the
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
// Ticket 15: the update section, the release notes and the streamed progress.
import UpdateSection from './src/components/UpdateSection.vue'
import ReleaseNotes from './src/components/ReleaseNotes.vue'
import UpdateProgress from './src/components/UpdateProgress.vue'
import { UPDATE_COPY, ut } from './src/components/update-copy.js'
import * as update from './src/stores/update.js'
import { demoUpdateCheck } from './src/api/fixture.js'
import { EVENT_UPDATE } from './src/api/ipc.js'
// Ticket 17: presets, Apply / Revert and the switch guard.
import PresetBar from './src/components/PresetBar.vue'
import ParamDiff from './src/components/ParamDiff.vue'
import GuardDialog, { askGuard, closeGuard } from './src/components/GuardDialog.vue'
import { SUBMIT_COPY, pt, autoBackupName } from './src/components/submit-copy.js'

// ---- a recording IPC double ------------------------------------------------
/**
 * jsdom has no Rust behind it, so `invoke` would reject and every command the
 * update flow sends would fail. This double stands in for the shell.
 *
 * It is a **double**, not a reimplementation: it answers in the envelope's own
 * shape (`{ok, data}` / `{ok, error}`) and only for the commands a check needs.
 * Three things it deliberately does the way Rust does them:
 *
 *   - `save_settings` answers with a **fresh Snapshot**, so a preference is
 *     only "saved" once Rust has read it back — which is the whole point of the
 *     round trip the settings page makes;
 *   - `install_update` runs **slowly** and emits one line per step on the real
 *     `EVENT_UPDATE` name, through the real `listen` path, so the streaming
 *     render is what is being tested and not a shortcut;
 *   - every call is recorded, which is what "persists through save_settings"
 *     and "asks before doing anything" are asserted against.
 *
 * It is installed *after* the store module has been evaluated, so `isTauri()`
 * has already settled on demo mode and the shell keeps saying so on screen.
 */
const ipc = {
  /** @type {{cmd:string,args:object}[]} every command, in order. */
  calls: [],
  /** event name → [{ id, cb }] */
  listeners: new Map(),
  /** callback id → callback (`transformCallback` in the real API). */
  cbs: new Map(),
  nextId: 1,
}

/** Call every listener of `event`, the way the shell emits a payload. */
function emit(event, payload) {
  for (const l of ipc.listeners.get(event) ?? []) l.cb({ payload })
}

/** The lines one install streams, in order — the real step sequence. */
const INSTALL_LINES = [
  '正在更新 llama.cpp…',
  '停止服务 QwenLLM…',
  '服务已停止。',
  '下载 llama-b10819-bin-win-cuda-13.4-x64.zip（42%）',
  '下载 llama-b10819-bin-win-cuda-13.4-x64.zip（100%）',
  '备份旧文件到 F:\\llama_ctl\\backup\\b10819',
  '解压替换二进制…',
  '重启服务 QwenLLM…',
  '更新完成：QwenLLM 已重启，当前 b10819。',
]

function handle(cmd, args) {
  switch (cmd) {
    case 'plugin:event|listen': {
      const id = args.handler
      const list = ipc.listeners.get(args.event) ?? []
      list.push({ id, cb: ipc.cbs.get(id) })
      ipc.listeners.set(args.event, list)
      return Promise.resolve(id)
    }
    case 'plugin:event|unlisten': {
      for (const [event, list] of ipc.listeners) {
        ipc.listeners.set(
          event,
          list.filter((l) => l.id !== args.eventId),
        )
      }
      return Promise.resolve(null)
    }
    case 'save_settings': {
      // Rust re-reads and returns the whole Snapshot; a language change comes
      // back with the new string table. The fixture carries one table, so only
      // `lang` moves — which is still what proves the answer was applied.
      const snap = store.snapshot.snap
      return Promise.resolve({
        ok: true,
        data: { ...snap, settings: args.settings, lang: args.settings.language },
      })
    }
    case 'check_update':
      return Promise.resolve({ ok: true, data: demoUpdateCheck() })
    case 'install_update':
      return new Promise((resolve) => {
        let i = 0
        const step = () => {
          if (i < INSTALL_LINES.length) {
            emit(EVENT_UPDATE, INSTALL_LINES[i])
            i += 1
            setTimeout(step, 0)
            return
          }
          resolve({
            ok: true,
            data: {
              replaced: ['llama-server.exe', 'llama-cli.exe'],
              added: ['cudart64_134.dll'],
              downloaded: 2,
              build: 10819,
              log: INSTALL_LINES.slice(),
            },
          })
        }
        step()
      })
    default:
      return Promise.resolve({
        ok: false,
        error: { kind: 'Unknown', message: `no fake for ${cmd}` },
      })
  }
}

window.__TAURI_INTERNALS__ = {
  transformCallback(cb) {
    const id = ipc.nextId++
    ipc.cbs.set(id, cb)
    return id
  },
  unregisterCallback(id) {
    ipc.cbs.delete(id)
  },
  invoke(cmd, args) {
    ipc.calls.push({ cmd, args })
    return handle(cmd, args)
  },
}

// `_unlisten` reaches into this before invoking `plugin:event|unlisten`.
window.__TAURI_EVENT_PLUGIN_INTERNALS__ = { unregisterListener() {} }



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
  // Ticket 15.
  UpdateSection,
  ReleaseNotes,
  UpdateProgress,
  UPDATE_COPY,
  ut,
  update,
  demoUpdateCheck,
  EVENT_UPDATE,
  INSTALL_LINES,
  // Ticket 17.
  PresetBar,
  ParamDiff,
  GuardDialog,
  askGuard,
  closeGuard,
  SUBMIT_COPY,
  pt,
  autoBackupName,
  ipc,
  ipc,
  motion,
}

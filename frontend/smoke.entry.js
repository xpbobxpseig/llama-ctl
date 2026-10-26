/**
 * Smoke entry — bundled and run inside jsdom by `smoke.mjs`.
 *
 * It mounts the real app the way `main.js` does — `createApp(DesignApp)` plus
 * the global stylesheet, no query switch — and hangs every piece the
 * assertions need off `window`. Everything the checks touch lives here, so
 * `smoke.mjs` stays pure Node: no bundling in the assertion pass, and no
 * second build for the verifier to drift from.
 */
import { createApp } from 'vue'
// `main.js` imports this before mounting; the smoke bundle must do the same,
// or it runs without the app's own stylesheet.
import './src/styles/global.css'
import DesignApp from './src/design/DesignApp.vue'
import ParamsView from './src/design/ParamsView.vue'
import LogsView from './src/design/LogsView.vue'
import PresetsView from './src/design/PresetsView.vue'
import SettingsView from './src/design/SettingsView.vue'
import AboutView from './src/design/AboutView.vue'
import MarketView from './src/design/MarketView.vue'
import * as market from './src/stores/market.js'
import { C as COPY, t, autoBackupName } from './src/design/copy.js'
import * as font from './src/design/font.js'
import * as store from './src/stores/snapshot.js'
import * as theme from './src/stores/theme.js'
import * as update from './src/stores/update.js'
import * as ipc from './src/api/ipc.js'
import { demoSnapshot, demoUpdateCheck, emptySnapshot, demoMarket } from './src/api/fixture.js'
import {
  FIELDS,
  GROUP_ORDER,
  GROUP_LABEL,
  OPTIONS,
  PATH_FIELDS,
  NO_HELP,
  paramHelp,
  optionHelp,
} from './src/api/field-copy.js'
import { TYPE, RADIUS, SPACE, PALETTES, cssVars, resolveMode } from './src/theme/index.js'
import { parseGeometry, formatGeometry } from './src/window/geometry.js'
import * as motion from './src/motion/index.js'

// ---- a recording IPC double ------------------------------------------------
/**
 * jsdom has no Rust behind it, so `invoke` would reject and every command the
 * shell sends would fail. This double stands in for it.
 *
 * It is a **double**, not a reimplementation: it answers in the envelope's own
 * shape (`{ok, data}` / `{ok, error}`), records every call (that is what the
 * IPC-shape assertions read), and only knows the commands a check needs. Four
 * things it deliberately does the way Rust does them:
 *
 *   - `save_settings` answers with a **fresh Snapshot**, so a preference is
 *     only "saved" once Rust has read it back;
 *   - `apply_changes` answers with `{ snapshot }` — the value the shell folds
 *     in and clears its form against;
 *   - `install_update` runs **slowly** and emits one line per step on the real
 *     `EVENT_UPDATE` name, through the real `listen` path, so the streaming
 *     render is what is being tested and not a shortcut;
 *   - an unknown command fails loudly instead of pretending to succeed.
 *
 * It is installed *after* the store module has been evaluated, so `isTauri()`
 * has already settled on demo mode and the fixture is what boots; from that
 * point on `isTauri()` is true, which is what lets the startup auto-check and
 * the progress listeners take their real paths.
 */
const ipcDouble = {
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
  for (const l of ipcDouble.listeners.get(event) ?? []) l.cb({ payload })
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

const ok = (data) => Promise.resolve({ ok: true, data })

/** The Snapshot Rust would be holding right now. */
const snap = () => store.snapshot.snap ?? demoSnapshot()

function handle(cmd, args) {
  switch (cmd) {
    case 'plugin:event|listen': {
      const id = args.handler
      const list = ipcDouble.listeners.get(args.event) ?? []
      list.push({ id, cb: ipcDouble.cbs.get(id) })
      ipcDouble.listeners.set(args.event, list)
      return Promise.resolve(id)
    }
    case 'plugin:event|unlisten': {
      for (const [event, list] of ipcDouble.listeners) {
        ipcDouble.listeners.set(
          event,
          list.filter((l) => l.id !== args.eventId),
        )
      }
      return Promise.resolve(null)
    }
    // 窗口材质对齐（DesignApp 的 watcher）：真机走窗口 API，替身只记录。
    case 'plugin:window|set_theme':
    case 'plugin:window|set_effects':
      return Promise.resolve(null)
    // ---- market（模型市场）----
    case 'market_search':
    case 'market_hot':
      return ok(demoMarket.list)
    case 'market_repo':
      return ok(demoMarket.detail)
    case 'market_tasks':
      return ok(demoMarket.tasks)
    case 'market_enqueue':
      return ok(demoMarket.tasks.map((t) => ({ ...t, state: 'running' })))
    case 'market_resume':
      return ok(demoMarket.tasks)
    case 'market_pause':
      return ok(demoMarket.tasks.map((t) => ({ ...t, state: 'paused' })))
    case 'market_cancel':
    case 'local_delete':
      return ok([])
    case 'bench_run':
      return ok({ pp_tps: 2234.87, tg_tps: 43.53, ngl: 99 })
    case 'local_scan':
      return ok(demoMarket.local)
    case 'save_settings':
      // Rust re-reads and returns the whole Snapshot; a language change comes
      // back with the new string table. The fixture carries one table, so only
      // `lang` moves — which is still what proves the answer was applied.
      return ok({
        ...snap(),
        settings: args.settings,
        lang: args.settings.language ?? snap().lang,
      })
    // The mutating commands all answer with a Snapshot, which is what makes
    // "the interface only ever shows what Rust read back" observable.
    case 'get_snapshot':
      return ok(snap())
    case 'service_action':
      return ok(snap())
    case 'revert':
      return ok(snap())
    case 'restart':
      return ok(snap())
    case 'switch_service':
      return ok({ ...snap(), selected: args.args.service })
    case 'load_preset': {
      // 真实语义：Snapshot.values = 预设值（editing=Some(preset)），
      // service_values 仍是服务的当前参数——差异对它算。
      // load_preset 的签名是扁平 name（Rust: name: String），别套 args。
      const base = snap()
      return ok({
        ...base,
        values: { ...base.values, port: '8081', ngl: '7' },
        service_values: { ...base.values },
        facts: { ...base.facts, dirty: true },
        preset_loaded: args.name,
      })
    }
    case 'save_preset':
      return ok({ saved: true, name: args.args.name })
    case 'set_start_mode':
      return ok({ ...snap(), facts: { ...snap().facts, start: args.mode } })
    case 'apply_changes': {
      // Rust rebuilds AppParameters from the submitted form and answers with
      // the Snapshot it re-read. The values below are the form's, so a check
      // can tell "the answer was folded in" from "the local buffer was kept".
      const now = snap()
      return ok({
        snapshot: {
          ...now,
          values: { ...now.values, ...args.args.values },
          service_values: { ...(now.service_values ?? now.values), ...args.args.values },
          facts: { ...now.facts, dirty: false },
        },
      })
    }
    case 'save_preset':
      return ok({ saved: true, name: args.name })
    case 'delete_preset':
      return ok({ deleted: true, name: args.name })
    case 'check_update':
      return ok(demoUpdateCheck())
    case 'install_update':
      return new Promise((resolve) => {
        let i = 0
        const step = () => {
          if (i < INSTALL_LINES.length) {
            emit(ipc.EVENT_UPDATE, INSTALL_LINES[i])
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
    const id = ipcDouble.nextId++
    ipcDouble.cbs.set(id, cb)
    return id
  },
  unregisterCallback(id) {
    ipcDouble.cbs.delete(id)
  },
  invoke(cmd, args) {
    ipcDouble.calls.push({ cmd, args })
    return handle(cmd, args)
  },
}

// `_unlisten` reaches into this before invoking `plugin:event|unlisten`.
window.__TAURI_EVENT_PLUGIN_INTERNALS__ = { unregisterListener() {} }

// `main.js` applies the saved font preferences before mounting; the smoke boot
// mirrors that order so the first frame is the one being asserted on.
font.applySaved()

const app = createApp(DesignApp)
app.mount('#app')

window.__SMOKE__ = {
  app,
  store,
  theme,
  update,
  ipc,
  ipcDouble,
  demoSnapshot,
  demoUpdateCheck,
  emptySnapshot,
  EVENT_UPDATE: ipc.EVENT_UPDATE,
  EVENT_RESTART: ipc.EVENT_RESTART,
  INSTALL_LINES,
  // The design layer, as mounted.
  DesignApp,
  ParamsView,
  market,
  LogsView,
  PresetsView,
  SettingsView,
  AboutView,
  MarketView,
  demoMarket,
  copy: { C: COPY, t, autoBackupName },
  font,
  // Field metadata the parameter form is built from.
  FIELDS,
  GROUP_ORDER,
  GROUP_LABEL,
  OPTIONS,
  PATH_FIELDS,
  NO_HELP,
  paramHelp,
  optionHelp,
  // Tokens and window geometry.
  TYPE,
  RADIUS,
  SPACE,
  PALETTES,
  cssVars,
  resolveMode,
  parseGeometry,
  formatGeometry,
  motion,
}

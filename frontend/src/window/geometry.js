/**
 * Window geometry, remembered across restarts.
 *
 * The Snapshot carries `settings.geometry` as `"WxH+X+Y"` — the same shape the
 * Python build wrote (`llama_ctl_gui.py` L2434: `self.settings["geometry"] =
 * self.geometry()`), so a window saved by the old build is restored by this
 * one. Rust owns the string; this module only parses, applies and re-reports
 * it through `save_settings`.
 *
 * Two rules keep it from fighting the user:
 *   1. restore happens once, before paint, and never again;
 *   2. the save is debounced — a drag emits a resize per frame, and writing a
 *      file per frame is how a settings file gets corrupted.
 *
 * Outside the Tauri shell there is no window to move, so every call is a
 * no-op that reports itself as such rather than pretending to succeed.
 *
 * **Capability caveat (ticket 12, needs a human):** persisting is fully wired
 * — it reads size / position / scale, which `core:window:default` already
 * allows. *Restoring* and the close-flush need three permissions that
 * `src-tauri/capabilities/default.json` does not grant yet:
 * `core:window:allow-set-size`, `core:window:allow-set-position`,
 * `core:window:allow-close-requested`. See the two functions below.
 */

import { getCurrentWindow, LogicalSize, LogicalPosition } from '@tauri-apps/api/window'
import * as ipc from '../api/ipc.js'
import * as store from '../stores/snapshot.js'

/** How long the window must hold still before a resize is persisted. */
const DEBOUNCE_MS = 400

/** The smallest window worth remembering — anything less is a fluke. */
const MIN_W = 400
const MIN_H = 320

let win = null
let timer = null
let unlisten = []
let restored = false

/** The window handle, or `null` outside the shell (and on any shell error). */
export function window_() {
  if (win !== null) return win
  if (!ipc.isTauri()) return null
  try {
    win = getCurrentWindow()
  } catch {
    win = null
  }
  return win
}

/**
 * Parse `"WxH+X+Y"` into numbers. `null` for anything that is not that shape,
 * including the `None` Rust sends when it has nothing remembered.
 *
 * @param {string|null|undefined} text
 * @returns {{w:number,h:number,x:number,y:number}|null}
 */
export function parseGeometry(text) {
  if (!text) return null
  const m = /^(\d+)x(\d+)(?:\+(-?\d+))?(?:\+(-?\d+))?$/.exec(String(text).trim())
  if (!m) return null
  const w = Number(m[1])
  const h = Number(m[2])
  if (w < MIN_W || h < MIN_H) return null
  return {
    w,
    h,
    x: m[3] === undefined ? null : Number(m[3]),
    y: m[4] === undefined ? null : Number(m[4]),
  }
}

/** Format the current window as `"WxH+X+Y"`. */
export function formatGeometry({ w, h, x, y }) {
  const pos = x === null || y === null ? '' : `+${Math.round(x)}+${Math.round(y)}`
  return `${Math.round(w)}x${Math.round(h)}${pos}`
}

/**
 * Restore the remembered geometry, once.
 *
 * Runs before the first paint so there is no visible jump: the window is
 * created at the config's 1080x820 and would otherwise flash that size before
 * being moved. A geometry whose monitor is gone is skipped silently — a window
 * restored off-screen is worse than one the OS places itself.
 *
 * **Needs two capability permissions the shell does not grant yet.** Reading
 * the window back is covered by `core:window:default` (`allow-scale-factor`,
 * `allow-inner-size`, `allow-outer-position`), so persisting geometry works as
 * written; applying it calls `setSize` / `setPosition`, which need
 * `core:window:allow-set-size` and `core:window:allow-set-position` added to
 * `src-tauri/capabilities/default.json`. Until they are, the IPC is refused,
 * this returns false, and the window opens at the config's size — degraded, not
 * broken. Ticket 12 left that file alone: the Rust side is settled.
 */
export async function restoreGeometry() {
  if (restored) return false
  restored = true

  const w = window_()
  const geo = parseGeometry(store.settings.value?.geometry)
  if (!w || !geo) return false

  try {
    await w.setSize(new LogicalSize(geo.w, geo.h))
    if (geo.x !== null && geo.y !== null) {
      await w.setPosition(new LogicalPosition(geo.x, geo.y))
    }
    return true
  } catch {
    // A failed restore is not worth an error state: the window is already on
    // screen at its default size, which is a perfectly good place to be.
    return false
  }
}

/**
 * Persist the current geometry through `save_settings`.
 *
 * Debounced: a drag fires a resize every frame, and one IPC per frame is both
 * wasteful and a race with the other settings writes.
 */
export function saveGeometry() {
  if (timer !== null) clearTimeout(timer)
  timer = setTimeout(flushGeometry, DEBOUNCE_MS)
}

/** Write the current geometry now. Returns `false` when nothing could be written. */
export async function flushGeometry() {
  if (timer !== null) {
    clearTimeout(timer)
    timer = null
  }
  const w = window_()
  const settings = store.settings.value
  if (!w || !settings) return false

  try {
    const factor = await w.scaleFactor()
    const size = await w.innerSize()
    const pos = await w.outerPosition()
    const next = formatGeometry({
      w: size.width / factor,
      h: size.height / factor,
      x: pos.x / factor,
      y: pos.y / factor,
    })
    // Nothing moved: skip the round trip, including its snapshot refresh.
    if (next === settings.geometry) return true
    const snap = await store.run('save_settings', () =>
      ipc.saveSettings({ ...settings, geometry: next }),
    )
    return snap !== null
  } catch {
    return false
  }
}

/**
 * Follow resize and move, and flush on close.
 *
 * `onCloseRequested` is the last chance to write: after it, the window and the
 * app are gone. The listener is unsubscribed as part of this module's
 * teardown, which the app calls when it unmounts.
 *
 * Like {@link restoreGeometry}, `onCloseRequested` needs a permission the
 * current capability set does not grant (`core:window:allow-close-requested`).
 * A refusal is caught and reported, so the shell keeps running without the
 * shutdown flush rather than failing to boot.
 */
export async function watchGeometry() {
  const w = window_()
  if (!w) return false
  try {
    unlisten = [
      await w.onResized(() => saveGeometry()),
      await w.onMoved(() => saveGeometry()),
      await w.onCloseRequested(() => {
        // Fire-and-forget on purpose: the close must not wait on IPC, and a
        // geometry we failed to remember is not worth blocking the exit for.
        flushGeometry()
      }),
    ]
    return true
  } catch {
    return false
  }
}

/** Stop following the window and drop the handle. */
export function stopGeometry() {
  unlisten.forEach((fn) => {
    try {
      fn()
    } catch {
      /* a listener already gone is not an error */
    }
  })
  unlisten = []
  win = null
}

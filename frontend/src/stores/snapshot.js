/**
 * The Snapshot store.
 *
 * **Rust holds the truth.** This module is a cache of the last Snapshot and
 * nothing more: it is refilled by a fetch, never edited to reflect what the
 * user is looking at, and never treated as a second source. The one exception
 * the contract allows is `form` — the edits the user is making right now,
 * which live here until the next Apply and nowhere else (CONTEXT.md: "前端不
 * 持有权威状态，只在编辑期暂存表单值").
 *
 * ADR-0005: `strings` comes from Rust too. `t()` looks a key up in the
 * snapshot's own table and falls back to the key, so a gap is visible instead
 * of blank — the frontend never ships a translation of its own.
 */

import { reactive, readonly, computed } from 'vue'
import * as ipc from '../api/ipc.js'
import { demoSnapshot } from '../api/fixture.js'
import { SHELL_COPY } from '../api/shell-copy.js'

/** Boot state: nothing fetched, no error, nothing selected. */
const state = reactive({
  /** @type {'loading'|'ready'|'error'} */
  phase: 'loading',
  /** @type {object|null} the last Snapshot Rust sent. */
  snap: null,
  /** @type {string} the rendered failure line, when `phase === 'error'`. */
  error: '',
  /** @type {boolean} true outside the Tauri shell — everything below is demo. */
  demo: !ipc.isTauri(),
  /**
   * The form the user is editing. `null` means "show what the service holds";
   * a non-null object is an edit in progress. This is the only piece of state
   * the frontend owns.
   */
  form: null,
  /** @type {string} the command currently running, for busy states. */
  busy: '',
  /** @type {string[]} progress lines from the last long operation. */
  log: [],
})

// ---- string table ----------------------------------------------------------

/**
 * Translate `key`, filling `{name}` placeholders.
 *
 * A missing key renders as the key: a gap you can see beats a blank label.
 */
export function t(key, fields) {
  // Rust's table first, then the shell's own keys. A missing key renders as
  // the key: a gap you can see beats a blank label.
  const raw = state.snap?.strings?.[key] ?? SHELL_COPY[key]?.[lang.value] ?? key
  if (!fields) return raw
  return raw.replace(/\{(\w+)\}/g, (whole, name) =>
    name in fields ? String(fields[name]) : whole,
  )
}

// ---- derived ---------------------------------------------------------------

/** The service the form is showing, `""` when none is known. */
export const selected = computed(() => state.snap?.selected ?? '')

/** Every known NSSM service; empty until the first fetch lands. */
export const services = computed(() => state.snap?.services ?? [])

/** `true` when the form differs semantically from the service. */
export const dirty = computed(() => state.snap?.facts?.dirty ?? false)

/** The `sc query` state plus the health verdict. */
export const status = computed(
  () =>
    state.snap?.status ?? {
      state: 'UNKNOWN',
      ok: false,
      detail: '',
    },
)

/** `"zh"` / `"en"`, straight from Rust so the app never guesses. */
export const lang = computed(() => state.snap?.lang ?? 'zh')

/** Preferences as Rust last persisted them. */
export const settings = computed(() => state.snap?.settings ?? null)

/** The values on screen: the edit in progress, else what the service holds. */
export const values = computed(() => state.form ?? state.snap?.values ?? {})

/** The `sc query` state plus the health verdict. */
/** Progress lines from the last restart / install, newest last. */

/** `true` while a command is in flight — every control derives its disabled state from this. */
export const busy = computed(() => state.busy !== '')

/** Which command is running, `""` when idle. */
export const busyName = computed(() => state.busy)

/** The phase every view switches on: `loading` / `ready` / `error`. */
export const phase = computed(() => state.phase)

/** The rendered failure line. */
export const error = computed(() => state.error)

/** `true` when running outside the shell (demo data on screen). */
export const isDemo = computed(() => state.demo)

/** `true` once a Snapshot has arrived. */
export const ready = computed(() => state.phase === 'ready' && state.snap !== null)

// ---- mutations -------------------------------------------------------------

/**
 * Replace the cached Snapshot. Only a fetch does this — a view never writes
 * what it merely displayed.
 */
export function setSnapshot(snap) {
  state.snap = snap
  state.phase = 'ready'
  state.error = ''
}

/** Put the shell into its error phase with a readable line. */
export function setError(err) {
  state.error = ipc.errorLine(err)
  state.phase = 'error'
}

/** Append one progress line (restart / install stream these). */
export function pushLog(line) {
  state.log.push(line)
  if (state.log.length > 500) state.log.shift()
}

/** Clear the transcript. */
export function clearLog() {
  state.log = []
}

/**
 * Edit one field. This is the frontend's entire write surface: it changes what
 * is on screen and nothing else. Apply is what tells Rust about it.
 */
export function editField(key, value) {
  state.form = { ...values.value, [key]: String(value) }
}

/** Replace the whole edit buffer (a preset load, a service switch). */
export function setForm(next) {
  state.form = next
}

/** Throw the edits away and show the service's values again. */
export function clearForm() {
  state.form = null
}

/**
 * Run one command and fold its result into the store.
 *
 * Every mutating command returns a fresh Snapshot, so "did it work" is always
 * answered by what Rust read afterwards — the store never infers it. Errors
 * are caught here rather than at the call site so a failed command cannot
 * leave a stale snapshot on screen with a stale busy flag.
 *
 * @template T
 * @param {string} name shown in the busy state
 * @param {() => Promise<T>} run
 * @param {(data: T) => void} [apply] fold the result in; default: it was a Snapshot
 * @returns {Promise<T|null>} null on failure
 */
export async function run(name, task, apply) {
  state.busy = name
  try {
    const data = await task()
    if (apply) apply(data)
    else if (data && typeof data === 'object' && 'strings' in data) setSnapshot(data)
    return data
  } catch (err) {
    // A failed command keeps the last good snapshot on screen and surfaces the
    // line — a white window or a silently reverted form would be worse.
    setError(err)
    return null
  } finally {
    state.busy = ''
  }
}

/**
 * Fetch the Snapshot. `values` is the form being edited, so the "unapplied
 * changes" flag and the health-probe target reflect what is on screen.
 */
export async function refresh() {
  if (state.demo) {
    setSnapshot(demoSnapshot())
    return null
  }
  return run('get_snapshot', () => ipc.getSnapshot(state.form))
}

/** Load the fixture so the shell can be inspected outside the Tauri window. */
export function loadDemo() {
  state.demo = true
  setSnapshot(demoSnapshot())
}

/** The store, exposed read-only: views read it, only the actions above write it. */
export const snapshot = readonly(state)

/** Reset everything — for tests and for the "reload" affordance. */
export function reset() {
  state.phase = 'loading'
  state.snap = null
  state.error = ''
  state.form = null
  state.busy = ''
  state.log = []
}

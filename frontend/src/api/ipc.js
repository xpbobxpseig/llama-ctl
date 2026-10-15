/**
 * The whole IPC surface (ticket 11's contract, consumed here).
 *
 * Every command answers with the same envelope, so there is exactly one place
 * in the app that has to know how a failure looks:
 *
 *   { "ok": true,  "data":  { ... } }
 *   { "ok": false, "error": { "kind": "NoSuchService", "message": "..." } }
 *
 * `kind` is `AppErrorKind`'s PascalCase variant name and is branchable;
 * `message` is already translated by Rust and rendered verbatim — the
 * frontend never owns a translation of its own (ADR-0005).
 *
 * ADR-0001: nothing here reaches the network. `invoke` is the Tauri IPC
 * channel; the only other traffic is window geometry, which also goes
 * through Tauri's own commands.
 */

import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'

/** The two progress streams `restart` and `install_update` emit on. */
export const EVENT_RESTART = 'llama-ctl://restart-progress'
export const EVENT_UPDATE = 'llama-ctl://update-progress'

/** An error that came back over the wire, with its branchable `kind`. */
export class CommandError extends Error {
  constructor(kind, message) {
    super(message)
    this.name = 'CommandError'
    this.kind = kind
  }
}

/**
 * Call one command and unwrap the envelope.
 *
 * A rejection carries the whole `ErrorPayload`, so `!reply.ok` is the only
 * failure test the app ever needs.
 */
export async function call(name, args) {
  try {
    const reply = await invoke(name, args ?? {})
    if (reply && reply.ok === true) return reply.data
    throw new CommandError(reply?.error?.kind ?? 'Unknown', reply?.error?.message ?? name)
  } catch (err) {
    // `invoke` rejects with the `ErrorPayload` object for a command that
    // returned `Err`; anything else (a missing command, a dead shell) has to
    // reach the UI as a readable line rather than a blank window, so it is
    // normalised to the same shape.
    if (err instanceof CommandError) throw err
    if (err && typeof err === 'object' && err.ok === false) {
      throw new CommandError(err.error?.kind ?? 'Unknown', err.error?.message ?? name)
    }
    throw new CommandError('Unknown', err?.message ?? String(err))
  }
}

/** Errors worth translating into a UI hint rather than a bare message. */
export function errorLine(err) {
  if (err instanceof CommandError) return `${err.kind}: ${err.message}`
  return String(err?.message ?? err)
}

// ---- the 16 commands -------------------------------------------------------

/** The whole-state Snapshot. One fetch, everything one screen needs. */
export const getSnapshot = (values = null) => call('get_snapshot', { values })

/**
 * The tail of the selected service's `server.err`.
 * Returns `{ lines, path }`; `lines` is empty when the file is missing, which
 * is not an error — the log region is decoration.
 */
export const tailLog = () => call('tail_log')

/** Re-enumerate the NSSM services (one powershell call, ~0.6 s). */
export const refreshServices = () => call('refresh_services')

/**
 * Switch the form to another service.
 * @param {string} service
 * @param {Record<string,string>|null} values the form being abandoned
 * @param {boolean} backup store it as a timestamped preset first
 */
export const switchService = (service, values = null, backup = false) =>
  call('switch_service', { service, values, backup })

/** Apply the form: rebuild `AppParameters` and write it back. */
export const applyChanges = (values, extras = []) => call('apply_changes', { values, extras })

/** Revert: discard the form and read the service again. Never writes. */
export const revert = () => call('revert')

/** `sc start` / `sc stop`. */
export const serviceAction = (action) => call('service_action', { action })

/** Set the boot start mode: `"auto"` / `"manual"` / `"disabled"`. */
export const setStartMode = (mode) => call('set_start_mode', { mode })

/** Restart, streaming one line per step on {@link EVENT_RESTART}. */
export const restart = (values = null) => call('restart', { values })

/** Load a preset into the form. Reads only. */
export const loadPreset = (name) => call('load_preset', { name })

/** Save the form as a preset. `false` when the name already exists. */
export const savePreset = (name, values) => call('save_preset', { name, values })

/** Delete a preset. `false` when there was nothing to delete. */
export const deletePreset = (name) => call('delete_preset', { name })

/** Persist preferences. A language change returns the new string table. */
export const saveSettings = (settings) => call('save_settings', { settings })

/** Check for a newer official build. Never installs (ADR-0001). */
export const checkUpdate = () => call('check_update')

/** Install the release the last check found, streaming on {@link EVENT_UPDATE}. */
export const installUpdate = () => call('install_update')

/** Startup cleanup of stale download / backup directories. */
export const pruneUpdateDirs = () => call('prune_update_dirs')

/** `true` when the form differs semantically from the service. */
export const isDirty = (values) => call('is_dirty', { values })

// ---- progress --------------------------------------------------------------

/**
 * Subscribe to a progress stream. Returns the unlisten function; callers
 * subscribe before starting the operation so no line is missed.
 *
 * @param {string} event one of {@link EVENT_RESTART} / {@link EVENT_UPDATE}
 * @param {(line: string) => void} onLine
 * @returns {Promise<() => void>}
 */
export function onProgress(event, onLine) {
  return listen(event, (e) => onLine(String(e.payload ?? '')))
}

// ---- environment -----------------------------------------------------------

/**
 * `true` when running inside the Tauri shell.
 *
 * Outside it (a plain browser, the component tests of tickets 13-17) there is
 * no `window.__TAURI_INTERNALS__`, and pretending otherwise would make every
 * screen show a spinner forever. Detection is by the injected API, not by a
 * user-agent guess.
 */
export function isTauri() {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
}

/**
 * The official-update half of the app (ticket 15).
 *
 * **Rust does the work; this module only holds what the user is looking at.**
 * It is not a second copy of the service's state — it is the update flow's own
 * transcript: the last check's answer, whether the changelog is on screen, and
 * the live install log. Nothing here is ever written back to a Snapshot.
 *
 * Three rules the ticket makes load-bearing:
 *
 * 1. **A startup check only prompts.** `check({ silent: true })` remembers the
 *    release and opens the notes; it never calls `install`. Only
 *    `beginInstall()` does, and only after the user has confirmed twice
 *    (changelog → backup confirmation). ADR-0001 / story 52.
 * 2. **The install is the release the last check found.** Rust refuses an
 *    install after the variant changed (`msg.channel.changed`), so changing the
 *    variant drops the release here too — the user can never install a build
 *    whose notes they have not read.
 * 3. **Progress is streamed, not polled.** `install_update` runs for minutes on
 *    a ~400 MB asset; it emits one line per step on `EVENT_UPDATE`, and those
 *    lines are appended as they arrive (`store.pushLog`). The renderer never
 *    waits on the download: the command is a promise, the lines are an event.
 *
 * `onProgress` is subscribed *before* the command is sent, so no line can be
 * missed; the whole install's log also comes back in the `InstallReport`, which
 * is what makes a re-render after the fact show the same transcript.
 */

import { computed, readonly, reactive, ref } from 'vue'
import * as ipc from '../api/ipc.js'
import * as store from './snapshot.js'

/** The update-view state. */
const state = reactive({
  /** @type {'idle'|'checking'|'installing'} which long operation is running. */
  phase: 'idle',
  /** @type {object|null} the `UpdateCheck` Rust returned: release/installed/up_to_date. */
  checked: null,
  /** @type {string} the variant the last check used, or '' for none. */
  checkedChannel: '',
  /** @type {string} the rendered failure line of the last check/install. */
  error: '',
  /** @type {object|null} what the last install did (`InstallReport`). */
  report: null,
  /** @type {boolean} true once a startup check has run this session. */
  autoChecked: false,
})

/** Whether the release-notes sheet is on screen. */
const showNotes = ref(false)

/**
 * Progress lines of the install in flight, newest last.
 *
 * The same lines go to `snapshot.log` (the shell's log region renders them);
 * this local copy is what the update card's own transcript renders, so a
 * restart's lines cannot be mixed into an install's.
 */
const lines = ref([])

/** `true` while a check or an install is in flight. */
export const busy = computed(() => state.phase !== 'idle')

/** The variant Rust last persisted, i.e. the one a check would use. */
export const channel = computed(() => store.settings.value?.upd_channel ?? '')

/** Whether the startup auto-check preference is on. */
export const autoOnStartup = computed(
  () => store.settings.value?.upd_check_on_startup ?? true,
)

/** The last `UpdateCheck` Rust returned, `null` before the first one. */
export const checked = computed(() => state.checked)

/** The installed build Rust read, `null` when unreadable. */
export const installed = computed(() =>
  state.checked ? state.checked.installed : null,
)

/** The release the last check found, `null` before the first one. */
export const release = computed(() => state.checked?.release ?? null)


/** `true` when Rust says the installed build already covers the release. */
export const upToDate = computed(() => state.checked?.up_to_date ?? false)

/** Append one progress line from the install stream (used by tests). */
export function pushProgress(line) {
  lines.value.push(line)
  if (lines.value.length > 500) lines.value.shift()
}

/** The transcript of the install in flight (or the last one). */
export const progress = readonly(lines)

/** The failure line, `''` when the last operation succeeded. */
export const error = computed(() => state.error)

/** What the last install did: replaced / added / downloaded / build. */
export const report = computed(() => state.report)


/** Whether the release-notes sheet is open. */
export const notesOpen = computed(() => showNotes.value)

/** `true` once the startup check has run, so it cannot run twice. */
export const autoChecked = computed(() => state.autoChecked)

/**
 * The build-variant options, from Rust's own `channels`.
 *
 * The Snapshot carries them, so the list on screen is whatever Rust offers —
 * never a second, hand-written list that can drift.
 */
export const channels = computed(() =>
  (store.snapshot.snap?.channels ?? []).map(([id, label]) => ({
    value: id,
    label,
  })),
)

/**
 * `unknown` / `known` / `none` — which of the status line's three cases is on
 * screen. The ticket's own requirement: 「未知」is the unreadable case, and it
 * must not read as a build number or as "not checked yet".
 */
export const statusKind = computed(() => {
  if (!state.checked) return 'none'
  return state.checked.installed === null || state.checked.installed === undefined
    ? 'unknown'
    : 'known'
})

/**
 * Accept an `UpdateCheck` exactly as `check_update` returns it.
 *
 * The production path is the command; this is the same object Rust would have
 * sent, so a test (and the smoke run) can put the section into its checked
 * state without a backend.
 */
export function setChecked(data) {
  state.checked = data ?? null
  state.checkedChannel = data ? channel.value : ''
}


/**
 * The status line under the section header.
 *
 * Four cases, and the difference between them is the point of the ticket:
 * "unknown" means *llama-server.exe could not be read*, which is not the same
 * as "not checked yet" and must not be shown as a build number.
 */
export const statusLine = computed(() => {
  if (state.checked) {
    const rel = state.checked.release
    const build = state.checked.installed
    const current =
      build === null || build === undefined
        ? store.t('upd.status.unknown')
        : store.t('upd.status.now', { b: `b${build}` })
    if (!rel) return current
    return `${current} · ${store.t('upd.check.done', { t: rel.tag })}`
  }
  return store.t('upd.status.none')
})

/** `true` when a release is known and an install could be started. */
export const canInstall = computed(() => release.value !== null && !busy.value)

/**
 * Where the old files will be backed up — computed here, ahead of the install,
 * so the confirmation can name it.
 * Rust derives the real directory (`<llama-root>/backup/<tag>/<YYYYmmdd_HHMMSS>`)
 * when it runs (`update_files::backup_dir`); the path below is the same shape,
 * and the confirmation's own copy says so, because the timestamp is Rust's
 * clock and not ours. This is a *preview*, and it is labelled as one.
 */
export const backupPreview = computed(() => {
  const rel = release.value
  if (!rel) return ''
  const root = backupRoot()
  return `${root}\\${rel.tag}`
})

/** The backup root: `LLAMA_CTL_BACKUP_DIR` else `F:\llama_ctl\backup`. */
function backupRoot() {
  // The Python build's own constants (llama_ctl_gui.py L62-65). `InstallEnv`
  // in Rust reads `LLAMA_CTL_LLAMA_DIR` only, so the backup root is not part
  // of the Snapshot — the shape is mirrored here for the confirmation's copy.
  return 'F:\\llama_ctl\\backup'
}

/** Reset everything — for tests. */
export function reset() {
  state.phase = 'idle'
  state.checked = null
  state.checkedChannel = ''
  state.error = ''
  state.report = null
  state.autoChecked = false
  showNotes.value = false
  lines.value = []
}

/**
 * Check for a newer official build. **Never installs.**
 *
 * @param {{ silent?: boolean }} [opts] `silent` = the startup check: a result
 *   that is already up to date is remembered and nothing is shown.
 * @returns {Promise<object|null>} the `UpdateCheck`, or null on failure
 */
export async function check(opts = {}) {
  if (state.phase !== 'idle') return null
  state.phase = 'checking'
  state.error = ''
  try {
    const data = await ipc.checkUpdate()
    state.checked = data
    state.checkedChannel = channel.value
    state.report = null
    // A stale "up to date" from the previous variant must not survive: the
    // release on screen is the one just checked, and only that one is
    // installable.
    const newer = data?.release && !data.up_to_date
    if (!opts.silent || newer) showNotes.value = Boolean(data?.release)
    return data
  } catch (err) {
    // A failed check drops the release: an install button pointing at a
    // release we could not confirm is worse than no button at all.
    state.checked = null
    state.checkedChannel = ''
    state.error = ipc.errorLine(err)
    return null
  } finally {
    state.phase = 'idle'
  }
}

/**
 * The startup auto-check: run once, only when the preference is on, and only
 * ever *prompt*. Nothing in this path can start a download.
 */
export async function autoCheck() {
  if (state.autoChecked || !autoOnStartup.value) return null
  state.autoChecked = true
  // Asked at call time, not at module load: `isTauri()` is a fact about the
  // environment, so a harness that stands a backend up after boot gets the
  // check while a plain browser does not put a failure line on a screen that
  // is already labelled as demo data.
  if (!ipc.isTauri()) return null
  return check({ silent: true })
}

/** Forget that the startup check has run — for tests. */
export function resetAutoCheck() {
  state.autoChecked = false
}

/**
 * Persist the build variant through `save_settings`.
 *
 * Rust answers with a fresh Snapshot, so the dropdown's position is what Rust
 * check: Rust refuses to install a release the user did not see the notes for.
 *
 * @param {string} next a channel id from Rust's own list
 * @returns {Promise<boolean>} false when the write failed
 */
export async function setChannel(next) {
  const settings = store.settings.value
  if (!settings) return false
  const snap = await store.run('save_settings', () =>
    ipc.saveSettings({ ...settings, upd_channel: next }),
  )
  if (snap === null) return false
  invalidateCheck()
  return true
}

/** Persist the "check on startup" preference the same way. */
export async function setAutoOnStartup(next) {
  const settings = store.settings.value
  if (!settings) return false
  const snap = await store.run('save_settings', () =>
    ipc.saveSettings({ ...settings, upd_check_on_startup: next }),
  )
  return snap !== null
}

/**
 * Forget the last check.
 *
 * Called after a variant change (the release on screen is for the old variant)
 * and used by tests. It is the only way `pending` is cleared apart from a new
 * check: an installable release must always be one the user was shown.
 */
export function invalidateCheck() {
  state.checked = null
  state.checkedChannel = ''
  state.report = null
  showNotes.value = false
}

/** Open / close the release-notes sheet. */
export function openNotes(next = true) {
  showNotes.value = next && release.value !== null
}

/**
 * Ask for the second confirmation: the backup directory.
 *
 * The changelog is the first; this is the one that names where the old files
 * go and what will be stopped. It is a separate question on purpose — Python
 * asked it (`upd.install.confirm`) and the ticket requires it.
 */
const confirm = ref(false)
export const confirmOpen = computed(() => confirm.value)

export function askInstall() {
  if (!canInstall.value) return
  confirm.value = true
}

export function cancelInstall() {
  confirm.value = false
}

/**
 * Run the install, streaming every progress line as it arrives.
 *
 * The listener is installed *before* the command is sent so no line is missed,
 * and the command's own promise is what ends the run — the transcript is
 * complete either way, because `InstallReport.log` carries the whole thing too.
 *
 * This is the only function in the app that starts a download, and it is
 * reachable only after `askInstall()`'s confirmation.
 */
export async function beginInstall() {
  if (!canInstall.value) return null
  confirm.value = false
  showNotes.value = false
  state.phase = 'installing'
  state.error = ''
  lines.value = []
  // One install's transcript at a time: mixing two runs' download/backup/
  // extract lines would read as a different, wrong sequence.
  store.clearLog()

  let unlisten = null
  try {
    unlisten = await ipc.onProgress(ipc.EVENT_UPDATE, (line) => {
      lines.value.push(line)
      store.pushLog(line)
    })
  } catch {
    // Outside the Tauri shell there is no event system; the install itself
    // will reject too, and the failure line is what the user sees.
    unlisten = null
  }

  try {
    const data = await store.run('install_update', () => ipc.installUpdate())
    if (data === null) {
      state.error = store.error.value
      return null
    }
    state.report = data
    // Rust's own transcript wins if any line arrived out of band.
    if (data.log?.length && data.log.length >= lines.value.length) {
      lines.value = data.log.slice()
    }
    return data
  } finally {
    if (unlisten) unlisten()
    state.phase = 'idle'
    // Files were replaced and the service restarted: the cached snapshot is
    // stale, so the installed build on screen is re-read from Rust.
    if (state.error === '') await store.refresh()
  }
}

/**
 * Appearance: `system` / `light` / `dark`, resolved to `light` / `dark`.
 *
 * The preference lives in Rust (`Settings.appearance`) and is persisted by the
 * `save_settings` command — the frontend keeps no shadow copy on disk. Until
 * the first Snapshot lands it falls back to the OS, which is the same default
 * Rust ships (`"system"`).
 *
 * `motion` rides along: ticket 16 owns the full motion system, but the master
 * switch is a preference and belongs with the rest of them.
 */

import { ref, computed, watch } from 'vue'
import { resolveMode } from '../theme/index.js'
import * as ipc from '../api/ipc.js'
import * as store from './snapshot.js'

/** `"system" | "light" | "dark"` — the preference, not the result. */
export const appearance = ref('system')

/** `true` when `prefers-color-scheme` says dark; kept live by the listener below. */
export const systemDark = ref(
  typeof window !== 'undefined' && window.matchMedia
    ? window.matchMedia('(prefers-color-scheme: dark)').matches
    : false,
)

/** The appearance actually in effect. */
export const mode = computed(() =>
  resolveMode(
    store.settings.value?.appearance ?? appearance.value,
    systemDark.value,
  ),
)

/** The master animation switch. `false` = every animation jumps to its end state. */
export const motion = computed(() => store.settings.value?.motion_enabled ?? true)

/** `true` when the user has asked for reduced motion, from either source. */
export const reducedMotion = computed(
  () =>
    !motion.value ||
    (typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true),
)

let started = false

/**
 * Start following the OS. Called once from `main.js`; idempotent, because a
 * second listener would only make the first one unreachable.
 */
export function startAppearance() {
  if (started || typeof window === 'undefined' || !window.matchMedia) return
  started = true
  const mq = window.matchMedia('(prefers-color-scheme: dark)')
  mq.addEventListener('change', (e) => {
    systemDark.value = e.matches
  })
}

/**
 * Persist the appearance through Rust.
 *
 * The command answers with a fresh Snapshot, which is what makes this
 * verifiable: the switch is not "done" until Rust has read it back. A language
 * change comes back with a new string table for the same reason.
 *
 * @param {'system'|'light'|'dark'} next
 * @returns {Promise<boolean>} false when the write failed
 */
export async function setAppearance(next) {
  const settings = store.settings.value
  if (!settings) return false
  appearance.value = next
  const snap = await store.run('save_settings', () =>
    ipc.saveSettings({ ...settings, appearance: next }),
  )
  return snap !== null
}

/** Persist the master motion switch the same way. */
export async function setMotion(next) {
  const settings = store.settings.value
  if (!settings) return false
  const snap = await store.run('save_settings', () =>
    ipc.saveSettings({ ...settings, motion_enabled: next }),
  )
  return snap !== null
}

/** Persist the language. Rust re-reads the string table and returns it. */
export async function setLanguage(next) {
  const settings = store.settings.value
  if (!settings) return false
  const snap = await store.run('save_settings', () =>
    ipc.saveSettings({ ...settings, language: next }),
  )
  return snap !== null
}

// Keep the local preference in step with what Rust last persisted, so an
// external edit (another window, a hand-edited settings.json) is not fought
// by a stale local value.
watch(
  () => store.settings.value?.appearance,
  (v) => {
    if (v) appearance.value = v
  },
  { immediate: true },
)

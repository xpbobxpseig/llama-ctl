/**
 * The motion system (ticket 16).
 *
 * One module owns every timing in the app, and one switch turns all of them
 * off at once. Components never implement their own on/off: they read the
 * `--m-*` custom properties (or call {@link useHelpTip}), and the switch
 * rewrites the properties on `<html>`.
 *
 * What the Python build did with `motion.py` — a 16 ms tick loop lerping hex
 * colours back into Tk widgets (326 lines) — is here a CSS transition. There
 * is no per-frame interpolation anywhere in this module; the only timers are
 * the one-shot ones below (the「?」delay), which are *thresholds*, not frames.
 *
 * The two rules that shape it:
 *
 *   - **The switch never disables anything.** Off means every animation takes
 *     no time, so a transition that ends in a different visual state still
 *     ends there. Nothing becomes unreachable, unreadable or invisible.
 *   - **Motion carries state, never decorates.** 100 ms in (an answer to the
 *     pointer), 800 ms of exponential-feeling decay back out.
 *
 * Where the numbers come from (`llama_ctl_gui.py`):
 *   L873-878  button hover: 100 ms ease-out in; α = exp(-t/τ), τ = 0.27 s out
 *   L521-524 「?」: 300 ms hover threshold, 200 ms fade in, 800 ms fade out
 *   L698-705 「?」fade-out accelerates with the pointer's distance, k ∈ [1, 2]
 *   L1558     the breathing dot: 1200 ms cycle, frozen after 30 s idle
 *   L516      the 300 ms threshold is anti-mistouch and is **not** governed by
 *             the motion switch — honoured here (see {@link THRESHOLD_VARS}).
 *
 * ADR-0001: no dependency, no remote asset, no font. Everything here is a
 * number and a CSS class.
 */

import { computed, ref, watch } from 'vue'
import { MOTION } from '../theme/index.js'
import { reducedMotion } from '../stores/theme.js'

// ---- tokens ----------------------------------------------------------------

/**
 * The class that zeroes every animation. It goes on `<html>`, not on a Vue
 * root: NaiveUI teleports popovers, select menus and dialogs to `<body>`, and
 * a class on an element inside `#app` would never reach them.
 */
export const OFF_CLASS = 'motion-off'

/**
 * "As good as zero". Not literally `0s`, so `transitionend` still fires and
 * Vue's `<Transition>` still completes its leave phase.
 */
export const INSTANT = '0.01ms'

/** The OS preference. Read, and kept live, by `stores/theme.js`. */
export const REDUCED_QUERY = '(prefers-reduced-motion: reduce)'

/**
 * Duration tokens the switch zeroes: CSS custom property → `MOTION` key.
 *
 * `src/theme/index.js` is where the values live; this map is what turns them
 * into custom properties, so a duration cannot exist in one place and not the
 * other.
 */
export const DURATION_VARS = {
  '--m-hover-in': 'HOVER_IN', // button reaches its highlight and holds
  '--m-hover-out': 'HOVER_OUT', // ...and decays back to rest
  '--m-enter': 'ENTER', // card / view entrance
  '--m-tip-in': 'TIP_IN', //「?」fade in
  '--m-tip-out': 'TIP_OUT', //「?」fade out
}

/**
 * Interaction thresholds. These are **not** animations — they decide *whether*
 * something happens — so the switch leaves them alone. Turning the 300 ms
 * hover threshold off would make the「?」fire on every pass across the form,
 * which is the opposite of what the switch promises (Python L516).
 */
export const THRESHOLD_VARS = {
  '--m-tip-delay': 'TIP_DELAY',
}

/** Easing tokens. Never zeroed: a curve with no duration draws nothing. */
export const EASE_VARS = {
  '--m-ease-out': 'EASE_OUT',
  '--m-ease-decay': 'EASE_DECAY',
}

/**
 * The same durations as bare milliseconds, for the JS side.
 *
 * Parsed out of `MOTION` rather than restated, so the「?」delay the timer uses
 * and the「?」delay in the stylesheet cannot drift apart.
 */
export const MS = Object.fromEntries(
  [...Object.values(DURATION_VARS), ...Object.values(THRESHOLD_VARS)].map((token) => [
    token,
    parseInt(MOTION[token], 10),
  ]),
)

/**
 * The「?」timings, in the one place they exist.
 *
 * `ParamHelp.vue` reads these; so does {@link useHelpTip}. Nothing else in the
 * app may spell 300, 200 or 800.
 */
export const HELP = {
  /** Hover before the tip appears, so a quick pass does not trigger it. */
  delay: MS.TIP_DELAY,
  /** Fade in, once it has decided to appear. */
  in: MS.TIP_IN,
  /** Exponential-feeling fade out after the pointer leaves. */
  out: MS.TIP_OUT,
}

// ---- the switch ------------------------------------------------------------

/**
 * The custom properties for one switch position.
 *
 * @param {boolean} enabled `false` zeroes every duration in
 *   {@link DURATION_VARS}; thresholds and easings are untouched.
 */
export function motionVars(enabled = true) {
  const out = {}
  for (const [cssVar, token] of Object.entries(DURATION_VARS)) {
    out[cssVar] = enabled ? MOTION[token] : INSTANT
  }
  for (const [cssVar, token] of Object.entries(THRESHOLD_VARS)) out[cssVar] = MOTION[token]
  for (const [cssVar, token] of Object.entries(EASE_VARS)) out[cssVar] = MOTION[token]
  return out
}

/**
 * Apply the switch.
 *
 * Two mechanisms, because they cover different things:
 *   - the `--m-*` properties are rewritten, so every rule that reads a token
 *     — including the ones in teleported popovers — answers in no time;
 *   - {@link OFF_CLASS} lands on `<html>`, and `styles/global.css` uses it to
 *     clamp `transition-duration` / `animation-duration` / both delays for
 *     anything that hardcodes a duration (NaiveUI's own 0.15 s popover
 *     transition and 0.3 s border fade, for instance).
 *
 * @param {boolean} enabled
 */
export function applyMotion(enabled = true) {
  const root = typeof document === 'undefined' ? null : document.documentElement
  if (!root) return
  for (const [name, value] of Object.entries(motionVars(enabled))) {
    root.style.setProperty(name, value)
  }
  root.classList.toggle(OFF_CLASS, !enabled)
}

/**
 * `true` when the switch is on *and* the OS has not asked for less motion.
 * The one answer every caller should use, so "is animation allowed" has a
 * single definition.
 */
export const motionEnabled = computed(() => !reducedMotion.value)

// ---- the「?」---------------------------------------------------------------

/**
 * Every tip controller currently open, by id. Python kept a single
 * `_HelpTip._active` and destroyed the previous one the moment a new「?」was
 * entered; this is that, as a set of one.
 */
const openTips = new Map()

/** How many tips are on screen. Always 0 or 1; exposed for the tests. */
export const helpOpenCount = ref(0)

/** The distance over which the fade-out reaches its full 2× acceleration. */
const ACCEL_PX = 400

let seq = 0

/**
 * The「?」behaviour: hover 300 ms, fade in 200 ms, fade out 800 ms faster the
 * further the pointer gets, restore at once if the pointer comes back during
 * the fade, and only ever one tip on screen.
 *
 * Keyboard reaches it too — `focus` opens immediately, without the 300 ms
 * threshold, because a deliberate Tab is not a pass-over.
 */
export function useHelpTip() {
  const id = ++seq
  /** The popover's `show` — driven from here, so hover and click agree. */
  const shown = ref(false)
  /**
   * `true` while a tip is being restored mid-fade: the fade-in is then
   * instantaneous (Python restored α = 1 at once rather than re-fading from
   * transparent).
   */
  const restoring = ref(false)
  /** The distance-scaled fade-out duration, as an inline custom property. */
  const fade = ref({})

  let showTimer = 0
  let fadingTimer = 0
  let restoreTimer = 0
  /** `true` from the moment the pointer leaves until the fade is over. */
  let fading = false

  watch(shown, (value) => {
    if (value) openTips.set(id, close)
    else openTips.delete(id)
    helpOpenCount.value = openTips.size
  })

  /** Close every *other* tip. Python: "后悬停者优先". */
  function closeOthers() {
    for (const [other, closeOther] of [...openTips]) {
      if (other !== id) closeOther()
    }
  }

  function close() {
    clearTimeout(showTimer)
    shown.value = false
  }

  /**
   * Python's `k = 1 + min(max(|dx|, |dy|) / 400, 1)`: the further the pointer
   * is from the「?」, the shorter the fade (α = exp(-t·k/τ) reaches any given
   * value in τ/k of the time). One read at the moment the pointer leaves —
   * not a per-frame loop.
   *
   * @param {{ currentTarget?: Element, clientX?: number, clientY?: number }} ev
   */
  function fadeFor(ev) {
    const el = ev?.currentTarget
    if (!el || typeof el.getBoundingClientRect !== 'function') return {}
    const r = el.getBoundingClientRect()
    const dx = Math.abs((ev.clientX ?? 0) - (r.left + r.width / 2))
    const dy = Math.abs((ev.clientY ?? 0) - (r.top + r.height / 2))
    const k = 1 + Math.min(Math.max(dx, dy) / ACCEL_PX, 1)
    return { '--tip-fade': `${Math.round(HELP.out / k)}ms` }
  }

  function enter() {
    clearTimeout(showTimer)
    closeOthers()
    if (shown.value) return
    if (fading) {
      // Back during the fade: restore at once, do not fade in again from
      // transparent (Python L578-587 set α = 1 directly).
      restoring.value = true
      clearTimeout(restoreTimer)
      restoreTimer = setTimeout(() => {
        restoring.value = false
      }, HELP.in + 40)
      shown.value = true
      return
    }
    showTimer = setTimeout(() => {
      shown.value = true
    }, HELP.delay)
  }

  function leave(ev) {
    clearTimeout(showTimer)
    if (!shown.value) return
    fading = true
    clearTimeout(fadingTimer)
    fadingTimer = setTimeout(() => {
      fading = false
      fade.value = {}
    }, HELP.out + 80)
    // With motion off the popover is gone the same frame, so a scaled duration
    // would never be read anyway.
    fade.value = reducedMotion.value ? {} : fadeFor(ev)
    restoring.value = false
    shown.value = false
  }

  /** Tab-in: deliberate, so no threshold. */
  function focus() {
    clearTimeout(showTimer)
    closeOthers()
    shown.value = true
  }

  function blur() {
    leave(null)
  }

  return { shown, restoring, fade, enter, leave, focus, blur, close }
}

<script setup>
/**
 * Status dot — a **vector** asset, not a font glyph.
 *
 * Python drew this with `text="\u25CF"` (`llama_ctl_gui.py` L1071-1077). The
 * ink measured 13x23px at a 13px font size: the shape came from Microsoft YaHei
 * UI's own metrics, so it drifted whenever a nearby label's size did, and it
 * could not be tinted per theme. Here the shape is two SVG circles on a fixed
 * 12-unit user-space grid; the fill is a colour token and the rendered size is
 * `width`/`height`, so neither the font stack nor any font size can move it.
 *
 * Breathing: while the service is RUNNING the halo pulses — one 1200 ms cycle,
 * the Python cadence, as a CSS keyframe (no per-frame JS). After
 * {@link IDLE_S} seconds without interaction it *freezes where it is*
 * (`animation-play-state: paused`) and the next interaction resumes it, which
 * is how Python's `_BREATH_IDLE_S` behaved (L1552-1554). The master motion
 * switch and the OS preference are handled once, globally, by
 * `styles/global.css`; a RUNNING dot then just holds its green.
 *
 * Only RUNNING breathes: "we could not read the state" must not look alive.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps({
  /** The `sc query` state: `RUNNING` / `STOPPED` / a transitional one. */
  state: { type: String, default: '' },
  /** Rendered size in px. The SVG scales; nothing about it is font-derived. */
  size: { type: Number, default: 12 },
})

const RUNNING = 'RUNNING'
const STOPPED = 'STOPPED'

const running = computed(() => props.state === RUNNING)
const stopped = computed(() => props.state === STOPPED)
const known = computed(() => props.state !== '' && props.state !== 'UNKNOWN')

/** Green only for RUNNING; a transitional state is orange, not neutral. */
const fill = computed(() => {
  if (running.value) return 'var(--run)'
  if (stopped.value) return 'var(--stop)'
  return known.value ? 'var(--org)' : 'var(--gray)'
})

// ---- the 30 s idle freeze ------------------------------------------------

/** Ticket 14: stop breathing after 30 s without interaction. */
const IDLE_S = 30

/** What counts as interaction — Python bound `<Motion>` and `<Key>`. */
const INTERACTIONS = ['pointermove', 'pointerdown', 'keydown', 'wheel']

const idle = ref(false)
let timer = 0

/** Any interaction rewinds the freeze; the dot resumes on the next frame. */
function note() {
  idle.value = false
  clearTimeout(timer)
  timer = setTimeout(() => {
    idle.value = true
  }, IDLE_S * 1000)
}

onMounted(() => {
  for (const ev of INTERACTIONS) window.addEventListener(ev, note, { passive: true })
  note()
})

onBeforeUnmount(() => {
  clearTimeout(timer)
  for (const ev of INTERACTIONS) window.removeEventListener(ev, note)
})

/** Frozen only while RUNNING: the pulse holds its current frame. */
const frozen = computed(() => idle.value && running.value)
</script>

<template>
  <!--
    `aria-hidden`: the state word rendered next to it already says the state, so
    a screen reader must not hear a second, emptier version of it. The dot is
    decorative ink; `data-state` is there for tests, not for users.
  -->
  <svg
    class="dot"
    :class="{ 'is-breathing': running, 'is-frozen': frozen }"
    :width="size"
    :height="size"
    :style="{ color: fill }"
    :data-state="state || 'UNKNOWN'"
    viewBox="0 0 12 12"
    aria-hidden="true"
    focusable="false"
  >
    <!--
      The halo is the breathing part: a wide circle at low alpha that the
      keyframe scales and fades. Animating the halo rather than the core keeps
      the dot's footprint, hit area and line box identical in every frame —
      the Python bug was precisely a shape whose size moved.
    -->
    <circle class="halo" cx="6" cy="6" r="4.5" />
    <circle class="core" cx="6" cy="6" r="3.5" />
  </svg>
</template>

<style scoped>
.dot {
  display: block;
  flex: none;
  /* The halo is drawn outside the core's radius, so it must not be clipped. */
  overflow: visible;
}

.core {
  fill: currentColor;
  /* State change, not decoration: immediate in, the slow decay out. */
  transition: fill var(--m-hover-in) var(--m-ease-out);
}

.halo {
  fill: currentColor;
  opacity: 0;
  transform-origin: 6px 6px;
  transition: opacity var(--m-hover-out) var(--m-ease-decay);
}

/* Only a RUNNING service breathes, and it stops under `global.css`'s motion
   switch (`.motion-off` / `prefers-reduced-motion` zero every duration). */
.is-breathing .halo {
  animation: dot-breathe 1200ms var(--m-ease-decay) infinite;
}

/* 30 s without interaction: hold the current frame, do not reset it. */
.is-frozen .halo {
  animation-play-state: paused;
}

@keyframes dot-breathe {
  0% {
    opacity: 0.32;
    transform: scale(0.86);
  }
  50% {
    opacity: 0.1;
    transform: scale(1.14);
  }
  100% {
    opacity: 0.32;
    transform: scale(0.86);
  }
}
</style>

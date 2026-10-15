<script setup>
/**
 * The install transcript (ticket 15).
 *
 * `install_update` runs for minutes on a ~400 MB asset: it stops the service,
 * downloads two zips, backs the old files up, extracts, restarts, and waits for
 * the health probe — and it emits **one line per step** on
 * `llama-ctl://update-progress`. Lines are appended as they arrive, never
 * batched and never polled, so the UI stays responsive while Rust blocks on a
 * worker thread: the renderer's own frame loop is untouched.
 *
 * Every state the flow can reach has a screen here:
 *   - **idle, nothing yet** — the placeholder, which says a line will appear
 *     when the install starts rather than showing an empty box;
 *   - **streaming** — lines newest last, autoscrolled, with a live dot;
 *   - **done** — the last line is Rust's own `upd.done`;
 *   - **failed** — the failure line is red, and the transcript above it is kept
 *     (the rollback lines are the only record of what was restored).
 *
 * `aria-live="polite"` is on the body, so a screen reader reads each new step
 * without stealing focus from the button the user just pressed.
 */
import { computed, nextTick, ref, watch } from 'vue'
import { ut } from './update-copy.js'
import * as update from '../stores/update.js'

/** The scroll container, for autoscroll. */
const body = ref(null)

/** The transcript from the store: appended live by the event listener. */
const lines = computed(() => update.progress.value ?? [])

/** `true` while the install command is in flight. */
const running = computed(() => update.busy.value)

/** The failure line, `''` when the install succeeded or never ran. */
const failed = computed(() => update.error.value)

/** What the last install did, once it is done. */
const report = computed(() => update.report.value)

/** The summary line Rust's `InstallReport` allows, once there is one. */
const summary = computed(() => {
  const r = report.value
  if (!r) return ''
  return ut('upd.result', {
    r: (r.replaced ?? []).length,
    a: (r.added ?? []).length,
    d: r.downloaded ?? 0,
  })
})

/**
 * Autoscroll: the newest line is the one the user wants.
 *
 * Only while a line was actually added — a re-render that merely re-measures
 * must not yank the scroll position away from a user reading backwards.
 */
watch(
  () => lines.value.length,
  async (n, before) => {
    if (!n || n <= (before ?? 0)) return
    await nextTick()
    const el = body.value
    if (el) el.scrollTop = el.scrollHeight
  },
)
</script>

<template>
  <!--
    `data-progress-count` is what the smoke run reads: the number of lines on
    screen, so "lines appear as they arrive" is asserted on the DOM and not on
    internal state.
  -->
  <div class="progress" :data-progress-count="lines.length" :data-progress-running="running ? 'true' : 'false'">
    <div class="head">
      <svg
        v-if="running"
        class="pulse"
        width="10"
        height="10"
        viewBox="0 0 12 12"
        aria-hidden="true"
      >
        <!-- A vector dot, for the same reason the status dot is one: a font
             glyph's ink would move with the type scale. -->
        <circle cx="6" cy="6" r="4" />
      </svg>
      <span class="t-group title">{{ ut('upd.progress') }}</span>
      <span class="spacer" />
      <span v-if="running" class="t-micro muted">{{ update.statusLine.value }}</span>
    </div>

    <div
      ref="body"
      class="body scroll"
      role="log"
      aria-live="polite"
      aria-relevant="additions"
    >
      <p v-if="!lines.length" class="t-mono-sm muted empty">
        {{ ut('upd.progress.empty') }}
      </p>
      <p
        v-for="(line, i) in lines"
        :key="`${i}-${line}`"
        class="t-mono-sm line selectable wrap-anywhere"
        :class="{ 'is-last': i === lines.length - 1 }"
      >
        {{ line }}
      </p>
    </div>

    <p v-if="failed" class="t-small err wrap-anywhere selectable">{{ failed }}</p>
    <p v-else-if="summary" class="t-small done wrap-anywhere">{{ summary }}</p>
  </div>
</template>

<style scoped>
.progress {
  display: flex;
  flex-direction: column;
  gap: var(--sp-xs);
}

.head {
  display: flex;
  align-items: center;
  gap: var(--sp-sm);
  min-width: 0;
}

.title {
  min-width: 0;
}

.spacer {
  flex: 1 1 auto;
  min-width: 0;
}

.pulse {
  flex: none;
  color: var(--acc);
  /* Only alive while the install runs: a pulse on an idle transcript would
     claim work that is not happening. */
  animation: upd-pulse 1200ms var(--m-ease-decay) infinite;
}

.pulse circle {
  fill: currentColor;
}

@keyframes upd-pulse {
  0% {
    opacity: 0.9;
  }
  50% {
    opacity: 0.25;
  }
  100% {
    opacity: 0.9;
  }
}

.body {
  /*
    A fixed line box, not a fixed height: the transcript grows inside its own
    scroller, so a 40-step install cannot push the rest of the card off-screen
    and long lines reflow instead of being clipped away.
  */
  max-height: 180px;
  min-height: 64px;
  overflow-y: auto;
  overflow-x: hidden;
  padding: var(--sp-sm) var(--sp-md);
  border: 1px solid var(--border);
  border-radius: var(--r-ctl);
  background: var(--field);
}

.line,
.empty {
  margin: 0;
  /* Log lines are mono and compact: the point is density, not rhythm. */
  white-space: pre-wrap;
}

.empty {
  padding: var(--sp-xs) 0;
}

/* The newest line carries the accent: it is the step in progress. */
.line.is-last {
  color: var(--txt);
}

.err {
  margin: 0;
  color: var(--red);
}

.done {
  margin: 0;
  color: var(--run);
}
</style>

<script setup>
/**
 * The status card: service state, health verdict and install directory.
 *
 * This is ticket 09's tracer bullet, and it is the screen that proves the
 * round trip works: everything on it comes from one Snapshot fetch, so if the
 * IPC or the shape is wrong this is where it shows.
 *
 * The dot is a plain CSS circle, not a font glyph — ticket 14 turns it into
 * the breathing indicator, and a glyph would change size with the font size.
 * `RUNNING` is the only state that paints green; `STOPPED` and everything
 * unknown paint the neutral grey, because "we could not read it" must not look
 * like "it is fine".
 */
import { computed } from 'vue'
import * as store from '../stores/snapshot.js'

const RUNNING = 'RUNNING'
const STOPPED = 'STOPPED'

const state = computed(() => store.status.value.state ?? '')
const running = computed(() => state.value === RUNNING)
const stopped = computed(() => state.value === STOPPED)
const known = computed(() => state.value !== '' && state.value !== 'UNKNOWN')

/** The dot's colour: green only for RUNNING. */
const dotColor = computed(() => {
  if (running.value) return 'var(--run)'
  if (stopped.value) return 'var(--stop)'
  return 'var(--gray)'
})

const dir = computed(() => store.snapshot.snap?.facts?.app_dir ?? '')
const params = computed(() => store.snapshot.snap?.facts?.app_params ?? '')
const startMode = computed(() => store.snapshot.snap?.facts?.start ?? '')
</script>

<template>
  <section class="card status enter enter-1" aria-live="polite">
    <span class="dot" :style="{ background: dotColor }" aria-hidden="true" />

    <div class="col">
      <div class="t-section" :class="{ 'is-run': running }">
        {{ known ? state : store.t('state.unknown') }}
      </div>
      <div class="t-mono-sm muted selectable detail">
        {{ store.status.value.detail || store.t('health.idle') }}
      </div>
    </div>

    <div class="spacer" />

    <dl class="facts">
      <div class="fact">
        <dt class="t-micro muted">{{ store.t('svc.label') }}</dt>
        <dd class="t-mono selectable wrap-anywhere">
          {{ store.selected.value || '—' }}
        </dd>
      </div>
      <div class="fact">
        <dt class="t-micro muted">{{ store.t('boot.label') }}</dt>
        <dd class="t-mono">
          {{ startMode ? store.t(`boot.${startMode}`) : '—' }}
        </dd>
      </div>
      <div v-if="dir" class="fact">
        <dt class="t-micro muted">AppDirectory</dt>
        <dd class="t-mono selectable wrap-anywhere">{{ dir }}</dd>
      </div>
    </dl>

    <p v-if="params" class="params t-mono-sm muted selectable wrap-anywhere">
      {{ params }}
    </p>
  </section>
</template>

<style scoped>
.status {
  display: grid;
  grid-template-columns: auto auto 1fr;
  align-items: center;
  gap: var(--sp-md);
  /* A long parameter string must wrap, not overflow the card. */
  min-width: 0;
}

.dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  flex: none;
  /* State change, immediate: the dot is the answer to "is it up?". */
  transition: background-color var(--m-hover-in) var(--m-ease-out);
}

.col {
  min-width: 0;
}

.is-run {
  color: var(--run);
}

.detail {
  margin: 0;
}

.facts {
  display: flex;
  gap: var(--sp-xl);
  margin: 0;
  flex-wrap: wrap;
  justify-content: flex-end;
  min-width: 0;
}

.fact {
  min-width: 0;
  max-width: 320px;
}

.fact dt {
  margin: 0;
}

.fact dd {
  margin: 0;
}

.params {
  grid-column: 1 / -1;
  margin: 0;
  padding-top: var(--sp-sm);
  border-top: 1px solid var(--border);
}
</style>

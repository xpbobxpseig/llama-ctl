<script setup>
/**
 * The old-vs-new comparison Apply shows before it writes (ticket 17).
 *
 * Deliberate boundary: this renders a **diff**, it does not decide anything.
 * Whether the form has unapplied changes is Rust's (`Snapshot.facts.dirty`),
 * and whether the write-back actually changes anything is Rust's too
 * (`ApplyResult.written`). What is left for the screen is the honest part:
 *
 *   - the old text is Rust's own `AppParameters`, verbatim;
 *   - the old values are Rust's own parse of that text (`Snapshot.values`),
 *     not a second parse the frontend performed;
 *   - the new values are the form — the only state the frontend owns.
 *
 * The rows are a **textual** comparison, which is the same kind Apply uses:
 * writing back is the normalisation pass, so `0.80` vs `0.8` and a legacy
 * `-c` vs `--ctx-size` are worth showing even when they are semantically equal.
 */
import { computed } from 'vue'
import { FIELDS } from '../api/field-copy.js'
import * as store from '../stores/snapshot.js'
import { pt } from './submit-copy.js'

const props = defineProps({
  /** Rust's parse of the service's `AppParameters`. */
  old: { type: Object, default: () => ({}) },
  /** The form: the edit in progress, else what the service holds. */
  next: { type: Object, default: () => ({}) },
  /** The service's `AppParameters`, verbatim from Rust. */
  oldText: { type: String, default: '' },
})

/** An unset value, so an empty cell never looks like a missing one. */
const BLANK = computed(() => pt('apply.blank'))

function show(v) {
  const s = String(v ?? '').trim()
  return s === '' ? BLANK.value : s
}

/** One row per field whose value text differs, in Rust's own table order. */
const rows = computed(() =>
  FIELDS.filter(
    (f) => String(props.old[f.key] ?? '').trim() !== String(props.next[f.key] ?? '').trim(),
  ).map((f) => ({
    key: f.key,
    label: store.lang.value === 'en' ? f.en : f.zh,
    from: show(props.old[f.key]),
    to: show(props.next[f.key]),
  })),
)
</script>

<template>
  <div class="diff">
    <p class="t-small muted head">
      {{ rows.length ? pt('apply.changed', { n: rows.length }) : pt('msg.apply.same') }}
    </p>

    <!--
      Three fixed tracks: long labels and long paths shrink the middle cell,
      never overlap it, and never get clipped out of the dialog.
    -->
    <div v-if="rows.length" class="rows">
      <div class="row t-micro muted head-row">
        <span />
        <span>{{ pt('apply.from') }}</span>
        <span>{{ pt('apply.to') }}</span>
      </div>
      <div
        v-for="r in rows"
        :key="r.key"
        class="row"
        :data-diff-row="r.key"
      >
        <span class="label t-small wrap-anywhere">{{ r.label }}</span>
        <span class="from t-mono wrap-anywhere selectable">{{ r.from }}</span>
        <span class="to t-mono wrap-anywhere selectable">{{ r.to }}</span>
      </div>
    </div>

    <p class="t-micro muted old-label">{{ pt('apply.old') }}</p>
    <p class="old t-mono-sm muted wrap-anywhere selectable">{{ oldText }}</p>
  </div>
</template>

<style scoped>
.diff {
  display: flex;
  flex-direction: column;
  gap: var(--sp-xs);
  min-width: 0;
}

.head {
  margin: 0;
}

.rows {
  display: flex;
  flex-direction: column;
  gap: var(--sp-xs);
  min-width: 0;
}

.row {
  display: grid;
  grid-template-columns: minmax(96px, 1fr) minmax(0, 1.1fr) minmax(0, 1.1fr);
  align-items: baseline;
  gap: var(--sp-sm);
  min-width: 0;
}

.head-row {
  padding-bottom: 2px;
  border-bottom: 1px solid var(--border);
}

.from {
  color: var(--mut);
}

.to {
  color: var(--acc);
}

.old-label {
  margin: var(--sp-xs) 0 0;
}

.old {
  margin: 0;
  padding: var(--sp-xs) var(--sp-sm);
  background: var(--tip);
  border-radius: var(--r-ctl);
  /* A 300-character parameter string scrolls, it does not push the dialog's
     buttons out of reach. */
  max-height: 96px;
  overflow: auto;
}
</style>

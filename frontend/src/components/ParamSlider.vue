<script setup>
/**
 * One numeric parameter: a slider with a **live numeric readout**.
 *
 * The readout is the one place the Python build had a real 4px line-box
 * misalignment, and the fix is structural rather than a nudge: the readout is
 * `t-mono`, which is `--f-mono` (13px) at `line-height: 1.5` — the *same*
 * size and the *same* line-height as the `t-body` label beside it, so the two
 * share a baseline in any font. `tabular-nums` keeps the digits from reflowing
 * the row while the slider is dragged, and the column is a fixed `ch` width so
 * the widest value the bounds allow is already reserved (a wider number must
 * not push the row).
 *
 * The slider is NaiveUI's: it carries `role="slider"` with `aria-valuenow` /
 * `-min` / `-max` on a focusable handle, so arrow keys work with no extra
 * wiring. The rail and knob are the Python build's 6px / 16px, set by the
 * theme override.
 *
 * An out-of-range or non-numeric value is clamped to the bounds rather than
 * rendered as `NaN`, and the clamp is reported so the row can say so — the
 * Snapshot's `warnings` already carries Rust's own version of that message.
 */
import { computed } from 'vue'
import { NSlider } from 'naive-ui'
import * as store from '../stores/snapshot.js'

const props = defineProps({
  /** The field's presentation metadata (`src/api/field-copy.js`). */
  field: { type: Object, required: true },
  /** `true` while a command is in flight. */
  disabled: { type: Boolean, default: false },
})

/** The value on screen: the edit in progress, else what the service holds. */
const raw = computed(() => store.values.value[props.field.key] ?? '')

/** The parsed number, clamped into the field's own bounds. */
const num = computed(() => {
  const n = Number(raw.value)
  if (!Number.isFinite(n)) return props.field.def
  return Math.min(props.field.max, Math.max(props.field.min, n))
})

/** `true` when what the service holds is outside the bounds or not a number. */
const clamped = computed(() => {
  const n = Number(raw.value)
  return !Number.isFinite(n) || n < props.field.min || n > props.field.max
})

/** The unit, in the active language. */
const unit = computed(() => {
  const u = props.field.unit ?? {}
  return store.lang.value === 'en' ? (u.en ?? u.zh ?? '') : (u.zh ?? '')
})

/**
 * The readout: `%g` like Python's `f"{num:g}"`, so `0.8` stays `0.8` and
 * `131072` stays `131072` — no exponent, no trailing zeros.
 *
 * Rounded to the step's own precision rather than to a fixed number of digits,
 * so the string can never be longer than `readoutWidth` reserved: a value the
 * bounds allow is always at most `ints + 1 + digits` characters.
 */
const readout = computed(() => {
  const text = String(Number(num.value.toFixed(decimals(props.field.step))))
  const u = unit.value
  return u ? `${text} ${u}` : text
})

/**
 * How wide the readout column has to be: the widest value the bounds allow,
 * plus the unit, plus a character of slack — in `ch`, so the reserved width is
 * in the mono font's own digit width.
 *
 * A fractional step needs a point and its own digits on top of the integer
 * part: `0.05` is four characters where `1` is one. Getting this wrong is the
 * same family as the ticket's line-box item — a readout that changes size as
 * the value changes.
 */
const readoutWidth = computed(() => {
  const digits = decimals(props.field.step)
  const ints = Math.max(
    String(Math.trunc(props.field.max)).length,
    String(Math.trunc(props.field.min)).length,
  )
  const widest = ints + (digits > 0 ? 1 + digits : 0)
  const u = unit.value ? unit.value.length + 1 : 0
  return `${widest + u + 1}ch`
})

/** Commit an edit. The store owns the edit; Rust decides whether it matters. */
function edit(value) {
  store.editField(props.field.key, format(value))
}

/** How many decimals a step implies: `0.05` → 2, `1` → 0. */
function decimals(step) {
  return (String(step).split('.')[1] ?? '').length
}
/** Write back in the shape Rust's parser accepts for this step. */
function format(value) {
  const step = props.field.step
  if (Number.isInteger(step)) return String(Math.round(value))
  // A fractional step keeps at most the step's own precision (0.05 → 2).
  const digits = (String(step).split('.')[1] ?? '').length
  return String(Number(value.toFixed(digits)))
}
</script>

<template>
  <div class="slider-row">
    <NSlider
      class="rail"
      :value="num"
      :min="field.min"
      :max="field.max"
      :step="field.step"
      :disabled="disabled"
      :aria-label="field.zh"
      @update:value="edit"
    />
    <output
      class="readout t-mono"
      :class="{ 'is-clamped': clamped }"
      :style="{ width: readoutWidth }"
      :title="clamped ? `${raw} → ${readout}` : undefined"
    >
      {{ readout }}
    </output>
  </div>
</template>

<style scoped>
.slider-row {
  display: grid;
  grid-template-columns: minmax(140px, 1fr) auto;
  align-items: center;
  gap: var(--sp-md);
  /* Two tracks, always: a long label shrinks the rail, never the readout. */
  min-width: 0;
}

.rail {
  min-width: 0;
  /* The 16px knob overhangs the rail by 2px on each side; padding keeps it
     inside the column instead of being clipped by it. */
  padding: var(--sp-xs) 0;
}

/*
 * The readout. Mono, tabular, and — the whole point — the same font size and
 * line-height as the body label beside it, so there is nothing to compensate
 * for. The family, size and line-height come from `t-mono` (global.css), the
 * same token module the label's `.t-body` reads; only what is *this* control's
 * is set here.
 */
.readout {
  text-align: right;
  color: var(--txt);
  /* The number is what the user came for; it has to be copyable. */
  user-select: text;
  -webkit-user-select: text;
  /* Reserved width, not a growing one: dragging must not reflow the row. */
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  /* State, not decoration: a value that had to be clamped says so in orange. */
  transition: color var(--m-hover-in) var(--m-ease-out);
}

.is-clamped {
  color: var(--org);
}
</style>

<script setup>
/**
 * One enumerated parameter: a select, plus the explanation of the option that
 * is currently chosen.
 *
 * The option hint is the Python build's `lbl_hint` behaviour, moved next to
 * the control it belongs to instead of a single card-wide label: a hint that
 * lives under its own select cannot be about the wrong field. It is driven by
 * the *committed* value, not by a local draft, so it always agrees with what
 * the store — and therefore what Rust would write — holds.
 *
 * An empty option renders as「（空）」the way `CTkOptionMenu` did, but its
 * `value` stays `""`, so what goes back over IPC is the empty string Rust's
 * parser expects, never the placeholder.
 */
import { computed } from 'vue'
import { NSelect } from 'naive-ui'
import * as store from '../stores/snapshot.js'
import { OPTIONS, optionHelp } from '../api/field-copy.js'

/** What an empty option is called; its value stays `""`. */
const BLANK = '（空）'

const props = defineProps({
  field: { type: Object, required: true },
  disabled: { type: Boolean, default: false },
})

/** The committed value, `""` when the field is unset. */
const value = computed(() => store.values.value[props.field.key] ?? '')

/** The dropdown entries, in Rust's own option order. */
const options = computed(() =>
  (OPTIONS[props.field.key] ?? []).map((v) => ({
    value: v,
    label: v === '' ? BLANK : v,
  })),
)

/** The explanation of the chosen option, `''` when it has none. */
const hint = computed(() =>
  optionHelp(props.field.key, value.value, store.snapshot.snap?.strings),
)

function edit(next) {
  store.editField(props.field.key, next ?? '')
}
</script>

<template>
  <div class="combo">
    <NSelect
      class="pick"
      :value="value === '' ? null : value"
      :options="options"
      :disabled="disabled"
      :placeholder="BLANK"
      :aria-label="field.zh"
      size="small"
      @update:value="edit"
    />
    <!--
      The current option's own explanation. `aria-live` because it changes in
      answer to a selection, and a screen reader has to hear that.
    -->
    <p v-if="hint" class="hint t-small muted wrap-anywhere" aria-live="polite">
      {{ hint }}
    </p>
  </div>
</template>

<style scoped>
.combo {
  display: flex;
  flex-direction: column;
  gap: var(--sp-xs);
  min-width: 0;
}

.pick {
  min-width: 0;
  max-width: 260px;
}

/*
 * The option hint sits on its own line inside the control column. It is
 * `min-height`-free on purpose: an option with no explanation collapses the
 * paragraph entirely rather than leaving a gap.
 */
.hint {
  margin: 0;
  max-width: 420px;
  /* State change: the line answers the selection, so it appears immediately. */
  animation: hint-in var(--m-hover-in) var(--m-ease-out) both;
}

@keyframes hint-in {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}
</style>

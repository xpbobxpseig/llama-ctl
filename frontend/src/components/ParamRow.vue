<script setup>
/**
 * One parameter row: the「?」button, the label, and the widget its kind asks
 * for.
 *
 * The grid is the point of this component. Every kind renders into the same
 * two tracks — `label | control` — so a checkbox, a slider and a path input
 * line up in one column of controls however long their labels are, and a long
 * label wraps inside its own track instead of pushing the control out of the
 * card. A checkbox spans both, because its label *is* its control.
 *
 * The「?」button is first in the row and in the tab order, the Python build's
 * own order (`btn` in column 0, label in column 1).
 */
import { computed } from 'vue'
import { NInput } from 'naive-ui'
import * as store from '../stores/snapshot.js'
import { PARAM_COPY, OPTIONS, optionSlug, paramHelp } from '../api/field-copy.js'
import ParamHelp from './ParamHelp.vue'
import ParamSlider from './ParamSlider.vue'
import ParamCombo from './ParamCombo.vue'
import ParamCheck from './ParamCheck.vue'
import ParamPath from './ParamPath.vue'

const props = defineProps({
  field: { type: Object, required: true },
  disabled: { type: Boolean, default: false },
})

/** The label in the active language. Chinese is Rust's own `Field::label`. */
const label = computed(() =>
  store.lang.value === 'en' ? (props.field.en || props.field.zh) : props.field.zh,
)

/** The explanation, from Rust's string table when it has the key. */
const help = computed(() => paramHelp(props.field.key, store.snapshot.snap?.strings))

/**
 * The per-option lines inside the popover, so a combo's「?」answers "what do
 * the choices mean" without the user having to try each one.
 */
const optionLines = computed(() => {
  const values = OPTIONS[props.field.key] ?? []
  const strings = store.snapshot.snap?.strings
  return values
    .map((v) => {
      const key = `param.opt.${props.field.key}.${optionSlug(v)}`
      const text = strings?.[key] ?? PARAM_COPY[key] ?? ''
      return text ? [v === '' ? '（空）' : v, text] : null
    })
    .filter(Boolean)
})

/** `true` when the row is a checkbox: its label is its control. */
const isCheck = computed(() => props.field.kind === 'check')

function edit(next) {
  store.editField(props.field.key, next ?? '')
}
</script>

<template>
  <div class="field" :class="{ 'is-check': isCheck }" :data-field="field.key">
    <ParamHelp class="q" :text="help" :label="label" :options="optionLines" />

    <label
      v-if="!isCheck"
      class="name t-body wrap-anywhere"
      :for="field.kind === 'text' ? `f-${field.key}` : undefined"
    >
      {{ label }}
    </label>

    <ParamSlider
      v-if="field.kind === 'slider'"
      class="control"
      :field="field"
      :disabled="disabled"
    />
    <ParamCombo
      v-else-if="field.kind === 'combo'"
      class="control"
      :field="field"
      :disabled="disabled"
    />
    <ParamCheck
      v-else-if="field.kind === 'check'"
      class="control"
      :field="field"
      :disabled="disabled"
    />
    <ParamPath
      v-else-if="field.kind === 'path'"
      class="control"
      :field="field"
      :disabled="disabled"
    />
    <!--
      Only the plain text input has a real `id`, so only it gets a `for`: a
      label pointing at nothing is worse than no `for` at all. Every other
      widget carries its own `aria-label`.
    -->
    <NInput
      v-else
      :id="`f-${field.key}`"
      class="control"
      size="small"
      :value="store.values.value[field.key] ?? ''"
      :disabled="disabled"
      :placeholder="label"
      :aria-label="field.zh"
      @update:value="edit"
    />
  </div>
</template>

<style scoped>
/*
 * Two tracks, and they stay two tracks: `minmax` on the label so a long one
 * wraps instead of overflowing, `1fr` on the control so it takes what is left.
 * Nothing here is `overflow: hidden`, so a layout defect cannot hide.
 */
.field {
  display: grid;
  grid-template-columns: 24px minmax(120px, auto) 1fr;
  align-items: center;
  gap: var(--sp-sm);
  padding: var(--sp-xs) 0;
  min-width: 0;
}

/* A checkbox's own label is the control, so it takes the rest of the row. */
.is-check {
  grid-template-columns: 24px 1fr;
}

.q {
  /* The popover's own styles are on the trigger button; here it only has to
     stay a fixed 24px that cannot be squeezed by a long row. */
  justify-self: start;
  flex: none;
}

.name {
  min-width: 0;
  color: var(--txt);
  cursor: default;
}

.control {
  min-width: 0;
  justify-self: start;
  width: 100%;
}

.is-check .control {
  width: auto;
}
</style>

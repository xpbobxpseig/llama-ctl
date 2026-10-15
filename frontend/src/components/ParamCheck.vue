<script setup>
/**
 * One boolean parameter: a checkbox.
 *
 * Rust's parser reads `1` / `true` / `on` / `yes` as on (params.rs L293), so
 * the checkbox writes `1` / `""` — the same shape the Python build wrote
 * (`onvalue="1"`, `offvalue=""`), and the shape `build_params` already accepts.
 *
 * One field ships ON in llama.cpp and must be turned *off* with a negation
 * (`--jinja` / `--no-jinja`). For that one, "absent" means on, so an unset
 * value renders as checked and unchecking is what emits `--no-jinja`. The
 * ticket asks for a checkbox, not a tri-state, because the third state is not
 * the user's to choose — Rust decides what absent means.
 */
import { computed } from 'vue'
import { NCheckbox } from 'naive-ui'
import * as store from '../stores/snapshot.js'

const props = defineProps({
  field: { type: Object, required: true },
  disabled: { type: Boolean, default: false },
})

const raw = computed(() => store.values.value[props.field.key] ?? '')

const checked = computed(() => {
  const v = raw.value
  // A switch that ships ON is on unless it was explicitly turned off; every
  // other switch is on only when a truthy value is there.
  if (props.field.onByDefault) return v !== '' && v !== '0' && v !== 'false'
  return v === '1' || v === 'true' || v === 'on' || v === 'yes'
})

function edit(next) {
  store.editField(props.field.key, next ? '1' : '')
}
</script>

<template>
  <NCheckbox
    class="check"
    :checked="checked"
    :disabled="disabled"
    :aria-label="field.zh"
    @update:checked="edit"
  >
    <span class="t-body">{{ store.lang.value === 'en' ? field.en : field.zh }}</span>
  </NCheckbox>
</template>

<style scoped>
.check {
  /* A checkbox is a whole row: it must not be squeezed by a long neighbour. */
  min-width: 0;
  padding: var(--sp-xs) 0;
}
</style>

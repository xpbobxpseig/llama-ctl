<script setup>
/**
 * One collapsible parameter group: a header button and its fields.
 *
 * Plain DOM, not NaiveUI's `NCollapse`, because the state this holds has to
 * survive a language or theme switch and the simplest way to guarantee that is
 * for the component not to own it at all: `open` is a prop, and the parent
 * keeps the whole map. A collapse that owned its own state would be rebuilt
 * with the string table and would spring shut.
 *
 * The header is a `button` with `aria-expanded` and `aria-controls`, so it is
 * keyboard-operable and announces its state. The chevron is a CSS triangle
 * rather than a font glyph, for the same reason the status dot is: a glyph
 * changes size with the font size, a triangle does not.
 */
import { computed } from 'vue'
import * as store from '../stores/snapshot.js'
import { GROUP_LABEL } from '../api/field-copy.js'
import ParamRow from './ParamRow.vue'

const props = defineProps({
  /** The group's Chinese key — Rust's own `G_*` value. */
  group: { type: String, required: true },
  /** The fields in this group, in table order. */
  fields: { type: Array, required: true },
  /** `true` when the body is shown. Owned by the parent, not here. */
  open: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
})

defineEmits(['toggle'])

/** The heading in the active language. */
const label = computed(() => {
  const entry = GROUP_LABEL[props.group]
  if (!entry) return props.group
  return store.lang.value === 'en' ? entry.en : entry.zh
})

/** Stable ids for `aria-controls` — derived from the group, so they survive a re-render. */
const bodyId = computed(() => `grp-${props.group}`)
</script>

<template>
  <section class="group" :data-group="group">
    <button
      type="button"
      class="head t-group"
      :class="{ 'is-open': open }"
      :aria-expanded="open"
      :aria-controls="bodyId"
      @click="$emit('toggle')"
    >
      <span class="chev" :class="{ 'is-open': open }" aria-hidden="true" />
      <span class="title">{{ label }}</span>
      <span class="count t-micro muted">{{ fields.length }}</span>
    </button>

    <!--
      The body stays mounted when collapsed (`v-show`, not `v-if`): the fields'
      values are in the store either way, and remounting them on every expand
      would throw away the focus the user just tabbed into.
    -->
    <div v-show="open" :id="bodyId" class="body">
      <ParamRow
        v-for="field in fields"
        :key="field.key"
        :field="field"
        :disabled="disabled"
      />
    </div>
  </section>
</template>

<style scoped>
.group {
  border-top: 1px solid var(--border);
  min-width: 0;
}

.group:first-of-type {
  border-top: none;
}

.head {
  display: flex;
  align-items: center;
  gap: var(--sp-sm);
  width: 100%;
  padding: var(--sp-sm) 0;
  font-family: var(--font-ui);
  font-size: var(--f-group);
  font-weight: 700;
  line-height: 1.4;
  color: var(--mut);
  text-align: left;
  background: transparent;
  border: 0;
  cursor: pointer;
  /* State change: the header answers a click, so it moves immediately and
     decays back out. */
  transition: color var(--m-hover-in) var(--m-ease-out);
}

.head:hover {
  color: var(--txt);
}

.head:active {
  color: var(--acc);
}

/* Open is accent, closed is muted — the Python build's own distinction
   (`C_ACC if open else C_MUT`), and it is the cheapest possible answer to
   "which groups am I looking at". */
.is-open {
  color: var(--acc);
}

/*
 * The chevron: two borders rotated into a triangle. It cannot drift with the
 * font size and it needs no icon asset (ADR-0001: everything local).
 */
.chev {
  width: 8px;
  height: 8px;
  flex: none;
  border-right: 1.5px solid currentColor;
  border-bottom: 1.5px solid currentColor;
  transform: rotate(-45deg);
  transform-origin: center;
  transition: transform var(--m-enter) var(--m-ease-out);
}

.chev.is-open {
  transform: rotate(45deg);
}

.title {
  min-width: 0;
}

.count {
  font-weight: 400;
}

.body {
  display: flex;
  flex-direction: column;
  gap: var(--sp-xs);
  padding: 0 0 var(--sp-md) var(--sp-lg);
  /* Long content reflows inside the group; nothing is clipped. */
  min-width: 0;
  /* One entrance for the body, spring-like, so expanding reads as a reveal
     rather than a jump. Reduced motion zeroes the duration, not the reveal. */
  animation: body-in var(--m-enter) var(--m-ease-out) both;
}

@keyframes body-in {
  from {
    opacity: 0;
    transform: translate3d(0, -4px, 0);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
</style>

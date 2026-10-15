<script setup>
/**
 * The parameter form: seven collapsible groups, one widget per field kind, and
 * a「?」on every parameter.
 *
 * **Expansion state lives here, in a module-level `ref`, and nowhere else.**
 * That is what makes it survive a language or theme switch: both go through
 * `save_settings`, which returns a fresh Snapshot and re-renders the tree, and
 * a state kept inside a component would be rebuilt with it and spring shut.
 * The map is keyed by the group's Chinese name — Rust's own `G_*` value — so it
 * is not affected by the heading being translated either.
 *
 * The first two groups are expanded by default, as the ticket asks.
 *
 * Rust stays authoritative throughout: this component reads `store.values` (the
 * edit in progress, else what the service holds) and writes through
 * `store.editField`, which is the frontend's entire write surface. It never
 * decides whether the form is dirty — `is_dirty` is a command and the Snapshot
 * already carries the answer.
 */
import { computed, ref } from 'vue'
import { NEmpty, NAlert } from 'naive-ui'
import * as store from '../stores/snapshot.js'
import { FIELDS, GROUP_ORDER } from '../api/field-copy.js'
import ParamGroup from './ParamGroup.vue'

/**
 * Which groups are open. Module scope, not component scope: the whole point is
 * that a re-render — a language switch, a theme switch, a Snapshot refresh —
 * leaves it exactly as the user left it.
 *
 * `ponytail:` the two open by default are the first two in `GROUP_ORDER`; if
 * the table ever gains a group, the default is still "the first two", and a
 * persisted-per-session map would be the upgrade path if that stops being
 * enough.
 */
const open = ref(
  Object.fromEntries(GROUP_ORDER.map((g, i) => [g, i < 2])),
)

/** The seven groups in Rust's own order, each with its fields in table order. */
const groups = computed(() =>
  GROUP_ORDER.map((group) => ({
    group,
    fields: FIELDS.filter((f) => f.group === group),
  })).filter((g) => g.fields.length > 0),
)

/** Every field the form renders, for the "n parameters" count. */
const total = computed(() => FIELDS.length)

function toggle(group) {
  open.value = { ...open.value, [group]: !open.value[group] }
}

/** Expand or collapse everything — one action, not seven clicks. */
function setAll(next) {
  open.value = Object.fromEntries(GROUP_ORDER.map((g) => [g, next]))
}

const allOpen = computed(() => GROUP_ORDER.every((g) => open.value[g]))
</script>

<template>
  <section class="card params enter enter-2" :aria-label="store.t('card.params')">
    <header class="head">
      <h2 class="t-section title">{{ store.t('card.params') }}</h2>
      <span class="count t-micro muted">{{ total }}</span>
      <div class="spacer" />
      <button type="button" class="link t-small" @click="setAll(!allOpen)">
        {{ allOpen ? store.t('shell.collapse_all') : store.t('shell.expand_all') }}
      </button>
    </header>

    <!-- No service selected: the form has nothing to edit. -->
    <NEmpty
      v-if="!store.selected.value"
      class="empty"
      :description="store.t('shell.no_service')"
    />

    <template v-else>
      <!--
        Parse warnings are Rust's own (`Snapshot.warnings`), rendered verbatim:
        an out-of-range slider value the service actually holds is something the
        user has to be told before they edit around it.
      -->
      <NAlert
        v-if="store.snapshot.snap?.warnings?.length"
        type="warning"
        class="warn"
        :show-icon="false"
      >
        <ul class="lines">
          <li
            v-for="(line, i) in store.snapshot.snap.warnings"
            :key="i"
            class="t-small selectable wrap-anywhere"
          >
            {{ line }}
          </li>
        </ul>
      </NAlert>

      <div class="groups">
        <ParamGroup
          v-for="entry in groups"
          :key="entry.group"
          :group="entry.group"
          :fields="entry.fields"
          :open="!!open[entry.group]"
          :disabled="store.busy.value"
          @toggle="toggle(entry.group)"
        />
      </div>
    </template>
  </section>
</template>

<style scoped>
.params {
  display: flex;
  flex-direction: column;
  gap: var(--sp-sm);
  min-width: 0;
}

.head {
  display: flex;
  align-items: baseline;
  gap: var(--sp-sm);
  min-width: 0;
}

.title {
  margin: 0;
  min-width: 0;
}

.count {
  font-weight: 400;
}

/* Expand-all / collapse-all: a text button, because it is a command on the
   list, not an action on the service. */
.link {
  flex: none;
  padding: 2px var(--sp-sm);
  font-family: var(--font-ui);
  font-size: var(--f-small);
  color: var(--mut);
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--r-ctl);
  cursor: pointer;
  transition:
    color var(--m-hover-in) var(--m-ease-out),
    background-color var(--m-hover-out) var(--m-ease-decay),
    border-color var(--m-hover-out) var(--m-ease-decay);
}

.link:hover {
  color: var(--acc);
  border-color: var(--acc);
  background: var(--tip);
  transition-duration: var(--m-hover-in);
}

.link:active {
  color: var(--acch);
}

.empty {
  padding: var(--sp-md) 0;
}

.warn {
  margin: 0;
}

.lines {
  margin: 0;
  padding-left: var(--sp-lg);
  display: flex;
  flex-direction: column;
  gap: var(--sp-xs);
}

/*
 * The group list is a plain block, not a scroll container: the shell's content
 * slot already scrolls, and a second scrollbar inside it would give the card
 * two scroll positions for one list.
 */
.groups {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
</style>

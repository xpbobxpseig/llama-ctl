<script setup>
/**
 * The window frame: title bar, the top service bar slot, the content slot and
 * the footer hint. Tickets 14-17 fill the slots; this file owns the chrome and
 * the grid that keeps them from overlapping when content grows.
 *
 * The layout is one column with four rows — `auto auto 1fr auto` — so the
 * content slot absorbs every spare pixel and the footer never rides up over
 * it. Long content scrolls inside the slot, never by pushing the chrome out of
 * view, and no row is ever clipped to hide overflow.
 */
import * as store from '../stores/snapshot.js'
import ServiceBar from './ServiceBar.vue'
</script>

<template>
  <div class="shell">
    <header class="bar">
      <h1 class="t-display title">{{ store.t('app.title') }}</h1>
      <div class="spacer" />
      <div class="actions">
        <!-- Outside the Tauri shell everything on screen is the fixture, and
             saying so beats letting demo data pass for a live service. -->
        <span v-if="store.isDemo.value" class="demo t-micro">
          {{ store.t('shell.demo') }}
        </span>
        <slot name="actions" />
      </div>
    </header>

    <!-- The top service bar slot: ticket 14 owns the controls inside it. -->
    <div class="svc">
      <slot name="service">
        <ServiceBar />
      </slot>
    </div>

    <!-- The content slot: the only area that scrolls. -->
    <main class="content scroll">
      <slot />
    </main>

    <footer v-if="store.dirty.value || store.error.value" class="foot">
      <span v-if="store.dirty.value" class="hint t-small">
        {{ store.t('status.dirty') }}
      </span>
      <span v-if="store.error.value" class="err t-small wrap-anywhere selectable">
        {{ store.error.value }}
      </span>
    </footer>
  </div>
</template>

<style scoped>
.shell {
  display: grid;
  grid-template-rows: auto auto 1fr auto;
  height: 100%;
  gap: var(--sp-md);
  padding: var(--sp-lg) var(--sp-xl);
  /* Without `min-height: 0` a grid child refuses to shrink below its content
     and the whole shell grows past the window. */
  min-height: 0;
}

.bar {
  display: flex;
  align-items: center;
  gap: var(--sp-sm);
  min-width: 0;
}

.title {
  margin: 0;
  /* Long titles shrink instead of pushing the buttons off the bar. */
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.actions {
  display: flex;
  align-items: center;
  gap: var(--sp-sm);
  flex: none;
}

.demo {
  padding: 2px var(--sp-sm);
  border-radius: 999px;
  border: 1px solid var(--org);
  color: var(--org);
  white-space: nowrap;
}

.svc {
  min-width: 0;
}

.content {
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding-right: var(--sp-xs);
}

.foot {
  display: flex;
  align-items: center;
  gap: var(--sp-md);
  min-height: 20px;
  /* Two long lines stack instead of overlapping. */
  flex-wrap: wrap;
}

.hint {
  color: var(--org);
}

.err {
  color: var(--red);
}
</style>

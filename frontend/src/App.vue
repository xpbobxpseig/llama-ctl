<script setup>
/**
 * The app root: theme provider, view switching, and the boot sequence.
 *
 * Boot order matters and is the whole point of this file:
 *   1. `n-config-provider` mounts with the theme for the resolved appearance,
 *      so the first paint is already in the right palette;
 *   2. the Snapshot is fetched and — only once it lands — the remembered
 *      window geometry is applied, because the geometry lives in the snapshot;
 *   3. the resize/move listeners start, so the next restart remembers this
 *      session's size and position.
 *
 * View switching is by key, not by URL: there is exactly one window, no deep
 * links, and a route library would be a dependency for a two-state switch.
 *
 * Every reachable state has a screen: loading (spinner), error (the rendered
 * failure line plus Retry), empty (no service known), and ready.
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  NConfigProvider,
  NMessageProvider,
  NButton,
  NSpin,
  NEmpty,
  NAlert,
  darkTheme,
} from 'naive-ui'
import AppShell from './components/AppShell.vue'
import ConsoleView from './views/ConsoleView.vue'
import SettingsView from './views/SettingsView.vue'
import { naiveOverrides, cssVars } from './theme/index.js'
import * as store from './stores/snapshot.js'
import * as theme from './stores/theme.js'
import * as geo from './window/geometry.js'
import * as ipc from './api/ipc.js'

/** `"console" | "settings"` — the only two destinations. */
const view = ref('console')

const mode = computed(() => theme.mode.value)

/** The NaiveUI theme object: `null` is light, `darkTheme` is dark. */
const naiveTheme = computed(() => (mode.value === 'dark' ? darkTheme : null))

/** The overrides, rebuilt whenever the appearance changes. */
const overrides = computed(() => naiveOverrides(mode.value))

/** The custom properties the plain-DOM half reads. */
const vars = computed(() => cssVars(mode.value))

/** The master motion switch, applied as a class so CSS can zero every duration. */
const motionOff = computed(() => theme.reducedMotion.value)

const hasService = computed(() => store.services.value.length > 0)

/**
 * Apply the remembered geometry the first time a Snapshot with one arrives.
 * It cannot happen at mount: `settings.geometry` is not known until Rust
 * answers.
 */
watch(
  () => store.settings.value?.geometry,
  async (value, before) => {
    if (!value || before !== undefined) return
    await geo.restoreGeometry()
  },
)

onMounted(async () => {
  theme.startAppearance()
  await store.refresh()
  await geo.watchGeometry()
  // Progress lines from restart / install stream to the shell's log.
  unlisten.push(
    await ipcSafe(() => ipc.onProgress(ipc.EVENT_RESTART, store.pushLog)),
    await ipcSafe(() => ipc.onProgress(ipc.EVENT_UPDATE, store.pushLog)),
  )
})

onUnmounted(() => {
  unlisten.forEach((fn) => fn && fn())
  unlisten.length = 0
  geo.stopGeometry()
})

/** Listeners to drop on unmount. */
const unlisten = []

/**
 * Run a subscription, tolerating its absence.
 *
 * Outside the Tauri shell there is no event system, and a rejected subscription
 * must not take the whole boot down with it — the app still renders, it just
 * shows no live progress.
 */
async function ipcSafe(fn) {
  try {
    return await fn()
  } catch {
    return null
  }
}

function toSettings() {
  view.value = 'settings'
}

function toConsole() {
  view.value = 'console'
}
</script>

<template>
  <NConfigProvider
    :theme="naiveTheme"
    :theme-overrides="overrides"
    :style="vars"
    class="root"
    :class="{ 'motion-off': motionOff }"
  >
    <NMessageProvider>
      <AppShell>
        <template #actions>
          <NButton
            size="small"
            :secondary="view === 'console'"
            :type="view === 'settings' ? 'primary' : 'default'"
            :disabled="store.busy.value && !store.ready.value"
            @click="view === 'console' ? toSettings() : toConsole()"
          >
            {{ store.t('btn.settings') }}
          </NButton>
        </template>

        <!-- Loading: the first fetch has not answered yet. -->
        <div v-if="store.phase.value === 'loading'" class="center">
          <NSpin size="medium" />
          <span class="t-small muted">{{ store.t('health.idle') }}</span>
        </div>

        <!--
          Error: the fetch itself failed. Everything else keeps the last good
          snapshot on screen and shows the line in the footer, so a failed
          command never blanks the window.
        -->
        <div v-else-if="store.phase.value === 'error' && !store.ready.value" class="center">
          <NAlert type="error" :title="store.t('mb.error')" class="errbox">
            <span class="t-body selectable wrap-anywhere">{{ store.error.value }}</span>
          </NAlert>
          <NButton
            size="small"
            type="primary"
            :disabled="store.busy.value"
            @click="store.refresh()"
          >
            {{ store.t('shell.retry') }}
          </NButton>
        </div>

        <!-- Empty: Rust knows no NSSM service at all. -->
        <div v-else-if="!hasService" class="center">
          <NEmpty :description="store.t('shell.no_service')" />
          <NButton
            size="small"
            secondary
            :disabled="store.busy.value"
            @click="store.run('refresh_services', () => ipc.refreshServices())"
          >
            {{ store.t('shell.rescan') }}
          </NButton>
        </div>

        <ConsoleView v-else-if="view === 'console'" />
        <SettingsView v-else @close="toConsole" />
      </AppShell>
    </NMessageProvider>
  </NConfigProvider>
</template>

<style scoped>
.root {
  height: 100%;
  background: var(--bg);
  color: var(--txt);
}

.center {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--sp-md);
  min-height: 240px;
  padding: var(--sp-xl);
  text-align: center;
}

.errbox {
  max-width: 560px;
  text-align: left;
}
</style>

<script setup>
/**
 * The official-update section (ticket 15).
 *
 * Everything here defers to Rust, and the places it cannot are the interesting
 * ones:
 *
 *   - **The build variant list is `Snapshot.channels`.** Rust builds it from
 *     `updater::channels()`, so a retired id or a new one appears here without
 *     a frontend edit. Choosing one goes through `save_settings` and is
 *     confirmed by the Snapshot Rust returns — and it *invalidates the last
 *     check*, because Rust refuses to install a release the user did not see the
 *     notes for (`msg.channel.changed`).
 *   - **「立即检查」never installs.** `check_update` is read-only (ADR-0001) and
 *     the startup check calls the same function with `silent`, so the one code
 *     path that runs at boot cannot download anything.
 *   - **「立即更新」only asks.** The two questions live in `UpdatePrompt`, which
 *     the window renders once, and only the second one's confirmation starts the
 *     install.
 *   - **The progress lines stream.** `install_update` emits one per step for
 *     minutes; `UpdateProgress` appends them as they arrive.
 *
 * The status line's three cases are the ticket's own requirement: an unreadable
 * `llama-server.exe` reads as「未知」, which is *not* the same as「还未检查过」,
 * and neither is a build number.
 */
import { computed, ref } from 'vue'
import { NSelect, NButton, NSwitch, NAlert, NTooltip } from 'naive-ui'
import UpdateProgress from './UpdateProgress.vue'
import { ut } from './update-copy.js'
import * as store from '../stores/snapshot.js'
import * as update from '../stores/update.js'

/** The last failed preference write, shown inline rather than as a modal. */
const failed = ref('')

/** The variant on screen: what Rust last persisted, never a local guess. */
const channel = computed(() => update.channel.value)

/** `unknown` / `known` / `none`:「未知」is the unreadable case. */
const statusKind = computed(() => update.statusKind.value)

/** The variant list, straight from Rust's `channels`. */
const channels = computed(() => update.channels.value)

/** `true` while a check or an install is in flight. */
const busy = computed(() => update.busy.value)

/** `true` while specifically the check is running. */
const checking = computed(() => busy.value && update.release.value === null)

/** The status line: 当前 b… / 版本未知 / 还未检查过, plus the latest tag. */
const statusLine = computed(() => update.statusLine.value)

/** The startup auto-check preference, as Rust persisted it. */
const autoOn = computed(() => update.autoOnStartup.value)

/** `true` when a release is known and could be installed. */
const canInstall = computed(() => update.canInstall.value)

/** The last check's failure, if any. */
const checkError = computed(() => update.error.value)

/**
 * Why「立即更新」is disabled, so a greyed control says why.
 *
 * '' means live. Two cases are real: no check has run yet, and one is running.
 */
const whyInstall = computed(() => {
  if (!store.selected.value) return store.t('msg.no.service')
  if (busy.value) return store.t('upd.checking')
  if (!canInstall.value) return store.t('upd.status.none')
  return ''
})

/** Why「立即检查」is disabled. */
const whyCheck = computed(() => {
  if (!store.selected.value) return store.t('msg.no.service')
  if (busy.value) return store.t('upd.checking')
  return ''
})

// ---- actions ---------------------------------------------------------------

/** Check for a newer build. Never installs, whichever way it was triggered. */
async function onCheck() {
  failed.value = ''
  await update.check()
}

/** Persist the variant. The answer is the new Snapshot, not the click. */
async function onChannel(next) {
  failed.value = (await update.setChannel(next)) ? '' : store.error.value
}

/** Persist the startup-check preference. */
async function onAuto(next) {
  failed.value = (await update.setAutoOnStartup(next)) ? '' : store.error.value
}

/** Open the second confirmation, the one that names the backup directory. */
function onAskInstall() {
  update.askInstall()
}
</script>

<template>
  <section class="card upd enter enter-3" data-update-section="">
    <h2 class="t-section title">{{ store.t('upd.section') }}</h2>

    <!--
      The status line. `data-update-status` carries which of the three cases it
      is, so the smoke run can assert「未知」really is the unreadable case and
      not a missing one.
    -->
    <p
      class="t-small status"
      :class="{ 'is-unknown': statusKind === 'unknown' }"
      :data-update-status="statusKind"
    >
      {{ statusLine }}
    </p>

    <div class="field">
      <label class="t-body" for="upd-channel">{{ store.t('upd.channel') }}</label>
      <NSelect
        id="upd-channel"
        data-update-channel=""
        :value="channel"
        :options="channels"
        :disabled="busy"
        size="small"
        class="ctl"
        @update:value="onChannel"
      />
      <span class="t-micro muted note">{{ ut('upd.channel.hint') }}</span>
    </div>

    <div class="field">
      <label class="t-body" for="upd-auto">{{ store.t('upd.auto.label') }}</label>
      <span class="auto" data-update-auto="">
        <NSwitch
          id="upd-auto"
          :value="autoOn"
          :disabled="busy"
          :aria-label="store.t('upd.auto.label')"
          @update:value="onAuto"
        />
        <span class="t-micro muted">{{ autoOn ? ut('upd.auto.on') : ut('upd.auto.off') }}</span>
      </span>
    </div>

    <div class="actions">
      <NTooltip :disabled="!whyCheck" :delay="300">
        <template #trigger>
          <NButton
            size="small"
            secondary
            data-update-action="check"
            :loading="checking"
            :disabled="busy || !store.selected.value"
            @click="onCheck"
          >
            {{ checking ? ut('upd.check.now') : store.t('upd.check') }}
          </NButton>
        </template>
        {{ whyCheck }}
      </NTooltip>

      <NTooltip :disabled="!whyInstall" :delay="300">
        <template #trigger>
          <NButton
            size="small"
            type="primary"
            data-update-action="install"
            :disabled="!canInstall || !store.selected.value"
            @click="onAskInstall"
          >
            {{ store.t('upd.install') }}
          </NButton>
        </template>
        {{ whyInstall }}
      </NTooltip>

      <span class="spacer" />

      <!-- The release Rust found, and the way back to its notes. -->
      <button
        v-if="update.release.value"
        type="button"
        class="link t-small"
        data-update-action="notes"
        @click="update.openNotes(true)"
      >
        {{ store.t('upd.changelog') }}
      </button>
    </div>

    <NAlert v-if="checkError" type="error" :show-icon="false" class="fail">
      <span class="wrap-anywhere selectable">{{ checkError }}</span>
    </NAlert>
    <NAlert v-if="failed" type="error" :show-icon="false" class="fail">
      <span class="wrap-anywhere selectable">{{ failed }}</span>
    </NAlert>

    <!-- The whole install, line by line, as Rust streams it. -->
    <UpdateProgress />

    <!--
      The two questions are not here. They live in `UpdatePrompt`, which the
      window renders once: the startup check runs while the console is on
      screen, so a prompt owned by this section would never be seen.
    -->
  </section>
</template>

<style scoped>
.upd {
  display: flex;
  flex-direction: column;
  gap: var(--sp-sm);
  min-width: 0;
}

.title {
  margin: 0;
}

.status {
  margin: 0;
  color: var(--mut);
}

/* An unreadable build is worth seeing: it is why「已是最新」cannot be claimed. */
.status.is-unknown {
  color: var(--org);
}

/* Two stable tracks, so a long label wraps in its own column. */
.field {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 200px;
  align-items: center;
  gap: var(--sp-sm) var(--sp-md);
  padding: var(--sp-sm) 0;
  border-top: 1px solid var(--border);
}

.ctl {
  min-width: 0;
}

.note {
  grid-column: 1 / -1;
  margin: 0;
}

.auto {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-xs);
}

.actions {
  display: flex;
  align-items: center;
  gap: var(--sp-sm);
  flex-wrap: wrap;
  padding-top: var(--sp-sm);
  border-top: 1px solid var(--border);
}

.spacer {
  flex: 1 1 auto;
  min-width: 0;
}

/* A text button: the way back to the notes after closing them. */
.link {
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--acc);
  font: inherit;
  cursor: pointer;
  /* Immediate feedback, like every other control. */
  transition: color var(--m-hover-in) var(--m-ease-out);
}

.link:hover {
  color: var(--acch);
}

.fail {
  margin-top: var(--sp-xs);
}
</style>

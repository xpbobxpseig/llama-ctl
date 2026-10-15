<script setup>
/**
 * The top service bar: the service dropdown plus the actions.
 *
 * This is the *slot filler* the shell ships, and it is deliberately thin —
 * ticket 14 replaces its contents with the real start/stop/restart/auto-start
 * controls and the breathing status dot. What is already load-bearing here:
 *
 *   - switching service is a real `switch_service` call, and the answer is a
 *     new Snapshot (Rust refuses an unknown name rather than showing an empty
 *     form, which is ticket 11's rule 2);
 *   - every control is disabled while a command is in flight, or while there
 *     is nothing selected — a disabled control says *why* through its tooltip.
 *
 * No service state is mirrored: the dropdown's value is `selected` from the
 * snapshot, so it cannot drift from what Rust last read — and a cancelled
 * switch question needs no rollback, because the box never moved by itself.
 *
 * Ticket 17 added one rule here: switching away from a form with unapplied
 * changes asks first and offers an Auto backup. Whether there *are* unapplied
 * changes is Rust's verdict (`Snapshot.facts.dirty`), never the dropdown's.
 */
import { computed, ref } from 'vue'
import { NSelect, NButton, NTooltip } from 'naive-ui'
import ServiceControls from './ServiceControls.vue'
import GuardDialog, { askGuard } from './GuardDialog.vue'
import { pt } from './submit-copy.js'
import { ct } from './control-copy.js'
import * as ipc from '../api/ipc.js'
import * as store from '../stores/snapshot.js'

/** `true` while a switch is in flight — the dropdown alone disables. */
const switching = ref(false)

const options = computed(() =>
  store.services.value.map((name) => ({ label: name, value: name })),
)

/** Nothing to switch to: one entry or none. */
const onlyOne = computed(() => store.services.value.length <= 1)

const hasService = computed(() => store.selected.value !== '')

/** Why the control is disabled, shown on hover. */
const disabledReason = computed(() => {
  if (store.busy.value) return store.t('msg.restarting')
  if (!hasService.value) return store.t('state.unknown')
  if (onlyOne.value) return store.t('msg.no.service')
  return ''
})

const disabled = computed(
  () => store.busy.value || !hasService.value || onlyOne.value,
)

/**
 * Ask before switching, when the form has unapplied changes.
 *
 * `dirty` is Rust's semantic verdict, read off the Snapshot. The dropdown's own
 * value is `selected`, so a cancelled question needs no rollback: the box is
 * still showing the service Rust last read.
 */
function requestSwitch(name) {
  if (name === store.selected.value) return
  if (store.dirty.value) {
    askGuard('service', name)
    return
  }
  onSwitch(name, false)
}

/**
 * Switch service. The form being abandoned goes along so Rust can auto-back it
 * up when it has unapplied changes — and only then, which is ticket 11's rule
 * on `Auto backup`: `backup` is only ever true because the user asked for it,
 * and even then Rust stores nothing for a form that is semantically identical
 * to the service.
 */
async function onSwitch(name, backup) {
  switching.value = true
  try {
    await store.run('switch_service', () =>
      ipc.switchService(name, store.snapshot.form, backup),
    )
    // A successful switch refills the form from the new service, so the edit
    // buffer Rust just answered with is the truth — drop ours.
    store.clearForm()
  } finally {
    switching.value = false
  }
}

/** Re-enumerate: one powershell call, so it is an explicit action, not a poll. */
async function onRefresh() {
  await store.run('refresh_services', () => ipc.refreshServices())
}
</script>

<template>
  <div class="svcbar">
    <span class="t-body muted label">{{ store.t('svc.label') }}</span>

    <div class="pick">
      <NSelect
        :value="store.selected.value || null"
        :options="options"
        :disabled="disabled || switching"
        :loading="switching"
        :placeholder="store.t('state.unknown')"
        size="small"
        class="sel"
        @update:value="requestSwitch"
      />
      <NTooltip v-if="disabledReason" :delay="300">
        <template #trigger>
          <span class="why" aria-hidden="true">?</span>
        </template>
        {{ disabledReason }}
      </NTooltip>
    </div>

    <NButton size="small" secondary :disabled="store.busy.value" @click="onRefresh">
      {{ store.t('shell.rescan') }}
    </NButton>

    <div class="spacer" />

    <!-- Ticket 14: start / stop / restart / boot auto-start. -->
    <slot>
      <ServiceControls />
    </slot>

    <!--
      Ticket 17: switching service with unapplied changes asks first, and the
      auto-backup is offered rather than assumed. Cancelling leaves the box on
      the service Rust last read — it is controlled, so there is nothing to
      roll back.
    -->
    <GuardDialog
      kind="service"
      :title="pt('mb.confirm')"
      :message="pt('msg.svc.dirty')"
      :backup-text="pt('guard.backup')"
      :discard-text="pt('guard.discard')"
      :cancel-text="ct('btn.cancel')"
      @backup="(name) => onSwitch(name, true)"
      @discard="(name) => onSwitch(name, false)"
    />
  </div>
</template>

<style scoped>
.svcbar {
  display: flex;
  align-items: center;
  gap: var(--sp-sm);
  min-width: 0;
  flex-wrap: wrap;
}

.label {
  flex: none;
}

.pick {
  display: flex;
  align-items: center;
  gap: var(--sp-xs);
  min-width: 168px;
  max-width: 320px;
}

.sel {
  flex: 1 1 auto;
  min-width: 0;
}

.why {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  flex: none;
  border-radius: 50%;
  border: 1px solid var(--border);
  color: var(--mut);
  font-size: var(--f-micro);
  cursor: help;
}
</style>

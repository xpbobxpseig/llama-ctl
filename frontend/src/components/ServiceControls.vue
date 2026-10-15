<script setup>
/**
 * Start / stop / restart / boot-auto-start (ticket 14).
 *
 * **Rust is authoritative, and these controls never assume otherwise.** Every
 * action here is a command whose answer is a fresh Snapshot; `store.run` folds
 * that answer in, so "did it work" is always what Rust read afterwards. Nothing
 * on this bar flips its own state optimistically: the Start button's disabled
 * state comes from `snapshot.status`, the auto-start switch's position comes
 * from `snapshot.facts.start`, and both are what Rust last said.
 *
 * **The two confirmations are the safety-critical part**, and Python had them
 * for a reason (`apply_auto`, L1989-1996; spec items 44 and 47):
 *
 *   - **restart** interrupts in-flight inference, so it asks first;
 *   - **changing the boot start mode writes to the service**, so it asks first,
 *     and **cancelling writes nothing** — the switch is *controlled*, meaning
 *     it only moves once a new Snapshot says Rust moved it. A cancelled
 *     question leaves it exactly where Rust last put it.
 *
 * Rust does not re-ask: `restart` and `set_start_mode` execute what they are
 * told. So this dialog is the only thing between a click and `sc`.
 *
 * Start/stop are *not* confirmed — `sc start` / `sc stop` are the whole point
 * of the button and Python never confirmed them either.
 */
import { computed, ref } from 'vue'
import { NButton, NSwitch, NTooltip } from 'naive-ui'
import ConfirmDialog from './ConfirmDialog.vue'
import { ct } from './control-copy.js'
import * as ipc from '../api/ipc.js'
import * as store from '../stores/snapshot.js'

const RUNNING = 'RUNNING'
const STOPPED = 'STOPPED'

const state = computed(() => store.status.value.state ?? '')
const running = computed(() => state.value === RUNNING)
const stopped = computed(() => state.value === STOPPED)

const hasService = computed(() => store.selected.value !== '')

/** The boot start mode Rust reports: `auto` / `manual` / `disabled`. */
const startMode = computed(() => store.snapshot.snap?.facts?.start ?? '')

/**
 * The auto-start switch's position. Controlled by the Snapshot, so it cannot
 * drift from what Rust last read — and a cancelled question cannot move it.
 */
const autoStart = computed(() => startMode.value === 'auto')

/**
 * Which question is on screen, `''` for none. One at a time: two overlapping
 * modals would let a user confirm the wrong one.
 */
const asking = ref('')

const askingRestart = computed(() => asking.value === 'restart')
const askingAuto = computed(() => asking.value === 'auto')

/** The mode the auto-start question would write, for the question's own text. */
const pendingMode = computed(() => (autoStart.value ? 'manual' : 'auto'))

const modeLabel = computed(() =>
  startMode.value ? store.t(`boot.${startMode.value}`) : store.t('state.unknown'),
)

/** `true` while a command is in flight — every control derives its state. */
const busy = computed(() => store.busy.value)

const restarting = computed(() => store.busyName.value === 'restart')

/** Disabled reasons, so a greyed control says *why* rather than just being grey. */
const whyStart = computed(() => {
  if (!hasService.value) return store.t('msg.no.service')
  if (busy.value) return ct('msg.restarting')
  if (running.value) return store.t('status.svc', { st: state.value })
  return ''
})
const whyStop = computed(() => {
  if (!hasService.value) return store.t('msg.no.service')
  if (busy.value) return ct('msg.restarting')
  if (stopped.value) return store.t('status.svc', { st: state.value })
  return ''
})
const whyRestart = computed(() => {
  if (!hasService.value) return store.t('msg.no.service')
  if (busy.value) return ct('msg.restarting')
  return ''
})
const whyAuto = computed(() => {
  if (!hasService.value) return store.t('msg.no.service')
  if (busy.value) return ct('msg.restarting')
  if (!startMode.value) return store.t('state.unknown')
  return ''
})

const disabled = {
  start: computed(() => busy.value || !hasService.value || running.value),
  stop: computed(() => busy.value || !hasService.value || stopped.value),
  restart: computed(() => busy.value || !hasService.value),
  auto: computed(() => busy.value || !hasService.value || !startMode.value),
}

// ---- actions ---------------------------------------------------------------

/** `sc start` / `sc stop`. Not confirmed — that is what the button is for. */
async function act(action) {
  await store.run(`service_action`, () => ipc.serviceAction(action))
}

/**
 * Restart: ask, then stream. `restart` takes the form so the health probe hits
 * the host/port *on screen* rather than a stale one, which is what Python read
 * off the widgets before starting its worker (L1934-1938).
 */
function askRestart() {
  if (disabled.restart.value || asking.value) return
  asking.value = 'restart'
}

async function doRestart() {
  asking.value = ''
  // One restart's transcript at a time: the steps are a sequence, and mixing
  // two runs' stop/start/ready lines reads as a different, wrong sequence.
  store.clearLog()
  await store.run('restart', () => ipc.restart(store.values.value))
}

/**
 * Ask before writing the start mode. The switch does **not** move here — only
 * a Snapshot that says Rust moved it does that.
 */
function askAuto() {
  if (disabled.auto.value || asking.value) return
  asking.value = 'auto'
}

async function doAuto() {
  const mode = pendingMode.value
  asking.value = ''
  await store.run('set_start_mode', () => ipc.setStartMode(mode))
}

/** Cancel: drop the question. Nothing was sent, so nothing was written. */
function cancel() {
  asking.value = ''
}
</script>

<template>
  <div class="ctl" role="group" :aria-label="store.t('svc.label')">
    <NTooltip :disabled="!whyStart" :delay="300">
      <template #trigger>
        <NButton
          size="small"
          secondary
          :disabled="disabled.start.value"
          :data-action="'start'"
          @click="act('start')"
        >
          {{ store.t('btn.start') }}
        </NButton>
      </template>
      {{ whyStart }}
    </NTooltip>

    <NTooltip :disabled="!whyStop" :delay="300">
      <template #trigger>
        <NButton
          size="small"
          secondary
          type="error"
          :disabled="disabled.stop.value"
          :data-action="'stop'"
          @click="act('stop')"
        >
          {{ store.t('btn.stop') }}
        </NButton>
      </template>
      {{ whyStop }}
    </NTooltip>

    <NTooltip :disabled="!whyRestart" :delay="300">
      <template #trigger>
        <NButton
          size="small"
          secondary
          :loading="restarting"
          :disabled="disabled.restart.value"
          :data-action="'restart'"
          @click="askRestart"
        >
          {{ store.t('btn.restart') }}
        </NButton>
      </template>
      {{ whyRestart }}
    </NTooltip>

    <span class="sep" aria-hidden="true" />

    <NTooltip :disabled="!whyAuto" :delay="300">
      <template #trigger>
        <span class="auto" :data-action="'autostart'">
          <NSwitch
            size="small"
            :value="autoStart"
            :disabled="disabled.auto.value"
            :aria-label="store.t('boot.label')"
            @update:value="askAuto"
          />
          <span class="auto-label t-small" :class="{ 'is-on': autoStart }">
            {{ store.t('boot.label') }}
          </span>
        </span>
      </template>
      {{ whyAuto }}
    </NTooltip>

    <!--
      The switch's own position is the truth; the mode word spells out which of
      Rust's three modes is actually set (auto / manual / disabled), which a
      two-state switch cannot show on its own.
    -->
    <span class="t-micro muted mode">{{ modeLabel }}</span>

    <!-- Restart: stops the service, so it is asked, not assumed. -->
    <ConfirmDialog
      kind="restart"
      :show="askingRestart"
      :title="ct('mb.doublecheck')"
      :message="ct('msg.restart.confirm', { s: store.selected.value })"
      :confirm-text="store.t('btn.restart')"
      :cancel-text="ct('btn.cancel')"
      tone="warning"
      @confirm="doRestart"
      @cancel="cancel"
    />

    <!-- Boot auto-start: writes to the service, so it is asked too. -->
    <ConfirmDialog
      kind="autostart"
      :show="askingAuto"
      :title="ct('mb.doublecheck')"
      :message="ct('msg.auto.confirm', { m: store.t(`boot.${pendingMode}`) })"
      :confirm-text="ct('btn.confirm')"
      :cancel-text="ct('btn.cancel')"
      @confirm="doAuto"
      @cancel="cancel"
    />
  </div>
</template>

<style scoped>
.ctl {
  display: flex;
  align-items: center;
  gap: var(--sp-sm);
  flex-wrap: wrap;
  min-width: 0;
}

.sep {
  width: 1px;
  height: 16px;
  flex: none;
  background: var(--border);
}

.auto {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-xs);
}

.auto-label {
  color: var(--mut);
  white-space: nowrap;
  /* State change, immediate: the label goes accent when auto-start is on. */
  transition: color var(--m-hover-in) var(--m-ease-out);
}

.auto-label.is-on {
  color: var(--txt);
}

.mode {
  white-space: nowrap;
}
</style>

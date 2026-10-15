<script setup>
/**
 * The submit side: presets, Apply and Revert (ticket 17).
 *
 * One row, in the Python build's own order (`llama_ctl_gui.py` L1105-1131):
 * 参数预设 · the unapplied-changes hint · the editable preset box · 保存 / 删除,
 * then 还原 / 应用更改 on the right.
 *
 * **Two things here are decided by Rust and only by Rust**, and the split is
 * the whole point of the ticket (CONTEXT.md):
 *
 *   1. *Unapplied changes* is `Snapshot.facts.dirty` — a **semantic** verdict
 *      (`!semantically_equal(form, AppParameters)`). It drives the hint and
 *      gates Revert. A local edit that Rust has not re-read cannot light it:
 *      computing it here is precisely the class of bug this rewrite removes.
 *   2. *Did the write-back change anything* is `ApplyResult.written` — a
 *      **textual** verdict, because Apply is also the normalisation pass. So
 *      the「无需改动」notice is what Rust reported, not what the screen guessed.
 *
 * Presets never write to the service: load fills the form and nothing else
 * (`load_preset` reads only), save with an existing name is a no-op Rust
 * reports as `false`, and delete asks first. Only Apply writes.
 */
import { computed, ref, watch } from 'vue'
import { NButton, NAutoComplete, NTooltip } from 'naive-ui'
import ConfirmDialog from './ConfirmDialog.vue'
import GuardDialog, { askGuard } from './GuardDialog.vue'
import ParamDiff from './ParamDiff.vue'
import { pt, autoBackupName } from './submit-copy.js'
import { ct } from './control-copy.js'
import * as ipc from '../api/ipc.js'
import * as store from '../stores/snapshot.js'

/** Which question this row is asking: `''` | `'apply'` | `'preset-del'`. */
const asking = ref('')

/** The line under the row: what the last command answered. */
const note = ref('')

/**
 * The preset name in the box.
 *
 * It is a *name* and nothing more — never a claim about where the form's values
 * came from. That claim is Rust's (`Snapshot.preset_loaded`), and confusing the
 * two is the Python bug where a freshly auto-selected dropdown entry let one
 * Apply overwrite a preset the user had never touched.
 */
const name = ref(store.snapshot.snap?.preset_loaded ?? '')

const busy = computed(() => store.busy.value)
const hasService = computed(() => store.selected.value !== '')

/** Rust's verdict; the only thing the hint and Revert are allowed to read. */
const dirty = computed(() => store.dirty.value)

const presets = computed(() => store.snapshot.snap?.presets ?? [])
const loaded = computed(() => store.snapshot.snap?.preset_loaded ?? '')
const running = computed(() => store.status.value.state === 'RUNNING')

/** The values Rust parsed out of the service, for the old side of the diff. */
const held = computed(() => store.snapshot.snap?.values ?? {})
/** The service's own `AppParameters`, verbatim. */
const heldText = computed(() => store.snapshot.snap?.facts?.app_params ?? '')
const extras = computed(() => store.snapshot.snap?.extras ?? [])

const blocked = computed(() => busy.value || !hasService.value)
const typed = computed(() => name.value.trim())
const known = computed(() => presets.value.includes(typed.value))

const canDelete = computed(() => !blocked.value && known.value)
const canSave = computed(() => !blocked.value && typed.value !== '' && !known.value)

/** Why 保存 is dead, so a grey button says something. */
const whySave = computed(() => {
  if (!hasService.value) return store.t('msg.no.service')
  if (busy.value) return ct('msg.restarting')
  if (typed.value === '') return pt('msg.preset.name')
  if (known.value) return pt('msg.preset.exists', { n: typed.value })
  return ''
})

/** Why 删除 is dead. */
const whyDelete = computed(() => {
  if (blocked.value) return whySave.value && !known.value ? whySave.value : ''
  if (!known.value) return pt('msg.preset.name')
  return ''
})

/** Why 还原 is dead — the ticket's own rule: only live with unapplied changes. */
const whyRevert = computed(() => {
  if (!hasService.value) return store.t('msg.no.service')
  if (busy.value) return ct('msg.restarting')
  if (!dirty.value) return pt('msg.nochange')
  return ''
})

/** Why 应用更改 is dead. */
const whyApply = computed(() => {
  if (!hasService.value) return store.t('msg.no.service')
  if (busy.value) return ct('msg.restarting')
  return ''
})

/** The Apply question's own first line: a RUNNING service needs a restart. */
const applyIntro = computed(() =>
  running.value
    ? pt('apply.intro.run', { s: store.selected.value })
    : pt('apply.intro.stop', { s: store.selected.value }),
)

// Keep the box in step with what Rust says the form came from. A preset that
// Rust has loaded is the only case where the box may be filled for the user.
watch(loaded, (v) => {
  if (v && v !== name.value) name.value = v
})


// ---- presets ---------------------------------------------------------------

/** Typing: the box holds a name. Nothing is saved or loaded by typing alone. */
function onName(next) {
  name.value = next ?? ''
}

/**
 * Choosing an entry: fill the form (**reads only** — the service is untouched),
 * asking first when there are unapplied changes.
 */
async function onPick(target) {
  if (!target) return
  if (target === loaded.value) {
    name.value = target
    return
  }
  if (dirty.value) {
    askGuard('preset', target)
    return
  }
  await load(target)
}

/**
 * Load a preset into the form.
 *
 * `load_preset` writes nothing to the service — that is Rust's rule 1, and the
 * reason loading a preset can never reconfigure a running service by accident.
 *
 * **Known contract gap** (needs a Rust-side fix, out of scope for this
 * ticket): `commands::snapshot::snapshot` always fills `Snapshot.values` from
 * `AppParameters`, and `editing` is only used for `dirty` and for the
 * health-probe host/port. So the reply carries the *service's* parsed values,
 * not the preset's — there is no command that returns a preset's values. Until
 * Rust gains one (`Snapshot.values` = the form when `editing` is supplied, or a
 * `preset_values` field), the form is refilled with the service's values and
 * the row shows the loaded name from Rust's own `preset_loaded`.
 */
async function load(target) {
  const snap = await store.run('load_preset', () => ipc.loadPreset(target))
  if (!snap) return
  name.value = target
  // Rust's reply describes the service; show those values, and re-read so the
  // hint is computed from exactly what is on screen rather than from the
  // preset Rust compared against.
  store.clearForm()
  await store.refresh()
}

/**
 * Store the form under the name in the box.
 *
 * An existing name is a **no-op**: Rust returns `false` and overwrites nothing.
 * `fromButton` distinguishes a click (say why nothing happened) from Enter on an
 * already-known name (stay quiet — that is just the box committing).
 */
async function save(fromButton) {
  const n = typed.value
  if (!n || known.value) {
    if (fromButton) note.value = n ? pt('msg.preset.exists', { n }) : pt('msg.preset.name')
    return
  }
  const stored = await store.run('save_preset', () => ipc.savePreset(n, store.values.value))
  if (stored === null) {
    note.value = ''
    return
  }
  await store.refresh()
  // `false` is Rust's answer for "that name already exists": say so rather
  // than letting a silent no-op look like a save.
  note.value = stored ? pt('msg.preset.saved', { n }) : pt('msg.preset.exists', { n })
}

/** Deleting asks first — it destroys a named set of values. */
function askDelete() {
  if (!canDelete.value || asking.value !== '') return
  asking.value = 'preset-del'
}

async function doDelete() {
  const n = typed.value
  asking.value = ''
  const gone = await store.run('delete_preset', () => ipc.deletePreset(n))
  if (gone === null) return
  await store.refresh()
  if (typed.value === n) name.value = ''
  note.value = gone ? pt('msg.preset.deleted', { n }) : pt('msg.preset.noload', { n })
}

/** Auto-backup first, then load. Rust still decides whether it stores anything. */
async function backupThenLoad(target) {
  const backup = autoBackupName()
  await store.run('save_preset', () => ipc.savePreset(backup, store.values.value))
  await load(target)
}

// ---- apply / revert --------------------------------------------------------

/** Apply: show the comparison, then ask. The button is the first click. */
function askApply() {
  if (blocked.value || asking.value !== '') return
  note.value = ''
  asking.value = 'apply'
}

async function doApply() {
  asking.value = ''
  const values = store.values.value
  const extra = extras.value
  const done = await store.run('apply_changes', () => ipc.applyChanges(values, extra), (res) => {
    store.setSnapshot(res.snapshot)
    store.clearForm()
    // Rust's own verdict. `written === false` is the **textual** comparison:
    // the rebuilt text already equalled what the service holds.
    note.value = res.written
      ? res.needs_restart
        ? pt('msg.apply.needs_restart')
        : pt('msg.written')
      : pt('msg.nochange')
    // A preset the form came from is refreshed by Rust, and only that one.
    if (res.preset_synced) note.value += ` ${pt('msg.apply.synced', { n: res.preset_synced })}`
  })
  if (done === null) note.value = ''
}

/**
 * Revert: throw the edits away and read the service again. Never writes
 * (`revert` invalidates the fact cache first, so the answer is what the system
 * holds now). Gated by Rust's `dirty`, so it can never be a no-op in disguise.
 */
async function doRevert() {
  const snap = await store.run('revert', () => ipc.revert())
  if (!snap) return
  store.clearForm()
  note.value = ''
}
</script>

<template>
  <section
    class="card presets"
    :data-preset-bar="''"
    :data-dirty="String(dirty)"
    :aria-label="store.t('card.presets')"
  >
    <header class="head">
      <h2 class="t-section title">{{ store.t('card.presets') }}</h2>

      <!--
        The hint. It is Rust's semantic verdict and nothing else: a local edit
        that Rust has not re-read leaves it off.
      -->
      <span v-if="dirty" class="hint t-small" data-dirty-hint>
        {{ store.t('status.dirty') }}
      </span>

      <span v-if="loaded" class="loaded t-micro muted wrap-anywhere">
        {{ pt('preset.loaded', { n: loaded }) }}
      </span>

      <div class="spacer" />

      <span
        v-if="note"
        class="note t-small wrap-anywhere selectable"
        data-note
        aria-live="polite"
      >
        {{ note }}
      </span>
    </header>

    <div class="row">
      <!--
        One control for both jobs, as Python's CTkComboBox did: typing enters a
        name (Enter or 保存 stores it), choosing an entry loads it. The `keyup`
        sits on a wrapper because that is where the event lands from the input.
      -->
      <div class="pick" @keyup.enter="save(false)">
        <NAutoComplete
          :value="name"
          :options="presets"
          :disabled="blocked"
          :placeholder="pt('preset.placeholder')"
          :aria-label="store.t('card.presets')"
          size="small"
          class="box"
          data-preset-name
          @update:value="onName"
          @select="onPick"
        />
      </div>

      <NTooltip :disabled="!whySave" :delay="300">
        <template #trigger>
          <NButton
            size="small"
            secondary
            :disabled="!canSave"
            :data-action="'preset-save'"
            @click="save(true)"
          >
            {{ pt('btn.save') }}
          </NButton>
        </template>
        {{ whySave }}
      </NTooltip>

      <NTooltip :disabled="!whyDelete" :delay="300">
        <template #trigger>
          <NButton
            size="small"
            secondary
            type="error"
            :disabled="!canDelete"
            :data-action="'preset-del'"
            @click="askDelete"
          >
            {{ store.t('preset.delete') }}
          </NButton>
        </template>
        {{ whyDelete }}
      </NTooltip>

      <div class="spacer" />

      <NTooltip :disabled="!whyRevert" :delay="300">
        <template #trigger>
          <NButton
            size="small"
            secondary
            :disabled="!dirty || blocked"
            :data-action="'revert'"
            @click="doRevert"
          >
            {{ store.t('btn.revert') }}
          </NButton>
        </template>
        {{ whyRevert }}
      </NTooltip>

      <NTooltip :disabled="!whyApply" :delay="300">
        <template #trigger>
          <NButton
            size="small"
            type="primary"
            :loading="busy"
            :disabled="blocked"
            :data-action="'apply'"
            @click="askApply"
          >
            {{ store.t('btn.apply2') }}
          </NButton>
        </template>
        {{ whyApply }}
      </NTooltip>
    </div>

    <!-- Apply: the comparison *is* the second confirmation. -->
    <ConfirmDialog
      kind="apply"
      :show="asking === 'apply'"
      :title="ct('mb.doublecheck')"
      :confirm-text="store.t('btn.apply2')"
      :cancel-text="ct('btn.cancel')"
      tone="warning"
      @confirm="doApply"
      @cancel="asking = ''"
    >
      <p class="intro t-body wrap-anywhere">{{ applyIntro }}</p>
      <ParamDiff :old="held" :next="store.values.value" :old-text="heldText" />
    </ConfirmDialog>

    <!-- Delete: destroys a named preset, so it asks. -->
    <ConfirmDialog
      kind="preset-del"
      :show="asking === 'preset-del'"
      :title="pt('mb.confirm')"
      :message="pt('msg.preset.del', { n: typed })"
      :confirm-text="store.t('preset.delete')"
      :cancel-text="ct('btn.cancel')"
      tone="warning"
      @confirm="doDelete"
      @cancel="asking = ''"
    />

    <!-- Switching preset with unapplied changes: ask, and offer the backup. -->
    <GuardDialog
      kind="preset"
      :title="pt('mb.confirm')"
      :message="pt('msg.preset.dirty')"
      :backup-text="pt('guard.backup')"
      :discard-text="pt('guard.discard')"
      :cancel-text="ct('btn.cancel')"
      @backup="backupThenLoad"
      @discard="load"
    />

  </section>
</template>

<style scoped>
.presets {
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
  flex-wrap: wrap;
}

.title {
  margin: 0;
  flex: none;
}

/*
 * The hint is a state, not a decoration: it appears in accent-warning the
 * moment Rust says the form differs, and the row never reserves space for it
 * (a permanently empty slot would teach the eye to ignore it).
 */
.hint {
  color: var(--org);
  white-space: nowrap;
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

.loaded {
  white-space: nowrap;
}


.note {
  color: var(--mut);
  text-align: right;
}

.row {
  display: flex;
  align-items: center;
  gap: var(--sp-sm);
  flex-wrap: wrap;
  min-width: 0;
}

/* The box grows into the spare width and shrinks before the buttons do. */
.pick {
  flex: 1 1 240px;
  min-width: 0;
  max-width: 320px;
}

.box {
  min-width: 0;
}

.intro {
  margin: 0 0 var(--sp-sm);
}
</style>

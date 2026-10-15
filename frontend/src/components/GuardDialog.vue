<script>
/**
 * Which "you have unapplied changes" question is on screen.
 *
 * Module scope, not component scope, and that is the point: two *different*
 * owners ask it — the service dropdown (ticket 12's bar) and the preset box —
 * and only one question may ever be open. Two overlapping modals would let a
 * user answer the wrong one.
 *
 * It is deliberately dumb: it records *what* is being asked and nothing else.
 * Whether the switch then happens, and whether an auto-backup is stored, is
 * answered by Rust (`switch_service` / `save_preset`), never by this module.
 */
import { ref } from 'vue'

/** `null`, or `{ kind, target }`. */
export const guard = ref(null)

/** Ask. A question already on screen wins: the first one is the live one. */
export function askGuard(kind, target) {
  if (!guard.value) guard.value = { kind, target }
}

/** Drop the question without acting on it. */
export function closeGuard() {
  guard.value = null
}
</script>

<script setup>
/**
 * The "switching with unapplied changes" confirmation (ticket 17).
 *
 * Three answers, not two, because the destructive part is *losing the edits*
 * and the app's answer to that is an Auto backup — a preset with a timestamped
 * name (CONTEXT.md), which is a different thing from the file Backup an update
 * makes. Offering "continue without a backup" as well as "cancel" is what makes
 * it an offer rather than a toll.
 *
 * Built on the same NaiveUI `preset="dialog"` as `ConfirmDialog`, so it
 * inherits the `Dialog` overrides (12px radius, 15px bold title) instead of
 * inventing a second modal look.
 */
import { computed } from 'vue'
import { NModal } from 'naive-ui'
import { pt } from './submit-copy.js'

const props = defineProps({
  /** Which owner this instance answers for, e.g. `'service'` / `'preset'`. */
  kind: { type: String, required: true },
  message: { type: String, default: '' },
  title: { type: String, default: '' },
  backupText: { type: String, default: '' },
  discardText: { type: String, default: '' },
  cancelText: { type: String, default: '' },
})

const emit = defineEmits(['backup', 'discard', 'cancel'])

const show = computed(() => guard.value?.kind === props.kind)
const target = computed(() => guard.value?.target ?? '')

/**
 * Answer. The question is closed *before* the event, so an owner that opens a
 * new question from its handler is not fighting a stale one.
 */
function answer(which) {
  const t = target.value
  closeGuard()
  emit(which, t)
}

/** Escape and the mask land here, and mean the same thing as Cancel. */
function onShow(next) {
  if (!next) answer('cancel')
}
</script>

<template>
  <NModal
    :show="show"
    preset="dialog"
    class="guard"
    :data-confirm-kind="kind"
    :title="title"
    :positive-text="backupText"
    :negative-text="cancelText"
    :positive-button-props="{ size: 'small', type: 'warning' }"
    :negative-button-props="{ size: 'small', quaternary: true }"
    @update:show="onShow"
    @positive-click="answer('backup')"
    @negative-click="answer('cancel')"
  >
    <p class="q t-body wrap-anywhere">{{ message }}</p>
    <p class="t-small muted wrap-anywhere">{{ pt('guard.target', { t: target }) }}</p>
    <!--
      The third way out: continue, and let the edits go. It is a text button
      under the question rather than a third dialog button, because it is the
      answer that *loses* something and must not look like the default.
    -->
    <button
      type="button"
      class="alt t-small"
      :data-guard-discard="kind"
      @click="answer('discard')"
    >
      {{ discardText }}
    </button>
  </NModal>
</template>

<style scoped>
.guard {
  white-space: normal;
}

.q {
  margin: 0 0 var(--sp-xs);
}

.alt {
  margin-top: var(--sp-sm);
  padding: 2px var(--sp-sm);
  font-family: var(--font-ui);
  font-size: var(--f-small);
  color: var(--mut);
  background: transparent;
  border: 1px solid var(--border);
  border-radius: var(--r-ctl);
  cursor: pointer;
  transition:
    color var(--m-hover-in) var(--m-ease-out),
    border-color var(--m-hover-out) var(--m-ease-decay);
}

.alt:hover {
  color: var(--acc);
  border-color: var(--acc);
  transition-duration: var(--m-hover-in);
}

.alt:active {
  color: var(--acch);
}
</style>

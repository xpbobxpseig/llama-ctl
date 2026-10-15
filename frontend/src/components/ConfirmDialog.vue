<script setup>
import { NModal } from 'naive-ui'
/**
 * The one confirmation dialog (ticket 14).
 *
 * Two actions in this app must not happen on a single click: **restart** (it
 * drops in-flight inference requests) and **changing the boot start mode**
 * (it writes to the service). Rust does not ask again — `restart` and
 * `set_start_mode` execute what they are told — so this dialog *is* the
 * confirmation, and it is the only thing standing between a click and `sc`.
 *
 * That makes one rule load-bearing: **cancelling writes nothing.** The dialog
 * never mutates anything itself; it reports the user's answer and the parent
 * decides. Closing it by any route (Cancel, Escape, the mask) reports `cancel`
 * and nothing else happens.
 *
 * Built on NaiveUI's `preset="dialog"` so it inherits the `Dialog` overrides in
 * `src/theme/index.js` (12px radius, 15px bold title) instead of inventing a
 * second modal look.
 */
defineProps({
  /** Controlled visibility — the parent owns when a question is on screen. */
  show: { type: Boolean, default: false },
  /** The question, already translated by the caller. */
  message: { type: String, default: '' },
  /** `mb.doublecheck` — "二次确认", i.e. this is the second check, not the first. */
  title: { type: String, default: '' },
  confirmText: { type: String, default: '' },
  cancelText: { type: String, default: '' },
  /**
   * `'warning'` paints the confirming button orange (a stop/start the user can
   * feel); `'default'` leaves it neutral (a preference write).
   */
  tone: { type: String, default: 'default' },
  /** What is being confirmed, for tests and for the smoke run. */
  kind: { type: String, default: '' },
})

const emit = defineEmits(['confirm', 'cancel'])

/** Escape and the mask land here, and mean the same thing as Cancel. */
function onShow(next) {
  if (!next) emit('cancel')
}
</script>

<template>
  <NModal
    :show="show"
    preset="dialog"
    class="confirm"
    :data-confirm-kind="kind"
    :title="title"
    :content="message"
    :positive-text="confirmText"
    :negative-text="cancelText"
    :positive-button-props="{
      size: 'small',
      type: tone === 'warning' ? 'warning' : 'default',
    }"
    :negative-button-props="{ size: 'small', quaternary: true }"
    @update:show="onShow"
    @positive-click="emit('confirm')"
    @negative-click="emit('cancel')"
  />
</template>

<style scoped>
/* The dialog renders in a teleport, so nothing here can be `scoped` to it;
   the visuals come from the `Dialog` theme overrides. This rule only keeps
   the body text wrappable — a service name must never be cut off. */
.confirm {
  white-space: normal;
}
</style>

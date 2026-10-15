<script setup>
/**
 * The update's two questions, rendered **once for the whole window** (ticket 15).
 *
 * The settings page owns the controls, but the startup check runs while the
 * user is looking at the console — so the prompt cannot live inside the
 * settings page, or a startup「发现新版本」would be invisible. Both questions
 * are driven by the update store, so whichever screen the user is on sees them.
 *
 * **Neither question does anything on its own.** The notes'「立即更新」opens the
 * second question, and only the second question's confirmation calls
 * `install_update`. That is the ticket's requirement: an update is confirmed
 * twice, and the second confirmation is the one that names where the old files
 * go.
 *
 * Python asked the same two (`_show_changelog` then `upd.install.confirm`).
 */
import { computed } from 'vue'
import ReleaseNotes from './ReleaseNotes.vue'
import ConfirmDialog from './ConfirmDialog.vue'
import * as store from '../stores/snapshot.js'
import { ut } from './update-copy.js'
import * as update from '../stores/update.js'

/**
 * The second question: Rust's `upd.install.confirm` (stop the service, replace
 * the binaries, back the old files up to `{d}`) plus the two local lines that
 * spell out the backup directory and that it is Rust's timestamped one.
 */
const confirmMessage = computed(() => {
  const backup = update.backupPreview.value
  const ask = store.t('upd.install.confirm', {
    s: store.selected.value,
    d: backup || '—',
  })
  return [ask, `${ut('upd.backup.where')} ${backup || '—'}`, ut('upd.backup.preview')].join(
    '\n\n',
  )
})

/** The notes'「立即更新」: open the second question. Nothing runs yet. */
function onAsk() {
  update.askInstall()
}

/** The confirmation's answer: only now does anything get downloaded. */
function onInstall() {
  update.beginInstall()
}

function onCancel() {
  update.cancelInstall()
}

function onCloseNotes() {
  update.openNotes(false)
}
</script>

<template>
  <!-- First question: the changelog, read before the user decides. -->
  <ReleaseNotes
    :show="update.notesOpen.value"
    @install="onAsk"
    @close="onCloseNotes"
  />

  <!-- Second question: the backup directory. This is the only thing standing
       between a click and a download. -->
  <ConfirmDialog
    kind="update"
    :show="update.confirmOpen.value"
    :title="store.t('upd.install')"
    :message="confirmMessage"
    :confirm-text="store.t('upd.install')"
    :cancel-text="ut('btn.cancel')"
    tone="warning"
    @confirm="onInstall"
    @cancel="onCancel"
  />
</template>

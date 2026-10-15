<script setup>
/**
 * The settings view: language, appearance, motion, and the official-update
 * section (ticket 15).
 *
 * Every control writes through `save_settings` and is answered with a fresh
 * Snapshot, so "the preference is saved" is something Rust read back, not
 * something the frontend assumed. A language change comes back with the new
 * string table, which is why the whole UI re-renders from it and no copy is
 * duplicated here.
 *
 * The update section is ticket 15's own component, dropped into the slot at the
 * bottom: it owns the variant selector, the two confirmations and the streamed
 * progress, and it reads its channel list from the same Snapshot.
 */
import { computed, ref } from 'vue'
import { NSelect, NSwitch, NButton, NAlert } from 'naive-ui'
import UpdateSection from '../components/UpdateSection.vue'
import * as store from '../stores/snapshot.js'
import * as theme from '../stores/theme.js'

/** The last failure, if any: shown inline rather than as a modal. */
const failed = ref('')

const languages = [
  { label: '中文', value: 'zh' },
  { label: 'English', value: 'en' },
]

const appearances = computed(() => [
  { label: store.t('appear.system'), value: 'system' },
  { label: store.t('appear.light'), value: 'light' },
  { label: store.t('appear.dark'), value: 'dark' },
])

const language = computed(() => store.settings.value?.language ?? 'zh')
const appearance = computed(() => store.settings.value?.appearance ?? 'system')
const motion = computed(() => store.settings.value?.motion_enabled ?? true)

/** Which appearance is actually in effect, for the note under the control. */
const resolved = computed(() =>
  theme.mode.value === 'dark' ? store.t('appear.dark') : store.t('appear.light'),
)

async function setLanguage(next) {
  failed.value = (await theme.setLanguage(next)) ? '' : store.error.value
}

async function setAppearance(next) {
  failed.value = (await theme.setAppearance(next)) ? '' : store.error.value
}

async function setMotion(next) {
  failed.value = (await theme.setMotion(next)) ? '' : store.error.value
}
</script>

<template>
  <div class="view">
    <section class="card enter enter-1">
      <h2 class="t-section title">{{ store.t('settings.title') }}</h2>

      <div class="field">
        <label class="t-body" for="set-lang">{{ store.t('settings.lang') }}</label>
        <NSelect
          id="set-lang"
          :value="language"
          :options="languages"
          :disabled="store.busy.value"
          size="small"
          class="ctl"
          @update:value="setLanguage"
        />
      </div>

      <div class="field">
        <label class="t-body" for="set-appear">{{ store.t('settings.appear') }}</label>
        <NSelect
          id="set-appear"
          :value="appearance"
          :options="appearances"
          :disabled="store.busy.value"
          size="small"
          class="ctl"
          @update:value="setAppearance"
        />
        <span class="t-micro muted note">{{ resolved }}</span>
      </div>

      <div class="field">
        <label class="t-body" for="set-motion">{{ store.t('settings.motion') }}</label>
        <NSwitch
          id="set-motion"
          :value="motion"
          :disabled="store.busy.value"
          @update:value="setMotion"
        />
      </div>

      <p class="t-small muted note">{{ store.t('settings.note') }}</p>

      <NAlert v-if="failed" type="error" :show-icon="false" class="fail">
        {{ failed }}
      </NAlert>
    </section>

    <!--
      Ticket 15: the official-update section — variant, check, the two
      confirmations, and the streamed progress. The slot stays, so a test can
      swap it out.
    -->
    <div class="enter enter-2">
      <slot>
        <UpdateSection />
      </slot>
    </div>

    <div class="row">
      <div class="spacer" />
      <NButton size="small" secondary @click="$emit('close')">
        {{ store.t('settings.close') }}
      </NButton>
    </div>
  </div>
</template>

<style scoped>
.view {
  display: flex;
  flex-direction: column;
  gap: var(--sp-md);
  min-width: 0;
}

.title {
  margin: 0 0 var(--sp-md);
}

/*
 * Two stable tracks — a label column and a control column — so a long label
 * wraps in its own track instead of pushing the control around.
 */
.field {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 200px;
  align-items: center;
  gap: var(--sp-sm) var(--sp-md);
  padding: var(--sp-sm) 0;
  border-top: 1px solid var(--border);
}

.field:first-of-type {
  border-top: none;
}

.ctl {
  min-width: 0;
}

.note {
  grid-column: 1 / -1;
  margin: 0;
}

.fail {
  margin-top: var(--sp-sm);
}
</style>

<script setup>
/**
 * The release notes the user reads **before deciding** (ticket 15).
 *
 * Python's `_show_changelog` (L2884-2946) is the model: the prompt line, the
 * changelog, the asset list, then the two choices. One thing is deliberately
 * different here — the sheet has **no install button of its own**. It offers
 * 「立即更新」, which opens the *second* confirmation (backup directory), and
 * 「关闭」, which dismisses. The ticket requires a second confirmation before
 * anything is downloaded, so a single click here can never start one.
 *
 * The changelog body is Rust's: `Release.body`. Official nightlies ship no
 * release notes, so Rust's `upd.no.changelog` — which says so plainly, and
 * names the tag and build — is what shows instead of an empty box. That is the
 * fix Python made in the comment at L2915-2918: an always-empty body read as
 * "the changelog failed to load", so the honest copy replaced it.
 *
 * Nothing here reaches the network. The release's `html_url` is **not** shown as
 * a link and the asset URLs are never touched: ADR-0001, and the download is
 * Rust's job. Only asset *names* are rendered.
 */
import { computed } from 'vue'
import { NModal, NCard, NButton, NScrollbar, NTag } from 'naive-ui'
import { ut } from './update-copy.js'
import * as store from '../stores/snapshot.js'
import * as update from '../stores/update.js'

const props = defineProps({
  /** Controlled by the store: only a checked release can open this. */
  show: { type: Boolean, default: false },
})

const emit = defineEmits(['install', 'close'])

/** The release on screen, `null` when there is none. */
const release = computed(() => update.release.value)

/** Rust's own title: `upd.title` = 发现新版本：{t}. */
const title = computed(() => {
  const rel = release.value
  return rel ? store.t('upd.title', { t: rel.tag }) : ''
})

/** Rust's prompt: 「官方最新 b{n}（当前 b{c}）。是否查看更新日志并更新？」 */
const prompt = computed(() => {
  const rel = release.value
  if (!rel) return ''
  const cur = update.installed.value
  return store.t('upd.prompt', {
    n: rel.build ?? rel.tag,
    c: cur === null || cur === undefined ? '?' : `b${cur}`,
  })
})

/**
 * The changelog body.
 *
 * Nightlies have no `body`, so the fallback is Rust's own `upd.no.changelog`
 * filled with the tag and build — never a blank pane, and never a made-up
 * summary.
 */
const notes = computed(() => {
  const rel = release.value
  if (!rel) return ''
  if (rel.body && rel.body.trim()) return rel.body
  return store.t('upd.no.changelog', { t: rel.tag, b: rel.build ?? '?' })
})
/** The asset *names* Rust will download — no URLs, ever. */
const assets = computed(() => (release.value?.assets ?? []).map((a) => a.name))

/** `true` when Rust already said the installed build covers this release. */
const upToDate = computed(() => update.upToDate.value)

/** `upd.assets` = 下载内容：{a} — Rust's copy, with the names joined. */
const assetLine = computed(() =>
  assets.value.length ? store.t('upd.assets', { a: assets.value.join(', ') }) : '',
)
</script>

<template>
  <!--
    `data-notes-kind` is the smoke run's handle: it asserts the sheet is what is
    on screen, and that the install it offers is only an *ask*.
  -->
  <NModal
    :show="show"
    class="notes"
    data-notes-kind="changelog"
    :data-notes-tag="release?.tag ?? ''"
    @update:show="(next) => !next && emit('close')"
  >
    <NCard
      class="sheet"
      size="small"
      :title="title"
      :bordered="false"
      role="dialog"
      aria-modal="true"
    >
      <template #header-extra>
        <NTag v-if="upToDate" size="small" type="success" :bordered="false">
          {{ store.t('upd.uptodate') }}
        </NTag>
      </template>

      <p class="t-body prompt wrap-anywhere">{{ prompt }}</p>

      <h3 class="t-group muted notes-head">{{ store.t('upd.changelog') }}</h3>
      <NScrollbar class="body scroll">
        <pre class="t-mono-sm notes selectable wrap-anywhere">{{ notes }}</pre>
      </NScrollbar>
      <p v-if="assetLine" class="t-small muted assets wrap-anywhere">{{ assetLine }}</p>


      <div class="actions">
        <span class="spacer" />
        <NButton size="small" secondary data-notes-action="close" @click="emit('close')">
          {{ store.t('settings.close') }}
        </NButton>
        <!--
          「立即更新」asks; it does not install. The second confirmation (the
          backup directory) is what actually starts the download.
        -->
        <NButton
          size="small"
          type="primary"
          data-notes-action="install"
          :disabled="!release"
          @click="emit('install')"
        >
          {{ store.t('upd.install') }}
        </NButton>
      </div>
      <p class="t-micro muted hint wrap-anywhere">{{ ut('upd.channel.hint') }}</p>
    </NCard>
  </NModal>
</template>

<style scoped>
.sheet {
  /* Cards are 12px; the sheet's own width is capped so long release notes wrap
     instead of stretching across a wide window. */
  width: min(680px, 92vw);
  border-radius: var(--r-card);
}

.prompt {
  margin: 0 0 var(--sp-md);
}

.notes-head {
  margin: 0 0 var(--sp-xs);
}

.body {
  /* A fixed line box: a 200-line changelog scrolls inside the sheet instead of
     pushing the two choices off it. */
  max-height: 240px;
  padding: var(--sp-sm) var(--sp-md);
  border: 1px solid var(--border);
  border-radius: var(--r-ctl);
  background: var(--field);
}

.notes {
  margin: 0;
  /* Release notes are pre-formatted: keep Rust's line breaks, and let a long
     URL-less token wrap rather than clip. */
  white-space: pre-wrap;
}

.assets {
  margin: var(--sp-md) 0 0;
}

.actions {
  display: flex;
  align-items: center;
  gap: var(--sp-sm);
  margin-top: var(--sp-lg);
}

.spacer {
  flex: 1 1 auto;
  min-width: 0;
}

.hint {
  margin: var(--sp-sm) 0 0;
}
</style>

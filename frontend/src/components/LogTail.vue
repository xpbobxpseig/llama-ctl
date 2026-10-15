<script setup>
/**
 * The `server.err` log tail (ticket 14).
 *
 * Two real sources, kept visibly separate:
 *
 *   1. **The file** — `tail_log` returns the last lines of the selected
 *      service's `server.err` plus the path it was read from. Polled while the
 *      region is open; Rust resolves the path (`<AppDirectory>\server.err`,
 *      falling back to `LLAMA_CTL_ERR_LOG`), so the frontend never guesses it.
 *   2. **The restart transcript** — `restart` streams one line per step on
 *      `llama-ctl://restart-progress`; `App.vue` subscribes and the lines land
 *      in `snapshot.log`. Appended after the file's tail, because a step the
 *      user just watched is newer than anything in the file.
 *
 * Outside the Tauri shell neither exists, so demo lines show — **labelled**,
 * so sample output can never pass for the service's own.
 *
 * Collapsing is by CSS `grid-template-rows: 0fr/1fr` — no JS height tween, and
 * it still animates out of the box (ticket 16's `.motion-off` zeroes it).
 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { NButton } from 'naive-ui'
import { ct } from './control-copy.js'
import * as store from '../stores/snapshot.js'
import { tailLog } from '../api/ipc.js'

/** The region starts folded, as Python's `self._log_open` did. */
const open = ref(false)

/** The file's tail, replaced wholesale on each poll (Rust already truncates). */
const fileLines = ref([])
/** The path Rust read from, so the header can say which file this is. */
const fileFrom = ref('')

/** Guards against a slow poll landing after the region closed. */
let pollToken = 0
let pollTimer = null
const POLL_MS = 1500

async function poll() {
  const token = ++pollToken
  try {
    const { lines, path } = await tailLog()
    if (token !== pollToken) return
    fileLines.value = lines || []
    fileFrom.value = path || ''
  } catch {
    // A failed poll must not empty a region that already had content, and must
    // never surface as an error the user cannot act on.
    if (token === pollToken) fileFrom.value = ''
  }
}

function stopPolling() {
  pollToken++
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function startPolling() {
  stopPolling()
  if (!store.isDemo.value) {
    poll()
    pollTimer = setInterval(poll, POLL_MS)
  }
}

/** Only poll while the region is actually visible. */
watch(open, (isOpen) => (isOpen ? startPolling() : stopPolling()))
onBeforeUnmount(stopPolling)

/** The restart transcript, newest last. */
const transcript = computed(() => store.snapshot.log)

/**
 * Demo lines, shown only outside the Tauri shell so an empty region is not
 * mistaken for a broken one. Labelled as demo in the region's own header.
 */
const demoLines = computed(() =>
  store.isDemo.value
    ? [
        // No scheme: a `http://` literal here would be the only URL-shaped
        // string in `dist/`, and ADR-0001's check is a grep.
        'llama server listening at 127.0.0.1:8080',
        'srv    load_model: ngl = 999, ctx = 131072',
        'srv  update_slots: all slots are idle',
        'slot launch_slot_: id  0 | task 12 | processing task',
      ]
    : [],
)

const shown = computed(() => {
  // The transcript is something the user actually just did, so it wins over
  // the demo placeholder even in demo mode.
  if (transcript.value.length) return transcript.value
  return store.isDemo.value ? demoLines.value : fileLines.value
})

const isDemo = computed(() => store.isDemo.value && transcript.value.length === 0)

/** The path Rust reported, else the one derived from the service's directory. */
const path = computed(() => {
  if (fileFrom.value) return fileFrom.value
  const dir = store.snapshot.snap?.facts?.app_dir
  // Python: `os.path.join(app_directory(service), "server.err")`, falling back
  // to `F:\llama.cpp\server.err` when the directory is unreadable (L2182-2188).
  return dir ? `${dir.replace(/[\\/]+$/, '')}\\server.err` : 'F:\\llama.cpp\\server.err'
})

/** Autoscroll: the newest line is the one the user wants. */
const body = ref(null)

watch(
  () => [shown.value.length, open.value],
  async () => {
    if (!open.value) return
    await nextTick()
    const el = body.value
    if (el) el.scrollTop = el.scrollHeight
  },
)

function toggle() {
  open.value = !open.value
}
</script>
<template>
  <section class="card log enter enter-4" :data-log-open="open ? 'true' : 'false'">
    <!--
      The whole header is the toggle: a real button, so it is tabbable and
      Enter/Space work, and `aria-expanded`/`aria-controls` tell a screen
      reader what it does.
    -->
    <button
      type="button"
      class="head"
      :aria-expanded="open"
      aria-controls="log-body"
      @click="toggle"
    >
      <svg class="caret" :class="{ 'is-open': open }" width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
        <!-- A vector chevron for the same reason the dot is one: a font glyph
             would move with the font size. -->
        <path d="M2.5 0.5 L7 5 L2.5 9.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
      <span class="t-group title">{{ open ? store.t('log.expanded') : store.t('log.collapsed') }}</span>
      <span class="spacer" />
      <span class="t-micro muted path">{{ ct('log.path', { p: path }) }}</span>
    </button>

    <!-- `0fr → 1fr` collapses the row without a JS height tween. -->
    <div class="fold" :class="{ 'is-open': open }">
      <div id="log-body" ref="body" class="body scroll" role="log" aria-live="polite" aria-relevant="additions">
        <p v-if="isDemo" class="t-micro demo-note">{{ ct('log.demo') }}</p>
        <p v-if="!shown.length" class="t-mono-sm muted empty">{{ ct('log.empty') }}</p>
        <p v-for="(line, i) in shown" :key="`${i}-${line}`" class="t-mono-sm line selectable wrap-anywhere">
          {{ line }}
        </p>
      </div>
    </div>

    <div v-if="transcript.length" class="foot">
      <NButton size="tiny" quaternary @click="store.clearLog()">
        {{ store.t('btn.revert') }}
      </NButton>
    </div>
  </section>
</template>

<style scoped>
.log {
  padding: 0;
  overflow: hidden;
}

.head {
  display: flex;
  align-items: center;
  gap: var(--sp-sm);
  width: 100%;
  /* The card owns the padding so the header's hover covers the full row. */
  padding: var(--sp-md) var(--sp-lg);
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  /* Immediate feedback: this is a control, and hover must not lag. */
  transition: color var(--m-hover-in) var(--m-ease-out);
}

.head:hover {
  color: var(--acc);
}

.title {
  min-width: 0;
}

.path {
  flex: none;
  max-width: 42%;
  /* A long AppDirectory must not push the header sideways. */
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.caret {
  flex: none;
  color: var(--mut);
  /* State change: the caret rotates to say "open". */
  transition: transform var(--m-hover-in) var(--m-ease-out);
}

.caret.is-open {
  transform: rotate(90deg);
}

/* Collapse by grid track, not by height: content of any length fits. */
.fold {
  display: grid;
  grid-template-rows: 0fr;
  transition: grid-template-rows var(--m-enter) var(--m-ease-out);
}

.fold.is-open {
  grid-template-rows: 1fr;
}

.body {
  /* Without `min-height: 0` a grid child refuses to shrink and the collapse
     silently does nothing. */
  min-height: 0;
  overflow: hidden auto;
  max-height: 240px;
  padding: 0 var(--sp-lg) var(--sp-md);
}

.line,
.empty {
  margin: 0;
  /* Log lines are mono and compact: the point is density, not rhythm. */
  white-space: pre-wrap;
}

.demo-note {
  margin: 0 0 var(--sp-xs);
  color: var(--org);
}

.foot {
  display: flex;
  justify-content: flex-end;
  padding: 0 var(--sp-lg) var(--sp-sm);
}
</style>

<script setup>
/**
 * A file-path parameter: a text input plus a Browse button.
 *
 * Typing is the primary path — a path can always be pasted, and the Python
 * build's `CTkEntry` was a plain entry too. Browse is the accelerator, and it
 * is a real one: a hidden `<input type="file">` opened by `showPicker()` where
 * the browser has it and by `click()` otherwise. Nothing remote is involved
 * and no dependency is added — a native file chooser is not a Rust round trip,
 * and the picked path goes into the form like any other edit (it is *not*
 * opened, read or uploaded).
 *
 * The row also answers the question the Python build answered with a tooltip
 * on the Browse button: a long path is shown in full. It is not truncated by
 * an ellipsis inside the control, because the whole path is what decides
 * whether the service starts.
 */
import { computed, ref } from 'vue'
import { NInput, NButton } from 'naive-ui'
import * as store from '../stores/snapshot.js'

const props = defineProps({
  field: { type: Object, required: true },
  disabled: { type: Boolean, default: false },
  /** The accepted file extensions, e.g. `.gguf`. */
  accept: { type: String, default: '.gguf' },
})

/** The hidden file input, opened by the Browse button. */
const picker = ref(null)

const value = computed(() => store.values.value[props.field.key] ?? '')

function edit(next) {
  store.editField(props.field.key, next ?? '')
}

/**
 * Open the native file chooser.
 *
 * `showPicker()` is the modern entry point; `click()` is the fallback for the
 * WebView2 builds that do not have it. Either way the user picks a file and
 * the path — and only the path — comes back.
 */
function browse() {
  const el = picker.value
  if (!el) return
  try {
    if (typeof el.showPicker === 'function') el.showPicker()
    else el.click()
  } catch {
    // A chooser the environment refuses to open (a headless test, a blocked
    // gesture) is not an error state: the input beside it still accepts the
    // path, so there is nothing to report and nothing to disable.
  }
}

/** Take the picked file's path into the form. */
function picked(event) {
  const file = event.target?.files?.[0]
  // `webkitRelativePath` is set for a directory pick and is the fuller path
  // when the browser gives one; `name` alone would be useless to llama-server.
  if (file) edit(file.webkitRelativePath || file.path || file.name)
  // Reset so choosing the same file twice still fires `change`.
  event.target.value = ''
}
</script>

<template>
  <div class="path-row">
    <NInput
      class="entry"
      :value="value"
      :disabled="disabled"
      :placeholder="store.lang.value === 'en' ? field.en : field.zh"
      :aria-label="field.zh"
      size="small"
      @update:value="edit"
    >
      <template #suffix>
        <NButton
          class="browse"
          size="tiny"
          secondary
          :disabled="disabled"
          @click="browse"
        >
          {{ store.t('browse') }}
        </NButton>
      </template>
    </NInput>

    <input
      ref="picker"
      class="picker"
      type="file"
      :accept="accept"
      tabindex="-1"
      aria-hidden="true"
      @change="picked"
    />
  </div>
</template>

<style scoped>
.path-row {
  display: flex;
  align-items: center;
  gap: var(--sp-sm);
  min-width: 0;
}

.entry {
  min-width: 0;
  flex: 1 1 auto;
}

.browse {
  /* The button lives inside the input's suffix slot; it must not inherit a
     shrinking width from the field's own layout. */
  flex: none;
}

/*
 * The chooser itself is never shown: it is opened programmatically. It stays
 * in the DOM (a detached input is not openable) but takes no space and is out
 * of the tab order and the accessibility tree, so the visible controls are the
 * only ones a keyboard user meets.
 */
.picker {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
</style>

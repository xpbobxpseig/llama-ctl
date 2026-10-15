<script setup>
/**
 * The「?」affordance: one button per parameter, opening the Chinese
 * explanation of what the parameter does.
 *
 * A popover rather than a tooltip, because the explanations run to four
 * sentences and a tooltip is for a word. It is a `button`, so it is reachable
 * by Tab and dismissed by Escape without any extra wiring, and it carries
 * `aria-label` — the only text inside it is「?」, which says nothing about
 * which parameter it belongs to.
 *
 * The trigger is a hover *and* click popover (`trigger="hover"` would leave a
 * keyboard user no way in), and the body is plain DOM inside NaiveUI's
 * `NPopover`, so it reads the same type scale as the rest of the card.
 */
import { NPopover } from 'naive-ui'
import { useHelpTip } from '../motion/index.js'

// The「?」timings live in one place (src/motion/index.js): 300 ms hover before
// it appears, 200 ms fade in, 800 ms fade out that shortens the further the
// pointer gets. Click still opens it, so a deliberate click is never gated by
// the hover threshold.
const tip = useHelpTip()
defineProps({
  /** The explanation, already resolved. */
  text: { type: String, default: '' },
  /** The parameter's label, for the accessible name. */
  label: { type: String, default: '' },
  /** Option explanation lines: `[[value, text], ...]`. */
  options: { type: Array, default: () => [] },
})
</script>

<template>
  <NPopover
    class="help"
    placement="top-start"
    :width="360"
    :trigger="manual"
    :show="tip.shown.value"
    :show-arrow="true"
  >
    <template #trigger>
      <button
        type="button"
        class="q"
        :aria-label="`${label} — 说明`"
        :style="tip.fade.value"
        @mouseenter="tip.enter"
        @mouseleave="tip.leave"
        @focus="tip.focus"
        @blur="tip.blur"
        @click="tip.enter"
      >?</button>
    </template>

    <div class="body">
      <p class="t-body text selectable">{{ text }}</p>
      <dl v-if="options.length" class="opts">
        <div v-for="[value, line] in options" :key="value" class="opt">
          <dt class="t-mono">{{ value }}</dt>
          <dd class="t-small selectable">{{ line }}</dd>
        </div>
      </dl>
    </div>
  </NPopover>
</template>

<style scoped>
/*
 * The Python build drew a 26px circle with a 1px border. Same shape here, on
 * the 4px rhythm (26 is not a multiple of 4, and the 2px difference is what
 * makes it read as a chip next to a 28px control — the radius token is used
 * for the pill so it cannot drift).
 */
.q {
  width: 24px;
  height: 24px;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-ui);
  font-size: var(--f-small);
  line-height: 1;
  color: var(--mut);
  background: transparent;
  border: 1px solid var(--border);
  border-radius: 999px;
  cursor: help;
  /* Immediate in, slower decay out: this is a press, not a decoration. */
  transition:
    color var(--m-hover-in) var(--m-ease-out),
    border-color var(--m-hover-in) var(--m-ease-out),
    background-color var(--m-hover-out) var(--m-ease-decay);
}

.q:hover {
  color: var(--acc);
  border-color: var(--acc);
  background: var(--tip);
  transition-duration: var(--m-hover-in);
}

.q:active {
  color: var(--acch);
  border-color: var(--acch);
}

.body {
  display: flex;
  flex-direction: column;
  gap: var(--sp-sm);
  /* A 360px popover of Chinese text must wrap, never overflow the viewport. */
  max-width: 100%;
}

.text {
  margin: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.opts {
  display: flex;
  flex-direction: column;
  gap: var(--sp-xs);
  margin: 0;
  padding-top: var(--sp-sm);
  border-top: 1px solid var(--border);
}

.opt {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: var(--sp-sm);
  align-items: baseline;
  /* Two tracks stay two tracks: a long explanation wraps inside its own. */
  min-width: 0;
}

.opt dt {
  margin: 0;
  color: var(--acc);
  white-space: nowrap;
}

.opt dd {
  margin: 0;
  color: var(--mut);
  min-width: 0;
  overflow-wrap: anywhere;
}
</style>

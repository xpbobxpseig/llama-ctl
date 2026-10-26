<script setup>
/**
 * 自写下拉 · 原生 select 的弹出层画不出高级感（圆角、间距、悬停、勾选
 * 都不可控），所以触发钮 + listbox 都自己画。
 *
 * - 触发钮占 `.val.sel` 的盒模型（26px 高、行内值胶囊），`bare` 变体是
 *   维护页渠道那种嵌在正文里的小下拉（12px、无边框）。
 * - 弹出层 `position: fixed`，坐标取自按钮的 getBoundingClientRect，
 *   右缘越界时向左收。菜单里 `↑↓` 移动、`Enter/Space` 确认、`Esc` 关闭、
 *   `Home/End` 跳到两端。
 * - 同一时间只允许一个弹出层：模块级的 openOwner 让后开者先关前一个。
 * - 选项的 `title` 原样保留——那是 Rust 的参数详解，悬停仍能看。
 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

// 模板是「按钮 + Teleport」两个根节点，Vue 不做自动 attrs 透传——
// 不显式接管的话，外面传的 class（市场页的 hubdd/mindd 宽度）会静默丢掉。
defineOptions({ inheritAttrs: false })

const props = defineProps({
  /** 当前值（字符串；空串是一个合法选项） */
  modelValue: { type: String, default: '' },
  /** `[{ value, label, title? }]` */
  options: { type: Array, default: () => [] },
  ariaLabel: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  bare: { type: Boolean, default: false },
})

const emit = defineEmits(['change'])

const open = ref(false)
const active = ref(-1)
const btnEl = ref(null)
const popEl = ref(null)
const place = ref({})

const selectedIndex = computed(() => props.options.findIndex((o) => o.value === props.modelValue))
const currentLabel = computed(() => props.options[selectedIndex.value]?.label ?? props.modelValue)

function position() {
  const r = btnEl.value?.getBoundingClientRect?.()
  if (!r) return
  // 祖先带 zoom（字体接口的界面缩放）时，fixed 弹层写的 CSS 值会被再乘
  // zoom，所以先除回去，弹层才贴在按钮正下方。
  const z = Number(getComputedStyle(btnEl.value).zoom) || 1
  const width = Math.max(r.width / z, props.bare ? 150 : 180)
  const view = (window.innerWidth || 9999) / z
  const left = Math.max(8, Math.min(r.left / z, view - width - 10))
  place.value = { left: `${left}px`, top: `${r.bottom / z + 5}px`, minWidth: `${width}px` }
}

async function openMenu() {
  if (props.disabled || open.value) return
  openOwner?.close()
  open.value = true
  active.value = selectedIndex.value
  openOwner = { close: () => close() }
  await nextTick()
  position()
  popEl.value?.focus?.()
}

function close(refocus = false) {
  open.value = false
  if (refocus) btnEl.value?.focus?.()
}

function pick(value) {
  emit('change', value)
  close(true)
}

function onTriggerKey(e) {
  if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(e.key)) {
    e.preventDefault()
    openMenu()
  }
}

function onPopKey(e) {
  const n = props.options.length
  if (e.key === 'Escape') {
    e.preventDefault()
    close(true)
  } else if (e.key === 'ArrowDown') {
    e.preventDefault()
    active.value = n ? (active.value + 1) % n : -1
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    active.value = n ? (active.value - 1 + n) % n : -1
  } else if (e.key === 'Home') {
    e.preventDefault()
    active.value = 0
  } else if (e.key === 'End') {
    e.preventDefault()
    active.value = n - 1
  } else if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault()
    if (active.value >= 0) pick(props.options[active.value].value)
  }
}

/** 点到弹出层与触发钮之外 → 收起；滚轮滚动 → 收起（fixed 菜单不跟随滚动）。 */
function onDocDown(e) {
  if (!e.target.closest?.('.dd-pop') && !e.target.closest?.('.selbtn')) close()
}
function onDocScroll() {
  close()
}

watch(open, (on) => {
  if (typeof document === 'undefined') return
  if (on) {
    document.addEventListener('mousedown', onDocDown)
    document.addEventListener('wheel', onDocScroll, { passive: true })
  } else {
    document.removeEventListener('mousedown', onDocDown)
    document.removeEventListener('wheel', onDocScroll)
  }
})

onBeforeUnmount(() => {
  if (typeof document === 'undefined') return
  document.removeEventListener('mousedown', onDocDown)
  document.removeEventListener('wheel', onDocScroll)
})
</script>

<script>
/** 当前打开的下拉；模块级，保证同一时间只有一个弹出层。 */
let openOwner = null
</script>

<template>
  <button
    ref="btnEl"
    v-bind="$attrs"
    class="selbtn"
    :class="{ bare }"
    type="button"
    role="combobox"
    :aria-label="ariaLabel"
    :aria-expanded="String(open)"
    aria-haspopup="listbox"
    :disabled="disabled"
    :data-value="modelValue"
    @click="open ? close() : openMenu()"
    @keydown="onTriggerKey"
  >
    <span class="sv">{{ currentLabel }}</span>
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M6 8l4 4 4-4" /></svg>
  </button>

  <!-- 传送到 .d5 根部的挂点：留在行内会被带 transform 的祖先（视图入场
       动画）劫持 fixed 定位的包含块，坐标随滚动漂移——即「界面错乱」。
       v-if 放在 Teleport 上：挂点在应用根部，Dd 挂载时它还没建好。 -->
  <Teleport v-if="open" to=".d5 .pop-layer">
    <div
      ref="popEl"
      class="dd-pop"
      :class="{ bare }"
      role="listbox"
      :aria-label="ariaLabel"
      tabindex="-1"
      :style="place"
      @keydown="onPopKey"
    >
      <button
        v-for="(opt, i) in options"
        :key="opt.value"
        type="button"
        role="option"
        :aria-selected="String(opt.value === modelValue)"
        :data-value="opt.value"
        :title="opt.title || ''"
        :class="{ lit: i === active }"
        @click="pick(opt.value)"
        @mousemove="active = i"
      >
        <span class="ol">{{ opt.label }}</span>
        <svg v-if="opt.value === modelValue" class="ok" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 10.5l3.5 3.5 7.5-8" /></svg>
      </button>
    </div>
  </Teleport>
</template>

<script setup>
/**
 * 参数页 · 与 v5 稿 1:1 的行式表单。
 *
 * 稿中这一页由脚本生成：`.section` 是分组标题本身（不是容器），行是 `.row`，
 * 四种单元格分别是 `.val.num` / `.val.sel` / `.sw` / `.val.path`。这里的 DOM
 * 与稿逐项对应；只在“编辑中”才把按钮换成输入框（稿未画编辑态，属交互必需）。
 *
 * 数据来自 Snapshot：元数据在 field-copy.js（与 Rust fields.rs 对齐），值是
 * store.values；改动判定按“与服务值文本不同”，与服务端的语义判定无关。
 */
import { computed, ref } from 'vue'
import * as store from '../stores/snapshot.js'
import { FIELDS, GROUP_ORDER, GROUP_LABEL, OPTIONS, optionHelp } from '../api/field-copy.js'
import Dd from './Dd.vue'

const props = defineProps({
  /** 侧栏「已改」筛选：只留改动行。 */
  onlyChanged: { type: Boolean, default: false },
})

/** 正在原地编辑的字段 key。 */
const editing = ref('')

/**
 * 稿里分组名比 Rust 的短（模型 / 上下文 / 并发）。稿是视觉基准，
 * 所以这里做一次展示层收窄，不改 Rust 的字符串。
 */
const SHORT = {
  '模型与视觉': ['模型', 'Model'],
  '上下文与显存': ['上下文', 'Context'],
  '并发与吞吐': ['并发', 'Concurrency'],
}

const groups = computed(() =>
  GROUP_ORDER.map((group) => {
    const entry = GROUP_LABEL[group] ?? { zh: group, en: group }
    const full = store.lang.value === 'en' ? entry.en : entry.zh
    const short = SHORT[entry.zh]
    return {
      group,
      label: short ? (store.lang.value === 'en' ? short[1] : short[0]) : full,
      fields: FIELDS.filter((f) => f.group === group),
    }
  }).filter((g) => g.fields.length > 0),
)

const svcValues = computed(() => store.snapshot.snap?.values ?? {})

/** 稿里只显示人类名，命令行 flag 放在 title 上。 */
function nameOf(field) {
  const label = store.lang.value === 'en' ? field.en || field.zh : field.zh
  const m = label.match(/^(.*?)\s*\(([^()]*)\)\s*$/)
  return m ? m[1] : label
}

function flagOf(field) {
  const label = store.lang.value === 'en' ? field.en || field.zh : field.zh
  const m = label.match(/^(.*?)\s*\(([^()]*)\)\s*$/)
  return m ? m[2] : ''
}

function valueOf(field) {
  return store.values.value[field.key] ?? ''
}

function changed(field) {
  return String(valueOf(field)) !== String(svcValues.value[field.key] ?? '')
}

function hidden(field) {
  return props.onlyChanged && !changed(field)
}

function unitOf(field) {
  const u = field.unit ?? {}
  return store.lang.value === 'en' ? u.en ?? '' : u.zh ?? ''
}

function decimals(step) {
  return (String(step).split('.')[1] ?? '').length
}

function num(field) {
  const n = Number(valueOf(field))
  if (!Number.isFinite(n)) return field.def
  return Math.min(field.max, Math.max(field.min, n))
}

/** 稿里数值按最短形式显示：整数不留小数，小数最多两位。 */
function readout(field) {
  const n = Number(num(field).toFixed(decimals(field.step)))
  return Number.isInteger(n) ? String(n) : String(Number(n.toFixed(2)))
}

function step(field, dir) {
  const next = Math.min(field.max, Math.max(field.min, num(field) + dir * field.step))
  store.editField(field.key, String(Number(next.toFixed(decimals(field.step)))))
}

function commit(field, event) {
  const raw = String(event.target.value ?? '').trim()
  if (raw !== '') store.editField(field.key, raw)
  editing.value = ''
}

function optionsOf(field) {
  return OPTIONS[field.key] ?? []
}

/** Dd 的选项：值、显示名、悬停说明（Rust 的参数详解）。 */
function comboOptions(field) {
  return optionsOf(field).map((value) => ({
    value,
    label: optionLabel(value),
    title: optionTitle(field, value),
  }))
}

function optionLabel(value) {
  if (value !== '') return value
  return store.lang.value === 'en' ? '(empty)' : '（空）'
}

function optionTitle(field, value) {
  return optionHelp(field.key, value, store.snapshot.snap?.strings) || ''
}
</script>

<template>
  <template v-for="g in groups" :key="g.group">
    <div class="section" :data-group="g.group">{{ g.label }}</div>

    <div
      v-for="field in g.fields"
      :key="field.key"
      class="row"
      :class="{ changed: changed(field), hidden: hidden(field) }"
      :data-row="field.key"
    >
      <span class="name">
        <span class="dot" aria-hidden="true"></span>
        <span class="txt" :title="flagOf(field) ? `${nameOf(field)} (${flagOf(field)})` : nameOf(field)">{{ nameOf(field) }}</span>
      </span>

      <!-- 数值：− 值 +
           稿中是 span.n > span.numv；编辑时才换成输入框。 -->
      <span v-if="field.kind === 'slider'" class="val num">
        <button class="step" type="button" aria-label="减少" :disabled="store.busy.value" @click="step(field, -1)">
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M5 10h10" /></svg>
        </button>
        <span class="n">
          <input
            v-if="editing === field.key"
            class="inline"
            type="text"
            inputmode="decimal"
            :value="valueOf(field)"
            @keydown.enter="commit(field, $event)"
            @keydown.esc="editing = ''"
            @blur="commit(field, $event)"
            v-focus
          />
          <template v-else>
            <button class="numv" type="button" :disabled="store.busy.value" @click="editing = field.key">{{ readout(field) }}</button>
            <span v-if="unitOf(field)" class="unit">{{ unitOf(field) }}</span>
          </template>
        </span>
        <button class="step" type="button" aria-label="增加" :disabled="store.busy.value" @click="step(field, 1)">
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M10 5v10M5 10h10" /></svg>
        </button>
      </span>

      <!-- 枚举：自绘下拉（Dd），触发钮占 .val.sel 的盒模型 -->
      <span v-else-if="field.kind === 'combo'" class="val sel">
        <Dd
          :model-value="valueOf(field)"
          :options="comboOptions(field)"
          :aria-label="nameOf(field)"
          :disabled="store.busy.value"
          @change="store.editField(field.key, $event)"
        />
      </span>

      <!-- 开关 -->
      <button
        v-else-if="field.kind === 'check'"
        class="sw"
        type="button"
        :aria-pressed="String(valueOf(field) === '1')"
        :aria-label="nameOf(field)"
        :disabled="store.busy.value"
        @click="store.editField(field.key, valueOf(field) === '1' ? '' : '1')"
      ><i></i></button>

      <!-- 路径 / 文本：静止态是稿中的按钮，点开才变输入框 -->
      <template v-else>
        <input
          v-if="editing === field.key"
          class="tinput"
          type="text"
          :value="valueOf(field)"
          :disabled="store.busy.value"
          :aria-label="nameOf(field)"
          spellcheck="false"
          @keydown.enter="commit(field, $event)"
          @keydown.esc="editing = ''"
          @blur="commit(field, $event)"
          v-focus
        />
        <button
          v-else
          class="val path"
          type="button"
          :title="valueOf(field) || '未设置'"
          :disabled="store.busy.value"
          @click="editing = field.key"
        ><span class="p">{{ valueOf(field) || '—' }}</span></button>
      </template>
    </div>
  </template>
</template>

<script>
export default {
  directives: {
    focus: {
      mounted(el) {
        el.focus()
        el.select?.()
      },
    },
  },
}
</script>

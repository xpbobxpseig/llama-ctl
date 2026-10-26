<script setup>
/**
 * 设置页 · 与稿 1:1：界面（语言 / 外观 / 动效 / 半透明材质）、
 * 字体（五档缩放滑条 / 界面字体 / 等宽字体，全部下拉）、更新（启动时检查）。
 *
 * 三个偏好写进既有 store（`theme.js` / `update.js`），不做乐观更新：
 * 值来自 Snapshot 的 settings，Rust 落盘后下一次快照才让控件动。
 * 字体三项走 `font.js`（localStorage，呈现层偏好），缩放是五档步进滑条。
 */
import { computed, ref, watch } from 'vue'
import * as store from '../stores/snapshot.js'
import * as theme from '../stores/theme.js'
import * as update from '../stores/update.js'
import * as ipc from '../api/ipc.js'
import * as font from '../design/font.js'
import { t } from './copy.js'
import Dd from './Dd.vue'

const lang = computed(() => store.lang.value)
const tr = (key, fields) => t(key, lang.value, fields)

const appearance = computed(() => theme.appearance.value)
const motion = computed(() => theme.motion.value)
const micaOn = computed(() => theme.mica.value)
const checkOnStart = computed(() => update.autoOnStartup.value)

const langOptions = computed(() => [
  { value: 'zh', label: '中文' },
  { value: 'en', label: 'English' },
])

const appearanceOptions = computed(() => [
  { value: 'system', label: tr('system') },
  { value: 'light', label: tr('light') },
  { value: 'dark', label: tr('dark') },
])

// ---- 字体（font.js 接口的设置页入口） ------------------------------------

/** Windows 自带、值得进下拉的族；'' = 默认栈。 */
const uiFontOptions = computed(() => [
  { value: '', label: `${tr('fontDefault')}（Segoe UI Variable）` },
  { value: 'Segoe UI Variable Text', label: 'Segoe UI Variable' },
  { value: 'Microsoft YaHei UI', label: '微软雅黑' },
  { value: 'DengXian', label: '等线' },
  { value: 'SimSun', label: '宋体' },
  { value: 'KaiTi', label: '楷体' },
])

const monoFontOptions = computed(() => [
  { value: '', label: `${tr('fontDefault')}（Cascadia Code）` },
  { value: 'Cascadia Code', label: 'Cascadia Code' },
  { value: 'Cascadia Mono', label: 'Cascadia Mono' },
  { value: 'Consolas', label: 'Consolas' },
  { value: 'Courier New', label: 'Courier New' },
  { value: 'NSimSun', label: '新宋体' },
])

// ---- 市场（下载根目录 / 访问令牌）：改动在 change 时经 save_settings 落盘 ----

const marketRoot = ref('')
const hfToken = ref('')
const msToken = ref('')

watch(
  () => store.settings.value,
  (s) => {
    if (!s || marketRoot.value) return
    marketRoot.value = s.market_download_root || 'F:\AI_Model'
    hfToken.value = s.market_hf_token || ''
    msToken.value = s.market_ms_token || ''
  },
  { immediate: true },
)

async function saveMarket() {
  const s = store.settings.value
  if (!s) return
  await store.run('save_settings', () =>
    ipc.saveSettings({
      ...s,
      market_download_root: marketRoot.value.trim() || 'F:\AI_Model',
      market_hf_token: hfToken.value.trim(),
      market_ms_token: msToken.value.trim(),
    }),
  )
}

const steps = font.SCALE_STEPS
const scaleIdx = computed(() => {
  const i = steps.findIndex((s) => s.value === font.state.scale)
  return i < 0 ? steps.findIndex((s) => s.value === 'normal') : i
})
const stopPct = (i) => `${(i / (steps.length - 1)) * 100}%`

function onScaleStop(i) {
  const s = steps[Math.min(steps.length - 1, Math.max(0, i))]
  if (s) font.setScale(s.value)
}

/** 点轨道按最近档落位；档位圆点自己 stop 冒泡。 */
function onSliderClick(e) {
  const rect = e.currentTarget.getBoundingClientRect()
  const ratio = rect.width ? (e.clientX - rect.left) / rect.width : 0
  onScaleStop(Math.round(ratio * (steps.length - 1)))
}

function onScaleKey(e) {
  if (e.key === 'ArrowRight' || e.key === 'ArrowUp') {
    e.preventDefault()
    onScaleStop(scaleIdx.value + 1)
  } else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') {
    e.preventDefault()
    onScaleStop(scaleIdx.value - 1)
  }
}

function onLanguage(value) {
  theme.setLanguage(value)
}

function onAppearance(value) {
  theme.setAppearance(value)
}
</script>

<template>
  <div class="section">{{ tr('ui') }}</div>

  <div class="lrow">
    <span class="lname">{{ tr('lang') }}</span>
    <span class="r">
      <span class="val sel">
        <Dd :model-value="lang" :options="langOptions" :aria-label="tr('lang')" @change="onLanguage" />
      </span>
    </span>
  </div>

  <div class="lrow">
    <span class="lname">{{ tr('appearance') }}</span>
    <span class="r">
      <span class="val sel">
        <Dd :model-value="appearance" :options="appearanceOptions" :aria-label="tr('appearance')" @change="onAppearance" />
      </span>
    </span>
  </div>

  <div class="lrow">
    <span class="lname">{{ tr('motion') }}</span>
    <span class="r">
      <button
        class="sw"
        type="button"
        :aria-pressed="String(motion)"
        :aria-label="tr('motion')"
        @click="theme.setMotion(!motion)"
      ><i></i></button>
    </span>
  </div>

  <div class="lrow">
    <span class="lname">{{ tr('mica') }}<span class="lsub">{{ tr('micaHint') }}</span></span>
    <span class="r">
      <button
        class="sw"
        type="button"
        :aria-pressed="String(micaOn)"
        :aria-label="tr('mica')"
        @click="theme.setMica(!micaOn)"
      ><i></i></button>
    </span>
  </div>

  <div class="section">{{ tr('font') }}</div>

  <div class="lrow">
    <span class="lname">{{ tr('uiScale') }}</span>
    <span class="r">
      <div
        class="stepslider"
        role="slider"
        tabindex="0"
        :aria-label="tr('uiScale')"
        :aria-valuemin="0"
        :aria-valuemax="steps.length - 1"
        :aria-valuenow="scaleIdx"
        :aria-valuetext="steps[scaleIdx]?.value"
        @click="onSliderClick"
        @keydown="onScaleKey"
      >
        <span class="track" aria-hidden="true"></span>
        <span class="fill" :style="{ width: stopPct(scaleIdx) }" aria-hidden="true"></span>
        <button
          v-for="(s, i) in steps"
          :key="s.value"
          class="stop"
          :class="{ on: i <= scaleIdx }"
          :style="{ left: stopPct(i) }"
          type="button"
          :tabindex="-1"
          :aria-label="s.value"
          @click.stop="onScaleStop(i)"
        ></button>
      </div>
    </span>
  </div>

  <div class="lrow">
    <span class="lname">{{ tr('uiFont') }}</span>
    <span class="r">
      <span class="val sel">
        <Dd :model-value="font.state.ui" :options="uiFontOptions" :aria-label="tr('uiFont')" @change="font.setUIFamily($event)" />
      </span>
    </span>
  </div>

  <div class="lrow">
    <span class="lname">{{ tr('monoFont') }}</span>
    <span class="r">
      <span class="val sel">
        <Dd :model-value="font.state.mono" :options="monoFontOptions" :aria-label="tr('monoFont')" @change="font.setMonoFamily($event)" />
      </span>
    </span>
  </div>

  <div class="section">{{ tr('updates') }}</div>
  <div class="lrow">
    <span class="lname">{{ tr('checkOnStart') }}</span>
    <span class="r">
      <button
        class="sw"
        type="button"
        :aria-pressed="String(checkOnStart)"
        :aria-label="tr('checkOnStart')"
        @click="update.setAutoOnStartup(!checkOnStart)"
      ><i></i></button>
    </span>
  </div>

  <div class="section">{{ tr('marketSec') }}</div>
  <div class="lrow">
    <span class="lname">{{ tr('marketRoot') }}</span>
    <span class="r"><input
      v-model="marketRoot"
      class="nameinput"
      type="text"
      spellcheck="false"
      @change="saveMarket"
    /></span>
  </div>
  <div class="lrow">
    <span class="lname">{{ tr('marketHfToken') }}</span>
    <span class="r"><input
      v-model="hfToken"
      class="nameinput"
      type="text"
      spellcheck="false"
      placeholder="hf_…"
      @change="saveMarket"
    /></span>
  </div>
  <div class="lrow">
    <span class="lname">{{ tr('marketMsToken') }}</span>
    <span class="r"><input
      v-model="msToken"
      class="nameinput"
      type="text"
      spellcheck="false"
      @change="saveMarket"
    /></span>
  </div>
</template>

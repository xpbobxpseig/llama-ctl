<script setup>
/**
 * 关于页 · 拉马管家的身份页。
 *
 * 内容骨架参照常见「关于」弹窗（标识 / 版本 / 技术栈 / 快捷入口 / 署名），
 * 样式只用稿中令牌：居中 hero、带复制的版本行、静音徽章、2×2 操作区。
 *
 * llama.cpp 构建号来自最近一次检查（update store）；没检查过就退回探活
 * 明细里的 b 号——与服务状态同一个来源，不另猜。外链走 opener 插件，
 * 由 Rust 打系统浏览器（ADR-0001：渲染进程自己不开网络）。
 */
import { computed, onBeforeUnmount, ref } from 'vue'
import * as store from '../stores/snapshot.js'
import * as update from '../stores/update.js'
import { openUrl } from '@tauri-apps/plugin-opener'
import { t } from './copy.js'
import pkg from '../../package.json'

const emit = defineEmits(['license', 'params', 'check-updates'])

const lang = computed(() => store.lang.value)
const tr = (key, fields) => t(key, lang.value, fields)

/** 版本单源：frontend/package.json（改版只动一处）。 */
const VERSION = pkg.version

const llamaBuild = computed(() => {
  if (update.installed.value !== null && update.installed.value !== undefined) {
    return `b${update.installed.value}`
  }
  const m = /b(\d+)/.exec(String(store.status.value.detail ?? ''))
  return m ? `b${m[1]}` : '—'
})

const appDir = computed(() => String(store.snapshot.snap?.facts?.app_dir ?? ''))

const stack = ['Tauri 2', 'Vue 3', 'Rust']

/** 复制成功的按钮亮一瞬「已复制」；失败就安静地无反馈。 */
const copied = ref('')
let copiedTimer = null

async function copy(text, key) {
  try {
    if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(text)
    else throw new Error('async clipboard unavailable')
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    try { document.execCommand('copy') } catch { /* 复制不了就安静失败 */ }
    ta.remove()
  }
  copied.value = key
  clearTimeout(copiedTimer)
  copiedTimer = setTimeout(() => (copied.value = ''), 1200)
}

function copyLabel(key) {
  return copied.value === key ? tr('copied') : tr('copyBtn')
}

function openHomepage() {
  openUrl('https://github.com/ggml-org/llama.cpp').catch(() => {})
}

onBeforeUnmount(() => clearTimeout(copiedTimer))
</script>

<template>
  <div class="about-hero">
    <svg viewBox="0 0 64 64" fill="currentColor" aria-hidden="true">
      <path d="M14 54 32 12l18 42-8-2.6L32 28.6 22 51.4z" opacity=".9" />
      <path d="M27.2 37.6 44.8 50l3.4-7.2-17-10.6z" opacity=".75" />
    </svg>
    <span class="aname">{{ tr('appName') }}</span>
    <span class="atag">{{ tr('appTagline') }}</span>
  </div>

  <div class="section">{{ tr('version') }}</div>
  <div class="lrow">
    <span class="lname">{{ tr('appVersion') }}</span>
    <span class="r">
      <span class="mono" style="font-family: var(--d5-ui)">{{ VERSION }}</span>
      <button class="textbtn" type="button" @click="copy(VERSION, 'app')">{{ copyLabel('app') }}</button>
    </span>
  </div>
  <div class="lrow">
    <span class="lname">{{ tr('llamaBuild') }}</span>
    <span class="r">
      <span class="mono">{{ llamaBuild }}</span>
      <button class="textbtn" type="button" :disabled="llamaBuild === '—'" @click="copy(llamaBuild, 'build')">{{ copyLabel('build') }}</button>
    </span>
  </div>
  <div class="lrow">
    <span class="lname">{{ tr('appDir') }}</span>
    <span class="r">
      <span class="mono">{{ appDir || '—' }}</span>
      <button v-if="appDir" class="textbtn" type="button" @click="copy(appDir, 'dir')">{{ copyLabel('dir') }}</button>
    </span>
  </div>

  <div class="section">{{ tr('stackSec') }}</div>
  <div class="chips">
    <span v-for="s in stack" :key="s" class="chip">{{ s }}</span>
  </div>

  <div class="section">{{ tr('quickSec') }}</div>
  <div class="actgrid">
    <button type="button" @click="emit('check-updates')">
      <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M16 10a6 6 0 1 1-1.9-4.4" /><path d="M16 4.2v3.4h-3.4" /></svg>
      {{ tr('checkUpdates') }}
    </button>
    <button type="button" @click="openHomepage">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22" /></svg>
      {{ tr('homepage') }}
    </button>
    <button type="button" @click="emit('params')">
      <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5.5 6.5l4.5 3.5-4.5 3.5" /><path d="M12.5 13.5h3" /></svg>
      {{ tr('appParams') }}
    </button>
    <button type="button" @click="emit('license')">
      <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11.5 3H7a1.6 1.6 0 0 0-1.6 1.6v10.8A1.6 1.6 0 0 0 7 17h6a1.6 1.6 0 0 0 1.6-1.6V6.1z" /><path d="M11.5 3v3.1h3.1" /><path d="M8 11h4M8 13.5h4" /></svg>
      {{ tr('license') }}
    </button>
  </div>

  <div class="about-foot">{{ tr('devBy') }}</div>
</template>

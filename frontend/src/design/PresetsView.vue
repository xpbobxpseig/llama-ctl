<script setup>
/**
 * 预设页 · 与稿 1:1：两个 `.section`（我的预设 / 自动备份）+ `.lrow` 列表。
 *
 * 「保存为预设」在第一组标题右侧（原顶栏「更多」菜单的入口迁到这里）。
 * 自动备份按名称前缀分组（`自动备份 ` / `Auto backup `），它们由“切换前备份”
 * 生成，所以稿中只给删除，不给“已载入”标记。
 */
import { computed } from 'vue'
import * as store from '../stores/snapshot.js'
import { t } from './copy.js'

const emit = defineEmits(['load', 'remove', 'save'])

const lang = computed(() => store.lang.value)
const presets = computed(() => store.snapshot.snap?.presets ?? [])
const loaded = computed(() => store.snapshot.snap?.preset_loaded ?? '')

/** 与 submit-copy.js 的 autoBackupName() 同前缀，两种语言都认。 */
const isBackup = (name) => /^(自动备份|Auto backup)\s/.test(name)

const mine = computed(() => presets.value.filter((n) => !isBackup(n)))
const backups = computed(() => presets.value.filter(isBackup))
</script>

<template>
  <div class="section preset-head">
    <span>{{ t('mine', lang) }}</span>
    <button class="textbtn" type="button" @click="emit('save')">{{ t('savePreset', lang) }}</button>
  </div>
  <div v-for="name in mine" :key="name" class="lrow">
    <span class="lname">{{ name }}</span>
    <span class="r">
      <span v-if="name === loaded" class="loadedmark">{{ t('loaded', lang) }}</span>
      <button class="textbtn" type="button" @click="emit('load', name)">{{ t('load', lang) }}</button>
      <button class="iconmini" type="button" :aria-label="t('more', lang)" @click="emit('remove', name)">
        <svg viewBox="0 0 20 20" fill="currentColor"><circle cx="4.6" cy="10" r="1.5" /><circle cx="10" cy="10" r="1.5" /><circle cx="15.4" cy="10" r="1.5" /></svg>
      </button>
    </span>
  </div>

  <div class="section">{{ t('backups', lang) }}</div>
  <div v-for="name in backups" :key="name" class="lrow">
    <span class="lname" style="font-family: var(--d5-mono); font-size: 13px">{{ name }}</span>
    <span class="r">
      <button class="textbtn" type="button" @click="emit('load', name)">{{ t('load', lang) }}</button>
      <button class="iconmini danger" type="button" :aria-label="t('del', lang)" @click="emit('remove', name)">
        <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6h12M8 6V4.6a.6.6 0 0 1 .6-.6h2.8a.6.6 0 0 1 .6.6V6M6.4 6l.5 9a1 1 0 0 0 1 .9h4.2a1 1 0 0 0 1-.9l.5-9M8.6 9v4M11.4 9v4" /></svg>
      </button>
    </span>
  </div>
</template>

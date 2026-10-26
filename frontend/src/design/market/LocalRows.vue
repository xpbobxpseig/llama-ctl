<script setup>
/**
 * 已下载区：区头硬件行（显卡/内存/磁盘剩余，每设备一行）+ 本地模型行
 * （体积/适配/实测成绩 + 实测/启用/打开目录/删除）。危险与停服类操作
 * 全部行内确认（market-ask 共享状态）；「启用」结果上抛给编排层做三种回填。
 */
import { computed } from 'vue'
import * as store from '../../stores/snapshot.js'
import * as market from '../../stores/market.js'
import * as ipc from '../../api/ipc.js'
import { t } from '../copy.js'
import { ask } from '../market-ask.js'
import { fmtBytes as fmtBytesFn, TIER_CLASS, TIER_TEXT } from '../market-fmt.js'

const emit = defineEmits(['enabled'])

const lang = computed(() => store.lang.value)
const tr = (key, fields) => t(key, lang.value, fields)

const gb = fmtBytesFn
const tierClass = TIER_CLASS

function fitText(tier) {
  return tr(TIER_TEXT[tier] || 'fitNo')
}

const localModels = computed(() => market.local.value?.models ?? [])
const localBench = computed(() => market.local.value?.benchmarks ?? [])
const hardware = computed(() => market.local.value?.hardware ?? null)

function benchFor(path) {
  return localBench.value.find((b) => b.model_path === path) || null
}

function onDel(model) {
  if (ask.del === model.path) {
    ask.del = ''
    market.removeLocal(model, store.values.value.model)
  } else {
    ask.del = model.path
    ask.bench = ''
  }
}

function onBench(model) {
  if (ask.bench === model.path) {
    ask.bench = ''
    market.bench(model.path)
  } else {
    ask.bench = model.path
    ask.del = ''
  }
}

function onEnable(model) {
  if (ask.enable === model.path) {
    ask.enable = ''
    market.enable(model).then((r) => emit('enabled', r))
  } else {
    ask.enable = model.path
    ask.del = ''
    ask.bench = ''
  }
}

async function openFolder(model) {
  if (!ipc.isTauri()) return
  const dir = model.path.replace(/[/\\][^/\\]+$/, '')
  try {
    const { openPath } = await import('@tauri-apps/plugin-opener')
    await openPath(dir)
  } catch {
    // 能力缺失：不炸界面
  }
}
</script>

<template>
  <div class="section">{{ tr('localSec') }}</div>
  <!-- 硬件行：每个设备一行（适配等级的判定依据，一坨挤在一行看不清） -->
  <div v-if="hardware" class="hwmeta">
    <template v-if="hardware.gpus.length">
      <div v-for="(g, i) in hardware.gpus" :key="i" class="hwrow">
        <span class="hwk">{{ hardware.gpus.length > 1 ? `${tr('hwGpu')} ${i + 1}` : tr('hwGpu') }}</span>
        <span class="mono hwv">{{ g.name || g.vendor }}</span>
      </div>
    </template>
    <div v-else class="hwrow">
      <span class="hwk">{{ tr('hwGpu') }}</span>
      <span class="mono hwv">CPU</span>
    </div>
    <div v-if="hardware.ram_total" class="hwrow">
      <span class="hwk">{{ tr('hwRam') }}</span>
      <span class="mono hwv">{{ gb(hardware.ram_total) }}</span>
    </div>
    <!-- 下载根所在卷的剩余空间：None（网络盘等）整行隐藏 -->
    <div v-if="market.local.value?.disk_free != null" class="hwrow">
      <span class="hwk">{{ tr('diskFree') }}</span>
      <span class="mono hwv">{{ gb(market.local.value.disk_free) }}</span>
    </div>
  </div>
  <div v-if="!localModels.length" class="lrow meta">{{ tr('localEmpty') }}</div>
  <div v-for="m in localModels" :key="m.path" class="mrow local">
    <div class="vmain">
      <span class="nm">{{ m.label }}</span>
      <span class="fl">{{ m.path }}</span>
      <span class="mono size">{{ gb(m.size) }}</span>
      <span class="fit" :class="tierClass[m.fit?.tier]">{{ fitText(m.fit?.tier) }}</span>
      <span v-if="benchFor(m.path)" class="mono dim bench">
        pp {{ benchFor(m.path).pp_tps.toFixed(0) }} · tg {{ benchFor(m.path).tg_tps.toFixed(1) }} t/s
      </span>
    </div>
    <div class="why">{{ m.fit?.reason }}</div>
    <p v-if="ask.bench === m.path" class="ask">
      <span>{{ tr('confirmBench') }}</span>
      <button class="pillbtn" type="button" @click="onBench(m)">{{ market.benchBusy.value ? tr('benchRunning') : tr('benchBtn') }}</button>
      <button class="textbtn" type="button" @click="ask.bench = ''">{{ tr('cancelDl') }}</button>
    </p>
    <p v-else-if="ask.enable === m.path" class="ask">
      <span>{{ tr('enableAsk') }}</span>
      <button class="pillbtn" type="button" @click="onEnable(m)">{{ tr('enable') }}</button>
      <button class="textbtn" type="button" @click="ask.enable = ''">{{ tr('cancelDl') }}</button>
    </p>
    <p v-else-if="ask.del === m.path" class="ask">
      <span>{{ tr('confirmDel') }}</span>
      <button class="pillbtn" type="button" @click="onDel(m)">{{ tr('removeModel') }}</button>
      <button class="textbtn" type="button" @click="ask.del = ''">{{ tr('cancelDl') }}</button>
    </p>
    <div v-else class="vops">
      <button class="textbtn" type="button" :disabled="!!market.benchBusy.value" @click="onBench(m)">{{ market.benchBusy.value === m.path ? tr('benchRunning') : tr('benchBtn') }}</button>
      <!-- 顺序：实测 / 启用 / 打开目录 / 删除；启用需行内确认 -->
      <button class="textbtn" type="button" @click="onEnable(m)">{{ tr('enable') }}</button>
      <button class="textbtn" type="button" @click="openFolder(m)">{{ tr('openFolder') }}</button>
      <button class="textbtn danger" type="button" @click="onDel(m)">{{ tr('removeModel') }}</button>
    </div>
  </div>
</template>

<script setup>
/**
 * 下载任务区：下单失败红行 + 任务行（进度 / 速度 / ETA / 状态 / 行内确认）。
 * 完成任务匹配到已下载条目时行内直接「启用」；确认状态是跨区共享的
 * market-ask（打开这里会按既有语义关掉已下载区开着的那处）。
 */
import { computed } from 'vue'
import * as store from '../../stores/snapshot.js'
import * as market from '../../stores/market.js'
import { t } from '../copy.js'
import { ask } from '../market-ask.js'
import {
  fmtBytes as fmtBytesFn,
  fmtEta as fmtEtaFn,
  pct as pctFn,
  STATE_TEXT,
} from '../market-fmt.js'

const emit = defineEmits(['enabled'])

const lang = computed(() => store.lang.value)
const tr = (key, fields) => t(key, lang.value, fields)

const fmtBytes = fmtBytesFn
const fmtEta = fmtEtaFn
const pct = pctFn
const stateText = STATE_TEXT

const localFor = (t) => market.taskToLocal(t)

function onTaskEnable(t) {
  const m = localFor(t)
  if (!m) return
  if (ask.task === t.id) {
    ask.task = ''
    market.enable(m).then((r) => emit('enabled', r))
  } else {
    ask.task = t.id
    ask.enable = ''
    ask.del = ''
    ask.bench = ''
  }
}
</script>

<template>
  <div class="section">{{ tr('tasksSec') }}</div>
  <!-- 下单失败就地可见（磁盘预检拒绝等）；重试成功或切源后消失 -->
  <p v-if="market.orderError.value" class="ask order-err">
    <span class="fit f-err">{{ tr('loadFail') }}</span>
    <span>{{ market.orderError.value }}</span>
  </p>
  <div v-if="!market.tasks.value.length" class="lrow meta">—</div>
  <div v-for="t in market.tasks.value" :key="t.id" class="mrow task">
    <div class="vmain">
      <span class="nm">{{ t.label }}</span>
      <span class="fl">{{ t.repo }}</span>
      <span class="mono dim">{{ fmtBytes(t.received) }} / {{ fmtBytes(t.total) }}</span>
      <span v-if="t.state === 'running' && t.speed_bps" class="mono dim">{{ fmtBytes(t.speed_bps) }}/s</span>
      <span v-if="t.state === 'running' && t.speed_bps" class="mono dim">· {{ tr('eta') }} {{ fmtEta((t.total - t.received) / t.speed_bps) }}</span>
      <span class="fit" :class="{ 'f-err': t.state === 'failed' }">{{ tr(stateText[t.state] || 'dlQueued') }}<template v-if="t.state === 'failed'">：{{ t.error }}</template></span>
    </div>
    <div v-if="t.state === 'running' || t.state === 'paused'" class="pbar">
      <div class="pfill" :style="{ width: pct(t) + '%' }"></div>
    </div>
    <p v-if="t.state === 'done' && localFor(t) && ask.task === t.id" class="ask">
      <span>{{ tr('enableAsk') }}</span>
      <button class="pillbtn" type="button" @click="onTaskEnable(t)">{{ tr('enable') }}</button>
      <button class="textbtn" type="button" @click="ask.task = ''">{{ tr('cancelDl') }}</button>
    </p>
    <div class="vops">
      <button v-if="t.state === 'done' && localFor(t)" class="textbtn" type="button" @click="onTaskEnable(t)">{{ tr('enable') }}</button>
      <button v-if="t.state === 'running'" class="textbtn" type="button" @click="market.pauseTask(t.id)">{{ tr('pause') }}</button>
      <button v-if="t.state === 'paused' || t.state === 'failed'" class="textbtn" type="button" @click="market.resumeTask(t.id)">{{ tr('resume') }}</button>
      <button v-if="t.state !== 'done'" class="textbtn danger" type="button" @click="market.cancelTask(t.id)">{{ tr('cancelDl') }}</button>
    </div>
  </div>
</template>

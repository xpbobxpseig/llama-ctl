<script setup>
/**
 * 市场页 · 发现 / 下载任务 / 已下载 三区（spec: docs/spec/model-marketplace.md）。
 *
 * - 权威状态在 Rust（DownloadManager + market.json），这里经 stores/market.js 镜像；
 * - 任务进度来自 EVENT_MARKET 全量推送，实测行流走 EVENT_BENCH 直落日志页；
 * - 「启用」回填 --model / --mmproj 到表单并走 Apply（AppParameters 唯一真源）；
 * - 适配等级色标用状态令牌：run=全量档 / warn=部分档 / gray=仅CPU / err=不建议。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import * as store from '../stores/snapshot.js'
import * as market from '../stores/market.js'
import * as ipc from '../api/ipc.js'
import { t } from './copy.js'
import Dd from './Dd.vue'

const lang = computed(() => store.lang.value)
const tr = (key, fields) => t(key, lang.value, fields)

const hubOptions = [
  { value: 'ms', label: '魔搭 ModelScope' },
  { value: 'hf', label: 'HuggingFace' },
]

/** 量级档位：0=全部。默认 ≥1B（spec 工单 3），档位给足往上选的空间。 */
const minOptions = computed(() => [
  { value: '0', label: tr('allSizes') },
  { value: '1', label: '≥1B' },
  { value: '7', label: '≥7B' },
  { value: '30', label: '≥30B' },
])

const search = ref('')
let searchTimer = null
function onSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => market.setQuery(search.value), 400)
}

const UNITS = ['B', 'KB', 'MB', 'GB', 'TB']

function fmtBytes(n) {
  if (n == null) return '—'
  let v = n
  let i = 0
  while (v >= 1024 && i < UNITS.length - 1) {
    v /= 1024
    i++
  }
  return `${v >= 100 || i === 0 ? v.toFixed(0) : v.toFixed(1)}${UNITS[i]}`
}

function gb(n) {
  return fmtBytes(n)
}

function fmtCount(n) {
  if (n == null) return '—'
  return n >= 10000 ? `${(n / 10000).toFixed(1)}w` : String(n)
}

const tierText = { full_gpu: 'fitFull', partial_gpu: 'fitPartial', cpu_only: 'fitCpu', not_recommended: 'fitNo' }
const tierClass = { full_gpu: 'fit-full', partial_gpu: 'fit-partial', cpu_only: 'fit-cpu', not_recommended: 'fit-no' }

function fitText(tier) {
  return tr(tierText[tier] || 'fitNo')
}

const stateText = { queued: 'dlQueued', running: 'dlRunning', paused: 'dlPaused', done: 'dlFin', failed: 'dlFail' }

const detailVariants = computed(() => market.detail.value?.variants ?? [])
const localModels = computed(() => market.local.value?.models ?? [])
const localBench = computed(() => market.local.value?.benchmarks ?? [])
const hardware = computed(() => market.local.value?.hardware ?? null)

function benchFor(path) {
  return localBench.value.find((b) => b.model_path === path) || null
}

const LIVE_STATES = ['queued', 'running', 'paused']

function taskFor(repo, label) {
  return market.tasks.value.find((t) => t.repo === repo && t.label === label && LIVE_STATES.includes(t.state)) || null
}

function pct(t) {
  return t.total > 0 ? Math.min(100, Math.round((t.received * 100) / t.total)) : 0
}

// ---- 确认（行内，不用全屏弹层） -------------------------------------------

const askDel = ref('')
const askBench = ref('')
const askEnable = ref('')

function onDel(model) {
  if (askDel.value === model.path) {
    askDel.value = ''
    market.removeLocal(model, store.values.value.model)
  } else {
    askDel.value = model.path
    askBench.value = ''
  }
}

function onBench(model) {
  if (askBench.value === model.path) {
    askBench.value = ''
    market.bench(model.path)
  } else {
    askBench.value = model.path
    askDel.value = ''
  }
}

function onEnable(model) {
  if (askEnable.value === model.path) {
    askEnable.value = ''
    market.enable(model).then((r) => {
      if (!r) return // 失败：applyError 行已浮出
      if (r.needs_restart) {
        askRestart.value = true // 服务在跑：给「立即重启」让参数真正生效
      } else if (r.written === false) {
        enableDone.value = tr('enableCurrent')
        setTimeout(() => (enableDone.value = ''), 4000)
      } else {
        enableDone.value = tr('enableDone') // 服务未运行：下次启动生效
        setTimeout(() => (enableDone.value = ''), 4000)
      }
    })
  } else {
    askEnable.value = model.path
    askDel.value = ''
    askBench.value = ''
  }
}

const askRestart = ref(false)

async function doRestart() {
  askRestart.value = false
  await market.restartNow()
}

const enableDone = ref('')

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

// ---- 挂载 -----------------------------------------------------------------

const unlisten = []

onMounted(async () => {
  unlisten.push(await market.subscribe())
  await market.init()
})

onBeforeUnmount(() => {
  unlisten.forEach((fn) => fn && fn())
  unlisten.length = 0
})
</script>

<template>
  <div>
    <!-- 发现 -->
    <div class="section market-head">
      <span>{{ tr('hot') }}</span>
      <Dd
        class="hubdd"
        :options="hubOptions"
        :model-value="market.hub.value"
        @change="market.saveHub($event)"
      />
      <input
        v-model="search"
        class="nameinput search"
        type="text"
        spellcheck="false"
        :placeholder="tr('searchPh')"
        @input="onSearch"
      />
      <span class="mlabel">{{ tr('scaleLabel') }}</span>
      <Dd
        class="mindd"
        :options="minOptions"
        :model-value="String(market.minB.value)"
        @change="market.setMinB($event)"
      />
      <button class="textbtn" type="button" :disabled="store.busy.value" @click="market.loadList()">{{ tr('refresh') }}</button>
    </div>

    <!-- 加载失败浮出：绝不静默停在旧列表上 -->
    <div v-if="market.error.value" class="mrow">
      <span class="fit f-gated">{{ tr('loadFail') }}</span>
      <span class="fl">{{ market.error.value }}</span>
      <button class="textbtn" type="button" @click="market.loadList()">{{ tr('refresh') }}</button>
    </div>

    <!-- 详情 -->
    <template v-if="market.detail.value">
      <div class="mrow back">
        <button class="textbtn" type="button" @click="market.closeDetail()">{{ tr('back') }}</button>
        <span class="nm">{{ market.detail.value.id }}</span>
        <span v-if="market.detail.value.gated" class="fit f-gated">{{ tr('gated') }}</span>
      </div>
      <div class="lrow meta">
        <span class="mono">
          {{ tr('downloads') }} {{ fmtCount(market.detail.value.downloads) }}
          <template v-if="market.detail.value.gguf?.context_length">· {{ tr('ctx') }} {{ market.detail.value.gguf.context_length }}</template>
          <template v-if="market.detail.value.gguf?.architecture">· {{ tr('arch') }} {{ market.detail.value.gguf.architecture }}</template>
          <template v-if="market.detail.value.gguf?.total_params">· {{ (market.detail.value.gguf.total_params / 1e9).toFixed(1) }}B</template>
        </span>
        <span v-if="detailVariants.some((v) => v.mmproj)" class="fl">{{ tr('mmprojHint') }}</span>
      </div>
      <div v-for="v in detailVariants" :key="v.label" class="mrow variant">
        <div class="vmain">
          <span class="nm">{{ v.label }}</span>
          <span v-if="v.is_sharded" class="fl">{{ tr('shards') }} {{ v.files.length }}</span>
          <span class="mono size">{{ gb(v.total_size + (v.mmproj?.size ?? 0)) }}</span>
          <span class="fit" :class="tierClass[v.fit?.tier || 'not_recommended']">{{ fitText(v.fit?.tier) }}</span>
        </div>
        <div class="vfit">
          <span class="why">{{ v.fit?.reason }}</span>
          <button
            class="pillbtn"
            type="button"
            :disabled="!!taskFor(market.detail.value.id, v.label)"
            @click="market.enqueue(v, market.detail.value.id)"
          >
            {{ taskFor(market.detail.value.id, v.label) ? tr('dlQueued') : tr('download') }}
          </button>
        </div>
      </div>
    </template>

    <!-- 列表 -->
    <template v-else>
      <div v-if="!market.list.value.length" class="lrow meta">{{ tr('marketEmpty') }}</div>
      <button v-for="r in market.list.value" :key="r.id" class="mrow repo" type="button" @click="market.openDetail(r.id)">
        <span class="nm">{{ r.name }}</span>
        <span v-if="r.gated" class="fit f-gated">{{ tr('gated') }}</span>
        <span class="mono dim">
          {{ r.params_b ? r.params_b + 'B · ' : '' }}{{ tr('downloads') }} {{ fmtCount(r.downloads) }}
        </span>
      </button>
    </template>

    <!-- 下载任务 -->
    <div class="section">{{ tr('tasksSec') }}</div>
    <div v-if="!market.tasks.value.length" class="lrow meta">—</div>
    <div v-for="t in market.tasks.value" :key="t.id" class="mrow task">
      <div class="vmain">
        <span class="nm">{{ t.label }}</span>
        <span class="fl">{{ t.repo }}</span>
        <span class="mono dim">{{ fmtBytes(t.received) }} / {{ fmtBytes(t.total) }}</span>
        <span v-if="t.state === 'running' && t.speed_bps" class="mono dim">{{ fmtBytes(t.speed_bps) }}/s</span>
        <span class="fit" :class="{ 'f-err': t.state === 'failed' }">{{ tr(stateText[t.state] || 'dlQueued') }}<template v-if="t.state === 'failed'">：{{ t.error }}</template></span>
      </div>
      <div v-if="t.state === 'running' || t.state === 'paused'" class="pbar">
        <div class="pfill" :style="{ width: pct(t) + '%' }"></div>
      </div>
      <div class="vops">
        <button v-if="t.state === 'running'" class="textbtn" type="button" @click="market.pauseTask(t.id)">{{ tr('pause') }}</button>
        <button v-if="t.state === 'paused' || t.state === 'failed'" class="textbtn" type="button" @click="market.resumeTask(t.id)">{{ tr('resume') }}</button>
        <button v-if="t.state !== 'done'" class="textbtn danger" type="button" @click="market.cancelTask(t.id)">{{ tr('cancelDl') }}</button>
      </div>
    </div>

    <!-- 已下载 -->
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
      <p v-if="askBench === m.path" class="ask">
        <span>{{ tr('confirmBench') }}</span>
        <button class="pillbtn" type="button" @click="onBench(m)">{{ market.benchBusy.value ? tr('benchRunning') : tr('benchBtn') }}</button>
        <button class="textbtn" type="button" @click="askBench = ''">{{ tr('cancelDl') }}</button>
      </p>
      <p v-else-if="askEnable === m.path" class="ask">
        <span>{{ tr('enableAsk') }}</span>
        <button class="pillbtn" type="button" @click="onEnable(m)">{{ tr('enable') }}</button>
        <button class="textbtn" type="button" @click="askEnable = ''">{{ tr('cancelDl') }}</button>
      </p>
      <p v-else-if="askDel === m.path" class="ask">
        <span>{{ tr('confirmDel') }}</span>
        <button class="pillbtn" type="button" @click="onDel(m)">{{ tr('removeModel') }}</button>
        <button class="textbtn" type="button" @click="askDel = ''">{{ tr('cancelDl') }}</button>
      </p>
      <div v-else class="vops">
        <button class="textbtn" type="button" :disabled="!!market.benchBusy.value" @click="onBench(m)">{{ market.benchBusy.value === m.path ? tr('benchRunning') : tr('benchBtn') }}</button>
        <!-- 顺序：实测 / 启用 / 打开目录 / 删除；启用需行内确认 -->
        <button class="textbtn" type="button" @click="onEnable(m)">{{ tr('enable') }}</button>
        <button class="textbtn" type="button" @click="openFolder(m)">{{ tr('openFolder') }}</button>
        <button class="textbtn danger" type="button" @click="onDel(m)">{{ tr('removeModel') }}</button>
      </div>
    </div>
    <p v-if="market.applyError.value" class="ask">
      <span class="fit f-gated">{{ tr('loadFail') }}</span>
      <span>{{ market.applyError.value }}</span>
    </p>
    <p v-if="askRestart" class="ask">
      <span>{{ tr('enableRestart') }}</span>
      <button class="pillbtn" type="button" @click="doRestart">{{ tr('restartSvc') }}</button>
      <button class="textbtn" type="button" @click="askRestart = false">{{ tr('cancelDl') }}</button>
    </p>
    <p v-if="enableDone" class="lrow meta ok-line">{{ enableDone }}</p>
  </div>
</template>

<script setup>
/**
 * 市场页编排器 · 发现 / 下载任务 / 已下载 三区（spec: docs/spec/model-marketplace.md）。
 *
 * - 权威状态在 Rust（DownloadManager + market.json），经 stores/market.js 镜像；
 * - 三区渲染拆在 market/ 子组件（MarketHead / RepoRows / TaskRows / LocalRows），
 *   各自直连 store；行内确认的跨区语义由 market-ask.js 的共享状态保证；
 * - 子组件的「启用」结果上抛到这里做三种回填（重启询问 / 已是当前 / 正常生效）；
 * - 任务进度来自 EVENT_MARKET 全量推送，实测行流走 EVENT_BENCH 直落日志页。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import * as store from '../stores/snapshot.js'
import * as market from '../stores/market.js'
import { t } from './copy.js'
import MarketHead from './market/MarketHead.vue'
import RepoRows from './market/RepoRows.vue'
import TaskRows from './market/TaskRows.vue'
import LocalRows from './market/LocalRows.vue'

const lang = computed(() => store.lang.value)
const tr = (key, fields) => t(key, lang.value, fields)

/** 启用发出后的三种回填：需重启 / 已是当前模型 / 正常生效。 */
function afterEnable(r) {
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
}

const askRestart = ref(false)

async function doRestart() {
  askRestart.value = false
  await market.restartNow()
}

const enableDone = ref('')

// ---- 挂载 -----------------------------------------------------------------

const unlisten = []

onMounted(async () => {
  // subscribe() 返回的是 unlisten 数组——必须摊开；整体 push 会让卸载钩子
  // 对数组调 fn()，每次离开市场页都抛 TypeError（Vue 只在控制台里吞掉）。
  unlisten.push(...(await market.subscribe()))
  await market.init()
})

onBeforeUnmount(() => {
  unlisten.forEach((fn) => fn && fn())
  unlisten.length = 0
})
</script>

<template>
  <div>
    <MarketHead />

    <!-- 加载失败浮出：绝不静默停在旧列表上 -->
    <div v-if="market.error.value" class="mrow">
      <span class="fit f-gated">{{ tr('loadFail') }}</span>
      <span class="fl">{{ market.error.value }}</span>
      <button class="textbtn" type="button" @click="market.loadList()">{{ tr('refresh') }}</button>
    </div>

    <RepoRows />
    <TaskRows @enabled="afterEnable" />
    <LocalRows @enabled="afterEnable" />

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

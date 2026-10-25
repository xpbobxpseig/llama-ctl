<script setup>
/**
 * 日志页 · 与稿 1:1：一条 `.logmeta`（文件路径 + 清空 + 跟随开关）+ `.logline` 列表。
 *
 * 两个真实来源与 LogTail 一致：`tail_log` 的尾部（Rust 决定路径与截断），
 * 以及重启/更新时流进 `snapshot.log` 的过程行。跟随开启时按 1500ms 轮询；
 * shell 外只有演示行，并照实显示。
 *
 * 「清空」只清**屏幕**：过程行清掉，文件尾按清空瞬间的内容记一个签名，
 * 轮询拿回同样的尾部就继续藏着，一旦文件有新内容（签名不同）自动恢复
 * 显示——llama-server 还在写这个文件，界面上没有「删文件」这回事。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as store from '../stores/snapshot.js'
import { tailLog } from '../api/ipc.js'
import { t } from './copy.js'

const lang = computed(() => store.lang.value)

/** 跟随开关：稿中右下是「跟随中 · 时间」，关掉就停在原地。 */
const follow = ref(true)

/** 清空后的文件尾签名；空串 = 没清过。 */
const clearedTail = ref('')

const fileLines = ref([])
const fileFrom = ref('')
const root = ref(null)

let timer = null
let token = 0
const POLL_MS = 1500

function clearView() {
  store.clearLog()
  clearedTail.value = JSON.stringify(fileLines.value)
}

async function poll() {
  const mine = ++token
  try {
    const { lines, path } = await tailLog()
    if (mine !== token) return
    fileLines.value = lines || []
    fileFrom.value = path || ''
  } catch {
    // 一次失败不能清空已有内容。
  }
}

function start() {
  stop()
  if (store.isDemo.value) return
  poll()
  timer = setInterval(poll, POLL_MS)
}

function stop() {
  token++
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

onMounted(() => {
  if (follow.value) start()
})

onBeforeUnmount(stop)

watch(follow, (on) => (on ? start() : stop()))

const demo = computed(() =>
  store.isDemo.value
    ? [
        '12:03:11.482 srv  load_model: ngl = 128, ctx = 65536',
        '12:03:11.503 srv  load_tensors: offloaded 128/128 layers to GPU',
        '12:03:12.117 srv  server is listening on 127.0.0.1:8080',
        '12:03:19.004 srv  [warn] prompt cache is disabled',
        '12:04:02.771 srv  [error] slot 0: context overflow',
        '12:04:03.010 srv  update_slots: all slots are idle',
      ]
    : [],
)

/** 文件尾换了内容就解除清空；同样的尾部继续藏着。 */
watch(
  () => JSON.stringify(fileLines.value),
  (sig) => {
    if (clearedTail.value && sig !== clearedTail.value) clearedTail.value = ''
  },
)

/** 过程行是用户刚刚做过的事，比文件尾部新，排在后面。清空后只留新过程行。 */
const raw = computed(() => {
  const cleared = clearedTail.value !== ''
  const base = cleared ? [] : store.isDemo.value ? demo.value : fileLines.value
  return [...base, ...store.snapshot.log]
})

/** 没有可清的东西时按钮禁用：屏上空着，或已经清过且没有新过程行。 */
const clearDisabled = computed(
  () => clearedTail.value !== '' && store.snapshot.log.length === 0,
)

function parse(line) {
  const text = String(line ?? '')
  const m = text.match(/^(\d{2}:\d{2}:\d{2}\.\d{3})\s+(.*)$/)
  const body = m ? m[2] : text
  const level = /\berror\b/i.test(body) ? 'err' : /\bwarn\b/i.test(body) ? 'warn' : ''
  return { time: m ? m[1] : '', body, level }
}

const lines = computed(() => raw.value.map(parse))

/** 稿中右上是路径：Rust 报的优先，否则由服务目录拼。 */
const path = computed(() => {
  if (fileFrom.value) return fileFrom.value
  const dir = store.snapshot.snap?.facts?.app_dir
  return dir ? `${dir.replace(/[\\/]+$/, '')}\\server.err` : 'F:\\llama.cpp\\server.err'
})

/** 跟随中的时间戳：最后一行的时刻。 */
const stamp = computed(() => {
  const last = lines.value[lines.value.length - 1]
  if (last?.time) return last.time.slice(0, 8)
  const now = new Date()
  return [now.getHours(), now.getMinutes(), now.getSeconds()].map((n) => String(n).padStart(2, '0')).join(':')
})

const followLabel = computed(() =>
  follow.value ? t('following', lang.value, { t: stamp.value }) : t('paused', lang.value),
)

/** 新行到达时贴底：最新的一行才是用户要看的。 */
watch(
  () => lines.value.length,
  async () => {
    if (!follow.value) return
    await nextTick()
    const el = root.value?.closest('.content')
    if (el) el.scrollTop = el.scrollHeight
  },
)
</script>

<template>
  <div ref="root">
    <div class="logmeta">
      <span class="mono">{{ path }}</span>
      <span class="logops">
        <button class="textbtn clear" type="button" :disabled="clearDisabled" @click="clearView">
          {{ t('clearLog', lang) }}
        </button>
        <button class="textbtn follow" type="button" @click="follow = !follow">
          <span class="dotlive" :class="{ off: !follow }"></span>{{ followLabel }}
        </button>
      </span>
    </div>
    <div class="log">
      <div v-for="(line, i) in lines" :key="i" class="logline" :class="line.level">
        <span class="t">{{ line.time }}</span><span class="m">{{ line.body }}</span>
      </div>
    </div>
  </div>
</template>

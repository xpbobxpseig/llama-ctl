<script setup>
/**
 * v5 设计层的外壳 · 与 docs/ui-redesign/v5-quiet-mockup.html 的 DOM 同构。
 *
 * 三件事：
 *   1. 结构照稿：rail（服务 / 3 个视图 / 设置·关于 / 筛选）+ topbar（标题、主操作、
 *      重启、目录、更多、窗口按钮）+ content + 空态水印 + 底部动作条 + 右下状态。
 *   2. 行为照契约：每个按钮都是一条 IPC，答案是新的 Snapshot；确认动作先问再发。
 *   3. 稿外必需的交互（弹层、菜单、编辑态）只用稿中令牌，不新增可见文案。
 *
 * 窗口用 `decorations: false`：标题栏由这里画，`data-tauri-drag-region` 负责拖动。
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import * as store from '../stores/snapshot.js'
import * as theme from '../stores/theme.js'
import * as update from '../stores/update.js'
import * as ipc from '../api/ipc.js'
import * as geo from '../window/geometry.js'
import { applyMotion } from '../motion/index.js'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { t, autoBackupName } from './copy.js'
import { FIELDS } from '../api/field-copy.js'
import ParamsView from './ParamsView.vue'
import LogsView from './LogsView.vue'
import PresetsView from './PresetsView.vue'
import SettingsView from './SettingsView.vue'
import AboutView from './AboutView.vue'
import MarketView from './MarketView.vue'
import './design.css'

const lang = computed(() => store.lang.value)
const tr = (key, fields) => t(key, lang.value, fields)

// ---- 视图 ---------------------------------------------------------------

const view = ref('params')
const filter = ref('all')

function go(name) {
  view.value = name
  menu.value = ''
}

/** 无服务：稿里只留水印，标题压到 45%。 */
const noService = computed(() => store.services.value.length === 0)

/** 稿中 `.rail-tools` 只在参数页出现。 */
const showTools = computed(() => view.value === 'params' && !noService.value)

// ---- 计数 ---------------------------------------------------------------

// 差异的基准是服务的当前参数（service_values），不是表单/预填写——
// 载入预设后两者不同；旧快照没有该字段时退回 values。
const svcValues = computed(
  () => store.snapshot.snap?.service_values ?? store.snapshot.snap?.values ?? {},
)

function changed(field) {
  return String(store.values.value[field.key] ?? '') !== String(svcValues.value[field.key] ?? '')
}

/** 差异行的字段名：跟界面语言，去掉命令行 flag 括号。 */
function fieldName(field) {
  const label = lang.value === 'en' ? field.en || field.zh : field.zh
  return label.replace(/\s*\([^()]*\)\s*$/, '')
}

const changedFields = computed(() => FIELDS.filter(changed))
const dirtyCount = computed(() => changedFields.value.length)

// ---- 顶栏状态 -----------------------------------------------------------

const status = computed(() => store.status.value)
const running = computed(() => status.value.state === 'RUNNING')
const stopped = computed(() => status.value.state === 'STOPPED')

const healthText = computed(() => {
  if (status.value.ok) return tr('healthOk')
  if (stopped.value) return tr('stopped')
  return tr('healthIdle')
})

const portText = computed(() => (store.values.value.port ? `:${store.values.value.port}` : ''))

const selected = computed(() => store.selected.value)

/** llama.cpp 安装目录（「打开安装目录」的目标；没有就保持禁用）。 */
const appDir = computed(() => String(store.snapshot.snap?.facts?.app_dir ?? ''))

async function openInstallDir() {
  if (!appDir.value) return
  if (!ipc.isTauri()) {
    // demo：落一行日志作反馈，绝不让点击看起来「没反应」
    store.pushLog(`[demo] 将打开安装目录 ${appDir.value}`)
    return
  }
  try {
    const { openPath } = await import('@tauri-apps/plugin-opener')
    await openPath(appDir.value)
  } catch {
    // 能力缺失：不炸界面
  }
}

// ---- 菜单 ---------------------------------------------------------------

const menu = ref('')

function toggleMenu(name) {
  menu.value = menu.value === name ? '' : name
}

function onDocClick(event) {
  if (!event.target.closest?.('.menu') && !event.target.closest?.('[data-menu]')) menu.value = ''
}

// ---- 弹层 ---------------------------------------------------------------

const dialog = reactive({ kind: '', target: '', guard: '', mode: '', name: '' })

function closeDialog() {
  dialog.kind = ''
  dialog.target = ''
  dialog.guard = ''
  dialog.name = ''
}

/** 应用更改：差异本身就是第二次确认。 */
function openApply() {
  if (store.busy.value || dirtyCount.value === 0) return
  dialog.kind = 'apply'
}

function openRestart() {
  if (store.busy.value || noService.value) return
  dialog.kind = 'restart'
}

function openInstall() {
  if (!update.canInstall.value) return
  update.askInstall()
  dialog.kind = 'install'
}

function openDelete(name) {
  dialog.target = name
  dialog.kind = 'delete'
}

function openSave() {
  dialog.name = ''
  dialog.kind = 'save'
}

function openParams() {
  dialog.kind = 'params'
}

function openLicense() {
  dialog.kind = 'license'
}

/** 关于页的「检查更新」：结果落在一个弹层里，绝不静默安装。 */
async function checkUpdates() {
  if (update.busy.value) return
  await update.check()
  dialog.kind = 'upd'
}

/** 有未应用更改时的三选：另存并切换 / 放弃 / 取消。 */
function guardOr(kind, target) {
  if (dirtyCount.value > 0) {
    dialog.guard = kind
    dialog.target = target
    dialog.kind = 'guard'
    return true
  }
  return false
}

// ---- 动作 ---------------------------------------------------------------

async function primary() {
  if (store.busy.value || noService.value) return
  await store.run('service_action', () => ipc.serviceAction(running.value ? 'stop' : 'start'))
}

async function doRestart() {
  closeDialog()
  store.clearLog()
  await store.run('restart', () => ipc.restart(store.values.value))
}

async function doApply() {
  closeDialog()
  await store.run('apply_changes', () => ipc.applyChanges(store.values.value, store.snapshot.snap?.extras ?? []), (res) => {
    store.setSnapshot(res.snapshot)
    store.clearForm()
  })
}

async function doRevert() {
  if (dirtyCount.value === 0) return
  const snap = await store.run('revert', () => ipc.revert())
  if (snap) store.clearForm()
}

async function doSwitch(name) {
  const snap = await store.run('switch_service', () => ipc.switchService(name, store.values.value))
  store.clearForm()
  if (snap) await store.refresh()
}

async function doLoad(name) {
  // load_preset 的 Snapshot 已经把预设值作为表单带回（editing=Some(preset)）。
  // 这里绝不能再 refresh——refresh 以 editing=None 拉快照，拿回的是服务当前
  // 参数，会把刚填进表单的预设值当场冲掉（「预设是摆设」的根因）。
  const snap = await store.run('load_preset', () => ipc.loadPreset(name))
  if (snap) store.clearForm()
}

async function doSave() {
  const name = dialog.name.trim()
  if (!name) return
  closeDialog()
  await store.run('save_preset', () => ipc.savePreset(name, store.values.value))
  await store.refresh()
}

async function doDelete() {
  const name = dialog.target
  closeDialog()
  await store.run('delete_preset', () => ipc.deletePreset(name))
  await store.refresh()
}

async function doInstall() {
  closeDialog()
  await update.beginInstall()
}

function onPickService(name) {
  menu.value = ''
  if (name === selected.value) return
  if (guardOr('service', name)) return
  doSwitch(name)
}

function onLoadPreset(name) {
  if (name === store.snapshot.snap?.preset_loaded) return
  if (guardOr('preset', name)) return
  doLoad(name)
}

/** 三选里的「另存并切换」：先备份当前表单，再照常切换。 */
async function backupThen() {
  const { guard, target } = dialog
  closeDialog()
  await store.run('save_preset', () => ipc.savePreset(autoBackupName(), store.values.value))
  if (guard === 'service') await doSwitch(target)
  else await doLoad(target)
}

function discardThen() {
  const { guard, target } = dialog
  closeDialog()
  if (guard === 'service') doSwitch(target)
  else doLoad(target)
}

// ---- 窗口按钮（自绘标题栏） --------------------------------------------

/**
 * 无边框窗口的缩放热区。
 *
 * `decorations: false` 之后 Windows 不给窗口 resize 边框（tao 也不做 hit-test），
 * 所以边缘必须自己给：8 个 5px 的不可见热区，按下就交给 Tauri 的
 * `startResizeDragging`。这也解释了“缩放出滚动条而不是自适应”——此前窗口根本
 * 没有可抓的边。
 */
const GRIPS = [
  ['n', 'North'],
  ['s', 'South'],
  ['w', 'West'],
  ['e', 'East'],
  ['nw', 'NorthWest'],
  ['ne', 'NorthEast'],
  ['sw', 'SouthWest'],
  ['se', 'SouthEast'],
]

function startResize(direction) {
  const w = currentWindow()
  if (w) w.startResizeDragging(direction).catch(() => {})
}

function currentWindow() {
  if (!ipc.isTauri()) return null
  try {
    return getCurrentWindow()
  } catch {
    // 权限/元数据缺失时不该让点击抛未捕获 rejection。
    return null
  }
}

async function minimize() {
  await currentWindow()?.minimize().catch(() => {})
}

async function toggleMaximize() {
  await currentWindow()?.toggleMaximize().catch(() => {})
}

async function closeWindow() {
  await currentWindow()?.close().catch(() => {})
}

// ---- 启动 ---------------------------------------------------------------

const unlisten = []

async function ipcSafe(fn) {
  try {
    return await fn()
  } catch {
    return null
  }
}

watch(
  () => theme.reducedMotion.value,
  (off) => applyMotion(!off),
  { immediate: true },
)

onMounted(async () => {
  theme.startAppearance()
  document.addEventListener('click', onDocClick)
  await store.refresh()
  await geo.watchGeometry()
  unlisten.push(await ipcSafe(() => ipc.onProgress(ipc.EVENT_RESTART, store.pushLog)))
  await update.autoCheck()
})

onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
  unlisten.forEach((fn) => fn && fn())
  unlisten.length = 0
  geo.stopGeometry()
})

const themeMode = computed(() => theme.mode.value)

/**
 * 云母材质只存在于 Tauri 壳里（窗口的 windowEffects）。设置页的「半透明
 * 材质」开关通过 save_settings 持久化（settings.mica_enabled，Rust 落盘），
 * 前端在这里把开关落到窗口上：开 = 挂 mica/acrylic，关 = 清掉特效；
 * `mica-host` 落在 <html> 上，把 global.css 给 body 的底色透出去，关掉时
 * 收回不透明底。
 */
const mica = computed(() => ipc.isTauri() && (store.settings.value?.mica_enabled ?? true))

const MICA_EFFECTS = { effects: ['acrylic'] }

/**
 * 窗口材质的运行时对齐：
 *   - 主题跟随应用外观（不是系统）。Mica 的明暗底色跟窗口主题走，浅色页
 *     罩在系统深色模式的材质上会整体发灰——真机「浅色发灰」的根因；
 *   - 半透明材质开关挂/摘窗口特效。
 * 两处失败都不致命（旧 WebView、权限回收）：保持现状，别让界面炸。
 */
watch(
  [mica, () => theme.mode.value],
  async ([on, mode]) => {
    if (typeof document !== 'undefined') document.documentElement.classList.toggle('mica-host', on)
    const w = currentWindow()
    if (!w) return
    try {
      await w.setTheme(mode)
      await w.setEffects(on ? MICA_EFFECTS : null)
    } catch {
      // 能力缺失：窗口保持创建时的样子。
    }
  },
  { immediate: true },
)

/** 根元素跟着主题走 color-scheme，原生 select 弹出层与滚动条才会用对底色。 */
watch(
  themeMode,
  (mode) => {
    if (typeof document !== 'undefined') document.documentElement.style.colorScheme = mode
  },
  { immediate: true },
)
</script>

<template>
  <div class="d5" :class="{ mica }" :data-theme="themeMode">
    <!-- 无边框窗口的缩放热区：4 边 + 4 角，5-10px，按下交给 startResizeDragging -->
    <div class="grips" aria-hidden="true">
      <i v-for="[dir, name] in GRIPS" :key="dir" :class="'g-' + dir" @mousedown.prevent="startResize(name)"></i>
    </div>
    <div class="app">
      <!-- 侧栏 -->
      <aside class="rail">
        <div class="rail-title">{{ tr('appName') }}</div>
        <nav>
          <button class="nav" data-view="presets" :aria-current="String(view === 'presets')" @click="go('presets')">
            <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5.5 3.5h9a1 1 0 0 1 1 1v12l-5.5-3-5.5 3v-12a1 1 0 0 1 1-1z" /></svg>
            <span class="label">{{ tr('presets') }}</span>
          </button>
          <button class="nav" data-view="params" :aria-current="String(view === 'params')" @click="go('params')">
            <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M3 6h14M3 10h14M3 14h9" /></svg>
            <span class="label">{{ tr('params') }}</span>
          </button>
          <button class="nav" data-view="logs" :aria-current="String(view === 'logs')" @click="go('logs')">
            <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2.5" y="3.5" width="15" height="13" rx="2.5" /><path d="M6 8l2 2-2 2M10.5 12h3.5" /></svg>
            <span class="label">{{ tr('logs') }}</span>
          </button>
        </nav>

        <div class="rail-spacer"></div>

        <div class="rail-foot">
          <button class="nav" data-view="market" :aria-current="String(view === 'market')" @click="go('market')">
            <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 6.5h13l-1.2 9a1.6 1.6 0 0 1-1.6 1.4H6.3a1.6 1.6 0 0 1-1.6-1.4z" /><path d="M7 8.5V5.4a3 3 0 0 1 6 0v3.1" /></svg>
            <span class="label">{{ tr('market') }}</span>
          </button>
          <button class="nav" data-view="settings" :aria-current="String(view === 'settings')" @click="go('settings')">
            <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><circle cx="10" cy="10" r="2.6" /><path d="M10 2.6v2M10 15.4v2M2.6 10h2M15.4 10h2M4.8 4.8l1.4 1.4M13.8 13.8l1.4 1.4M15.2 4.8l-1.4 1.4M6.2 13.8l-1.4 1.4" /></svg>
            <span class="label">{{ tr('settings') }}</span>
          </button>
          <button class="nav" data-view="about" :aria-current="String(view === 'about')" @click="go('about')">
            <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><circle cx="10" cy="10" r="7.4" /><path d="M10 9.2v5M10 6.4v.2" /></svg>
            <span class="label">{{ tr('about') }}</span>
          </button>
        </div>

        <div class="rail-tools" :style="{ visibility: showTools ? 'visible' : 'hidden' }">
          <div class="seg" role="group" aria-label="筛选">
            <button type="button" data-filter="all" :aria-pressed="String(filter === 'all')" @click="filter = 'all'">{{ tr('all') }}</button>
            <button type="button" data-filter="changed" :aria-pressed="String(filter === 'changed')" @click="filter = 'changed'">{{ tr('changed') }} <span>{{ dirtyCount }}</span></button>
          </div>
          <button class="textbtn savepreset" type="button" @click="openSave">{{ tr('savePreset') }}</button>
        </div>
      </aside>

      <!-- 主区 -->
      <main class="main">
        <header class="topbar" data-tauri-drag-region>
          <button class="title" data-menu="service" type="button" :title="tr('switchService')" :style="{ opacity: noService ? '.45' : '1' }" @click="toggleMenu('service')">
            <span>{{ selected || '—' }}</span>
            <svg class="chev" width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M6 8l4 4 4-4" /></svg>
          </button>
          <div class="actions">
            <button class="round" type="button" :aria-label="running ? tr('stopSvc') : tr('startSvc')" :title="running ? tr('stopSvc') : tr('startSvc')" :disabled="store.busy.value || noService" @click="primary">
              <svg v-if="running" width="16" height="16" viewBox="0 0 20 20" fill="currentColor"><rect x="5.4" y="5.4" width="9.2" height="9.2" rx="1.6" /></svg>
              <svg v-else width="16" height="16" viewBox="0 0 20 20" fill="currentColor"><path d="M6.6 4.4l9.2 5.6-9.2 5.6z" /></svg>
            </button>
            <button class="ghost" type="button" :title="tr('restartSvc')" :aria-label="tr('restartSvc')" :disabled="noService" @click="openRestart">
              <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M16 10a6 6 0 1 1-1.9-4.4" /><path d="M16 4.2v3.4h-3.4" /></svg>
            </button>
            <button class="ghost" type="button" :title="tr('openDir')" :aria-label="tr('openDir')" :disabled="!appDir" @click="openInstallDir">
              <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6.5A1.5 1.5 0 0 1 4.5 5h3l1.6 2h6.4A1.5 1.5 0 0 1 17 8.5v6A1.5 1.5 0 0 1 15.5 16h-11A1.5 1.5 0 0 1 3 14.5z" /></svg>
            </button>
            <div class="wc">
              <button type="button" :title="tr('minimize')" :aria-label="tr('minimize')" @click="minimize">
                <svg width="12" height="12" viewBox="0 0 12 12" stroke="currentColor" stroke-width="1.2"><path d="M2 6h8" /></svg>
              </button>
              <button type="button" :title="tr('maximize')" :aria-label="tr('maximize')" @click="toggleMaximize">
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.2"><rect x="2.4" y="2.4" width="7.2" height="7.2" rx="1" /></svg>
              </button>
              <button type="button" :title="tr('close')" :aria-label="tr('close')" @click="closeWindow">
                <svg width="12" height="12" viewBox="0 0 12 12" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"><path d="M2.6 2.6l6.8 6.8M9.4 2.6l-6.8 6.8" /></svg>
              </button>
            </div>
          </div>
        </header>
        <div class="rule"></div>

        <section class="content">
          <div class="view" :key="view">
            <ParamsView v-if="view === 'params'" :only-changed="filter === 'changed'" />
            <LogsView v-else-if="view === 'logs'" />
            <PresetsView v-else-if="view === 'presets'" @load="onLoadPreset" @remove="openDelete" @save="openSave" />
            <SettingsView v-else-if="view === 'settings'" />
            <MarketView v-else-if="view === 'market'" />
            <AboutView
              v-else-if="view === 'about'"
              @license="openLicense"
              @params="openParams"
              @check-updates="checkUpdates"
              @nav-updates="go('settings')"
            />
          </div>
        </section>

        <div class="empty" :class="{ show: noService }" aria-hidden="true">
          <svg viewBox="0 0 64 64" fill="currentColor" aria-hidden="true">
            <path d="M14 54 32 12l18 42-8-2.6L32 28.6 22 51.4z" opacity=".9" />
            <path d="M27.2 37.6 44.8 50l3.4-7.2-17-10.6z" opacity=".75" />
          </svg>
        </div>

        <div class="actionbar" :class="{ show: (store.dirty.value || dirtyCount > 0) && !noService }">
          <span>{{ tr('dirtyN', { n: dirtyCount }) }}</span>
          <div class="bar-btns">
            <button class="textbtn" type="button" @click="doRevert">{{ tr('revert') }}</button>
            <button class="pillbtn" type="button" @click="openApply">{{ tr('apply') }}</button>
          </div>
        </div>

        <div v-show="view !== 'logs' && !noService" class="statuspill">
          <span class="sdot" :class="{ ok: status.ok }" aria-hidden="true"></span>
          <span>{{ healthText }}</span>
          <span class="mono">{{ portText }}</span>
        </div>

        <!-- 服务切换 -->
        <div v-if="menu === 'service'" class="menu" style="left: 26px; top: 46px">
          <button v-for="name in store.services.value" :key="name" type="button" :aria-current="String(name === selected)" @click="onPickService(name)">{{ name }}</button>
        </div>
        <!-- 弹层：稿中无静态元素，交互必需 -->
        <div v-if="dialog.kind" class="scrim" @click.self="closeDialog">
          <div class="modal" role="dialog" aria-modal="true">
            <header>
              {{ dialog.kind === 'apply' ? tr('apply')
                : dialog.kind === 'restart' ? tr('restartSvc')
                  : dialog.kind === 'delete' ? tr('del')
                    : dialog.kind === 'save' ? tr('savePreset')
                      : dialog.kind === 'install' ? tr('update')
                        : dialog.kind === 'upd' ? tr('update')
                          : dialog.kind === 'params' ? tr('appParams')
                            : dialog.kind === 'license' ? tr('license')
                              : tr('confirm') }}
            </header>

            <div class="body">
              <template v-if="dialog.kind === 'apply'">
                <p style="margin: 0 0 8px">{{ tr('changes') }}</p>
                <div v-for="field in changedFields" :key="field.key" class="diffrow">
                  <span class="nm">{{ fieldName(field) }}<span class="fl">{{ field.key }}</span></span>
                  <span class="old">{{ svcValues[field.key] || '—' }}</span>
                  <span class="new">{{ store.values.value[field.key] || '—' }}</span>
                </div>
              </template>

              <p v-else-if="dialog.kind === 'restart'" style="margin: 0">{{ tr('restartAsk') }}</p>
              <p v-else-if="dialog.kind === 'guard'" style="margin: 0">
                {{ dialog.guard === 'service' ? tr('guardService', { n: dialog.target }) : tr('guardPreset') }}
              </p>
              <p v-else-if="dialog.kind === 'delete'" style="margin: 0">{{ tr('deleteAsk', { n: dialog.target }) }}</p>

              <p v-else-if="dialog.kind === 'upd'" style="margin: 0">{{ update.error.value || update.statusLine.value }}</p>

              <template v-else-if="dialog.kind === 'install'">
                <p style="margin: 0 0 8px">{{ tr('installAsk') }}</p>
                <pre>{{ update.statusLine.value }}</pre>
                <pre v-if="update.backupPreview.value">{{ update.backupPreview.value }}</pre>
              </template>

              <template v-else-if="dialog.kind === 'save'">
                <p style="margin: 0 0 8px">{{ tr('name') }}</p>
                <input v-model="dialog.name" class="nameinput" type="text" spellcheck="false" @keydown.enter="doSave" />
              </template>

              <pre v-else-if="dialog.kind === 'params'">{{ store.snapshot.snap?.facts?.app_params || '—' }}</pre>
              <pre v-else-if="dialog.kind === 'license'">{{ tr('licenseBody') }}</pre>
            </div>

            <footer>
              <button v-if="dialog.kind === 'guard'" class="textbtn" type="button" @click="discardThen">{{ tr('discard') }}</button>
              <button v-if="dialog.kind === 'guard'" class="pillbtn" type="button" @click="backupThen">{{ tr('backupAndSwitch') }}</button>

              <button v-else-if="dialog.kind === 'apply'" class="pillbtn" type="button" @click="doApply">{{ tr('apply') }}</button>
              <button v-else-if="dialog.kind === 'restart'" class="pillbtn" type="button" @click="doRestart">{{ tr('restartSvc') }}</button>
              <button v-else-if="dialog.kind === 'delete'" class="pillbtn" type="button" @click="doDelete">{{ tr('del') }}</button>
              <button v-else-if="dialog.kind === 'save'" class="pillbtn" type="button" :disabled="!dialog.name.trim()" @click="doSave">{{ tr('savePreset') }}</button>
              <button v-else-if="dialog.kind === 'install'" class="pillbtn" type="button" @click="doInstall">{{ tr('update') }}</button>
              <button v-else-if="dialog.kind === 'upd' && update.canInstall.value" class="pillbtn" type="button" @click="openInstall">{{ tr('update') }}</button>
              <button v-else-if="dialog.kind === 'upd'" class="pillbtn" type="button" @click="closeDialog">{{ tr('close') }}</button>
              <button v-else class="pillbtn" type="button" @click="closeDialog">{{ tr('close') }}</button>

              <button v-if="dialog.kind !== 'params' && dialog.kind !== 'license'" class="textbtn" type="button" @click="dialog.kind === 'install' ? (update.cancelInstall(), closeDialog()) : closeDialog()">{{ tr('cancel') }}</button>
            </footer>
          </div>
        </div>
      </main>
    </div>

    <!-- 自绘下拉的弹出层挂点：必须在 .d5 里（继承主题令牌），又必须在
         .view / .content / 行这些带动画或滚动的祖先之外——fixed 定位的
         包含块会被祖先的 transform 劫持，那正是「点开后界面错乱」的原因。 -->
    <div class="pop-layer"></div>
  </div>
</template>

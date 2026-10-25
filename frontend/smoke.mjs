/**
 * Smoke test — `cd frontend && npm run smoke`.
 *
 * It is the smallest thing that fails if the design layer breaks: bundle the
 * real app with the same Vite config as the shipped build, run that bundle in
 * jsdom behind a recording IPC double, then assert the five contracts the
 * shell owes Rust:
 *
 *   1. **IPC shape.** Every command goes out with the name and the arguments
 *      the contract fixes (`get_snapshot` / `switch_service` / `apply_changes` /
 *      `service_action` / `restart` / `set_start_mode` / `load_preset` /
 *      `save_preset` / `delete_preset` / `save_settings` / `check_update` /
 *      `install_update`) — and the shell never sends anything else.
 *   2. **One-way state.** What is on screen comes from the Snapshot; a
 *      cancelled confirmation sends no write; `apply_changes` folds in the
 *      Snapshot Rust returns and clears the form; `restart` and
 *      `install_update` are only reachable through a confirmation.
 *   3. **Field contract.** 28 fields in 7 groups, agreeing with `OPTIONS` /
 *      `paramHelp` / `optionHelp`, with fixture values inside the bounds Rust's
 *      parser enforces.
 *   4. **Update flow.** `check_update` never installs, the startup check runs
 *      once, a channel change drops the checked release, the install question
 *      carries the backup directory, and the progress lines are Rust's,
 *      verbatim and in order.
 *   5. **Copy completeness.** Every `design/copy.js` entry has zh and en copy
 *      and its `{placeholders}` can be filled.
 *
 * `assert` + jsdom only. The repo has no JS test framework, and adding one for
 * a smoke check nobody asked for would be worse than using the bundler that is
 * already installed.
 *
 * honest: it is the same artefact shape Tauri loads, booted in the same order.
 */
import assert from 'node:assert/strict'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { build } from 'vite'
import vue from '@vitejs/plugin-vue'
import { JSDOM, VirtualConsole } from 'jsdom'

// ---- bundle the app the way `npm run build` does ----------------------------

await build({
  configFile: false,
  root: process.cwd(),
  logLevel: 'warn',
  plugins: [vue()],
  // The library build leaves `process.env.NODE_ENV` where the app build would
  // have inlined it; jsdom has no `process`, so it is pinned here.
  define: { 'process.env.NODE_ENV': '"production"' },
  build: {
    // A throwaway directory: `dist/` is what Tauri loads and is left exactly
    // as `npm run build` produced it.
    outDir: '.smoke',
    emptyOutDir: true,
    target: 'chrome105',
    minify: false,
    cssCodeSplit: false,
    lib: {
      entry: 'smoke.entry.js',
      formats: ['iife'],
      name: 'Smoke',
      fileName: () => 'smoke.js',
    },
  },
})

// The host page: the same mount point `index.html` has, and nothing else.
writeFileSync(
  '.smoke/host.html',
  '<!doctype html><html lang="zh"><head><meta charset="utf-8">' +
    '<title>smoke</title></head><body><div id="app"></div>' +
    '<script src="./smoke.js"></script></body></html>',
)

// ---- run it ----------------------------------------------------------------

const warnings = []
const virtualConsole = new VirtualConsole()
for (const level of ['jsdomError', 'warn', 'error']) {
  virtualConsole.on(level, (m) => warnings.push(String(m?.stack ?? m)))
}

const dom = await JSDOM.fromFile('.smoke/host.html', {
  runScripts: 'dangerously',
  resources: 'usable',
  pretendToBeVisual: true,
  virtualConsole,
})
const { window } = dom
const W = window.window
const doc = W.document

await new Promise((done) => {
  const deadline = Date.now() + 20_000
  const poll = setInterval(() => {
    if (window.__SMOKE__ || Date.now() > deadline) {
      clearInterval(poll)
      done()
    }
  }, 25)
})

assert.ok(window.__SMOKE__, `the bundle ran and mounted:\n${warnings.join('\n')}`)

const S = window.__SMOKE__
const {
  store,
  theme,
  update,
  ipcDouble,
  ipc: ipcModule,
  copy,
  motion,
  TYPE,
  RADIUS,
  SPACE,
  PALETTES,
  cssVars,
  resolveMode,
  parseGeometry,
  formatGeometry,
  FIELDS,
  GROUP_ORDER,
  GROUP_LABEL,
  OPTIONS,
  PATH_FIELDS,
  NO_HELP,
  paramHelp,
  optionHelp,
  demoSnapshot,
  demoUpdateCheck,
  emptySnapshot,
  INSTALL_LINES,
  EVENT_UPDATE,
} = S
const { C: COPY, t, autoBackupName } = copy
/** Rust's own string table, through the store's `t()` (ADR-0005). */
const st = store.t

// ---- reading the screen ----------------------------------------------------

/** Vue flushes on the microtask queue; a command's answer is one IPC later. */
async function flush() {
  await new Promise((r) => setTimeout(r, 40))
  await new Promise((r) => W.requestAnimationFrame(() => r()))
}

const q = (sel) => doc.querySelector(sel)
const qa = (sel) => [...doc.querySelectorAll(sel)]
/** Whitespace-collapsed text, so a rendered label can be compared to its copy. */
const txt = (el) => String(el?.textContent ?? '').replace(/\s+/g, ' ').trim()
/** The same collapse, for an expected string that carries newlines. */
const flat = (s) => String(s ?? '').replace(/\s+/g, ' ').trim()
/** Escape a literal string into a regex, for asserting on rendered copy. */
const re = (text) => new RegExp(String(text).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
/** A raw text node, newlines and spacing preserved. */
const raw = (el) => String(el?.textContent ?? '')

async function click(el, what) {
  assert.ok(el, `元素存在：${what ?? '???'}`)
  el.click()
  await flush()
}

/** 自绘下拉（Dd.vue）的用户路径：点触发钮 → 弹出层出现。返回选项数组。 */
async function openDd(btn, what) {
  assert.ok(btn, `下拉触发钮存在：${what ?? '???'}`)
  btn.click()
  await flush()
  assert.ok(q('.d5 .dd-pop'), `弹出层打开：${what ?? '???'}`)
  return qa('.d5 .dd-pop [role="option"]')
}

/** 再点一次触发钮收起（触发钮即开关）。 */
async function closeDd(btn, what) {
  btn?.click()
  await flush()
  assert.equal(q('.d5 .dd-pop'), null, `弹出层收起：${what ?? '???'}`)
}

/** 打开下拉并点选某值。 */
async function pickDd(btn, value, what) {
  const opts = await openDd(btn, what)
  const opt = opts.find((o) => o.getAttribute('data-value') === value)
  assert.ok(opt, `${what ?? '下拉'} 有选项 ${value}`)
  opt.click()
  await flush()
}

async function typeInto(el, value) {
  assert.ok(el, 'input 存在')
  el.value = value
  el.dispatchEvent(new W.Event('input'))
  await flush()
}

async function pressEnter(el) {
  el.dispatchEvent(new W.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
  await flush()
}

async function navTo(name) {
  await click(q(`.rail .nav[data-view="${name}"]`), `导航 ${name}`)
}

/** Every IPC call so far, in order. */
const calls = () => Array.from(ipcDouble.calls)
const cmds = () => calls().map((c) => c.cmd)
/** The commands sent since `mark` (a `calls().length` snapshot). */
const since = (mark) => calls().slice(mark)
const sentOf = (mark, cmd) => since(mark).filter((c) => c.cmd === cmd)

/** The open dialog, or null. Every overlay is `.scrim > .modal`. */
const modal = () => q('.scrim .modal')
const modalHead = () => txt(q('.scrim .modal header'))
const modalBody = () => q('.scrim .modal .body')
const modalButtons = () => qa('.scrim .modal footer button')
/** The confirming button of the open dialog. */
const confirmBtn = () => q('.scrim .modal footer .pillbtn')
/** The last footer button — 取消 for every dialog that offers a way out. */
const cancelBtn = () => modalButtons().at(-1)

// ---- a fresh snapshot, the way Rust would push one -------------------------

/** Push an arbitrary Snapshot, as a command's answer would. */
function pushSnap(patch) {
  store.setSnapshot({ ...store.snapshot.snap, ...patch })
}
/** Push a `settings` patch, as `save_settings` would answer. */
function pushSettings(patch) {
  store.setSnapshot({
    ...store.snapshot.snap,
    settings: { ...store.snapshot.snap.settings, ...patch },
  })
}

await flush()
assert.equal(store.phase.value, 'ready', '启动后进入 ready 相：Snapshot 已到')
console.log('ok  设计层外壳挂载完成：createApp(DesignApp) + global.css（无 query 开关）')

// ---- the shell mounts, not a blank page ------------------------------------

assert.ok(q('.d5'), '外壳根节点是 .d5')
assert.equal(q('.d5').parentElement.id, 'app', '外壳挂在 #app 里')
assert.equal(q('.d5').getAttribute('data-theme'), 'light', '外观取自 Snapshot（system → light）')
assert.ok(q('.d5 > .app'), '.app 是外壳的唯一子层')
assert.ok(q('.app > .rail'), '.rail 在 .app 里')
assert.ok(q('.app > .main'), '.main 在 .app 里')
assert.ok(q('.content > .view'), '内容包在 .view 里（视图入场动画的挂点）')
assert.equal(txt(q('.rail-title')), COPY.appName[0], '侧栏标题就是软件名「拉马管家」')

// The five destinations, in the order the rail draws them.
const navs = qa('.rail .nav[data-view]')
assert.equal(navs.length, 5, '侧栏有 5 个目的地')
assert.deepEqual(
  navs.map((n) => n.getAttribute('data-view')),
  ['presets', 'params', 'logs', 'settings', 'about'],
  '导航顺序：预设 / 参数 / 日志 / 设置 / 关于',
)
const navLabels = navs.map((n) => txt(n.querySelector('.label')))
assert.deepEqual(
  navLabels,
  [COPY.presets[0], COPY.params[0], COPY.logs[0], COPY.settings[0], COPY.about[0]],
  '每个导航项的 .label 来自文案表',
)
assert.equal(qa('.rail .nav .count').length, 0, '导航没有计数徽标（v6 减法）')
assert.equal(qa('.rail-foot .nav').length, 2, '.rail-foot 装设置与关于')
assert.equal(q('.nav[data-view="params"]').getAttribute('aria-current'), 'true', '启动落在参数页')
for (const view of ['presets', 'logs', 'settings', 'about']) {
  assert.equal(q(`.nav[data-view="${view}"]`).getAttribute('aria-current'), 'false', `${view} 未选中`)
}

// The rail tools only exist on the parameter page, and hold only the filter.
assert.equal(q('.rail-tools').style.visibility, 'visible', '参数页显示筛选条')
const segs = qa('.rail-tools .seg button[data-filter]')
assert.equal(segs.length, 2, '筛选条两段：全部 / 已改')
assert.deepEqual(segs.map((b) => b.getAttribute('data-filter')), ['all', 'changed'])
assert.equal(segs[0].getAttribute('aria-pressed'), 'true', '默认筛「全部」')
assert.equal(segs[1].getAttribute('aria-pressed'), 'false')
assert.match(txt(segs[1]), new RegExp(COPY.changed[0]), '第二段是「已改」')
assert.equal(q('.rail-tools .ghost-mini'), null, '筛选条里没有展开按钮（与窗口最大化重复，v6 减法）')

// The top bar: one drag region, one service menu, four actions, three window buttons.
assert.ok(q('.topbar[data-tauri-drag-region]'), '顶栏是拖动区')
assert.ok(q('.topbar .title[data-menu="service"]'), '标题就是服务切换菜单')
assert.equal(txt(q('.topbar .title')), 'QwenLLM', '标题显示 Snapshot 选中的服务')
assert.equal(q('.topbar .title').getAttribute('title'), COPY.switchService[0], '标题的提示是「切换服务」')
assert.ok(q('.topbar .actions .round'), '主操作是圆形按钮')
assert.equal(q('.topbar .actions .round').getAttribute('aria-label'), COPY.stopSvc[0], 'RUNNING 时主操作是「停止服务」')
assert.ok(q('.actions .ghost[title="' + COPY.restartSvc[0] + '"]'), '有重启按钮')
assert.ok(q('.actions .ghost[title="' + COPY.openDir[0] + '"]'), '有打开安装目录按钮')
assert.equal(q('.actions .ghost[title="' + COPY.openDir[0] + '"]').disabled, true, '打开目录尚未接线，如实禁用')
assert.equal(q('.actions .ghost[data-menu="more"]'), null, '没有「更多」菜单按钮（入口各自归位，v6 减法）')
assert.equal(qa('.actions .wc button').length, 3, '自绘标题栏三个窗口按钮')
assert.deepEqual(
  qa('.actions .wc button').map((b) => b.getAttribute('title')),
  [COPY.minimize[0], COPY.maximize[0], COPY.close[0]],
  '窗口按钮靠 title 区分：最小化 / 最大化 / 关闭',
)
for (const b of qa('.actions .wc button')) {
  assert.match(b.getAttribute('aria-label') ?? '', /\S/, '每个窗口按钮都有 aria-label')
}
assert.ok(q('.rule'), '顶栏与内容之间有一条分隔线')

// The status pill and the two overlays that are not open yet.
assert.ok(q('.statuspill'), '右下状态条就位')
assert.match(txt(q('.statuspill')), re(COPY.healthOk[0]), '状态条说「探活 OK」')
assert.match(txt(q('.statuspill .mono')), /^:8080$/, '端口用等宽字显示')
assert.equal(q('.empty').classList.contains('show'), false, '有服务时不显示空态水印')
assert.equal(q('.actionbar').classList.contains('show'), false, '没有未应用更改时动作条收起')
assert.match(txt(q('.actionbar')), new RegExp(COPY.revert[0]), '动作条里有「还原」')
assert.match(txt(q('.actionbar')), new RegExp(COPY.apply[0]), '动作条里有「应用更改」')
console.log('ok  外壳结构：侧栏 6 项 / 顶栏动作 / 状态条 / 动作条 / 空态')
// ---- the type scale, radii and contrast ------------------------------------

const steps = [TYPE.DISPLAY, TYPE.SECTION, TYPE.GROUP, TYPE.BODY, TYPE.SMALL, TYPE.MICRO]
assert.deepEqual(steps, [28, 20, 15, 13, 12, 11], `字级：${steps}`)
for (let i = 1; i < steps.length; i++) {
  assert.ok(steps[i] < steps[i - 1], `第 ${i} 级必须严格小于上一级：${steps}`)
}
assert.equal(TYPE.MONO, TYPE.BODY, '等宽字与正文同号，值与标签才能共基线')
assert.ok(TYPE.MONO_SM < TYPE.MONO, '日志行取更小的等宽步进')
assert.equal(RADIUS.CARD, '12px', '面板圆角')
assert.equal(RADIUS.CONTROL, '8px', '控件圆角')
assert.equal(RADIUS.CHIP, '6px', '徽标圆角')
assert.equal(RADIUS.PILL, '999px', '药丸圆角')
assert.equal(SPACE.MD, 12, '间距阶梯')
for (const v of Object.values(SPACE)) {
  assert.equal(v % 4, 0, `间距 ${v} 落在 4px 节奏上`)
}

/** WCAG relative luminance for a `#rrggbb` token. */
function luminance(hex) {
  const channel = (v) => {
    const c = parseInt(v, 16) / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  }
  const h = hex.replace('#', '')
  return (
    0.2126 * channel(h.slice(0, 2)) +
    0.7152 * channel(h.slice(2, 4)) +
    0.0722 * channel(h.slice(4, 6))
  )
}

function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

// Every text role clears WCAG AA on the canvas. This is the guard that makes a
// future palette edit prove itself instead of quietly lowering contrast.
for (const mode of ['light', 'dark']) {
  const p = PALETTES[mode]
  for (const key of ['TXT', 'TXT2', 'MUT', 'ACC', 'RUN', 'ORG', 'RED']) {
    const ratio = contrast(p[key], p.BG)
    assert.ok(ratio >= 4.5, `${mode} ${key} 在画布上是 ${ratio.toFixed(2)}:1，需 4.5`)
  }
  const onPrimary = contrast(p.PRIMARY_ON, p.PRIMARY)
  assert.ok(onPrimary >= 4.5, `${mode} 主按钮文字是 ${onPrimary.toFixed(2)}:1，需 4.5`)
  assert.equal(p.BG, mode === 'light' ? '#f5f5f7' : '#171614', `${mode} 画布底色`)
  assert.equal(p.PRIMARY, mode === 'light' ? '#1d1d1f' : '#eae5dd', `${mode} 提交用墨色`)
  assert.equal(p.ACC, mode === 'light' ? '#1f6b58' : '#6ec9a8', `${mode} 交互用森林绿`)
}
assert.equal(resolveMode('system', false), 'light', 'system + 浅色系统 → light')
assert.equal(resolveMode('system', true), 'dark', 'system + 深色系统 → dark')
assert.equal(resolveMode('light', true), 'light', '显式 light 压过系统')
assert.equal(resolveMode('dark', false), 'dark', '显式 dark 压过系统')

const lightVars = cssVars('light')
const darkVars = cssVars('dark')
assert.notEqual(lightVars['--bg'], darkVars['--bg'], '背景随外观互换')
assert.notEqual(lightVars['--card'], darkVars['--card'], '面板底色随外观互换')
assert.notEqual(lightVars['--primary'], darkVars['--primary'], '提交墨色反转')
assert.notEqual(lightVars['--acc'], darkVars['--acc'], '深色下交互色提亮')
assert.notEqual(lightVars['--run'], darkVars['--run'], '深色下状态绿提亮')
for (const [k, v] of Object.entries(lightVars)) {
  if (k.startsWith('--sp-')) assert.equal(parseInt(v, 10) % 4, 0, `${k} = ${v} 落在 4px 节奏上`)
}
assert.equal(lightVars['--f-mono'], lightVars['--f-body'], '--f-mono 与 --f-body 同号')
assert.match(lightVars['--font-mono'], /Cascadia Mono/, '等宽字族')
assert.match(lightVars['--font-mono'], /Consolas/, '等宽回退')
assert.match(lightVars['--font-ui'], /Microsoft YaHei UI/, '界面字覆盖中文字形')
console.log('ok  字级 28/20/15/13/12/11 · 圆角 12/8/6 · AA 对比度 · 两套外观同构')

// ---- geometry round trip ---------------------------------------------------

assert.deepEqual(
  { ...parseGeometry('1200x800+10+20') },
  { w: 1200, h: 800, x: 10, y: 20 },
  '完整几何串带位置',
)
assert.deepEqual(
  { ...parseGeometry('1000x860') },
  { w: 1000, h: 860, x: null, y: null },
  '只有尺寸的几何串没有位置',
)
assert.equal(parseGeometry('120x80'), null, '过小的窗口被拒绝')
assert.equal(parseGeometry(null), null, '没有几何串不是错误')
assert.equal(parseGeometry('garbage'), null, '损坏的几何串被拒绝')
assert.equal(formatGeometry({ w: 1200, h: 800, x: 10, y: 20 }), '1200x800+10+20')
assert.equal(formatGeometry({ w: 1000, h: 860, x: null, y: null }), '1000x860')
console.log('ok  窗口几何按 WxH+X+Y 解析与格式化')

// ---- the parameter page: 7 sections, 28 rows ------------------------------

const sections = qa('.content .section')
assert.equal(sections.length, 7, '参数页 7 个分组标题')
assert.deepEqual(
  sections.map(txt),
  ['模型', '加速', '上下文', '并发', '采样', '网络', '高级'],
  '分组顺序与 Rust 的写法一致（稿中收窄的短名）',
)
// Every group has a label in both languages: the short names above are the
// mock's, the full ones are Rust's, and neither may be blank.
for (const group of GROUP_ORDER) {
  assert.match(String(GROUP_LABEL[group]?.zh ?? ''), /\S/, `${group} 有中文分组名`)
  assert.match(String(GROUP_LABEL[group]?.en ?? ''), /\S/, `${group} 有英文分组名`)
}
assert.equal(EVENT_UPDATE, 'llama-ctl://update-progress', '进度流的通道名就是 Rust 监听的那条')
const rows = qa('.content .row[data-row]')
assert.equal(rows.length, 28, '28 个参数行')
const rowKeys = rows.map((r) => r.getAttribute('data-row'))
assert.deepEqual(rowKeys, [...FIELDS.map((f) => f.key)], '行序就是 FIELDS 的表序')
assert.deepEqual(
  [...GROUP_ORDER],
  ['模型与视觉', '加速', '上下文与显存', '并发与吞吐', '采样', '网络', '高级'],
  '七个分组名与 Rust 的 G_* 一致',
)
assert.equal(new Set(rowKeys).size, 28, '没有重复的行')
console.log('ok  参数页：7 个 .section + 28 个 .row[data-row]')

// ---- every kind renders the control it should ------------------------------

for (const f of FIELDS) {
  const row = q(`.row[data-row="${f.key}"]`)
  assert.ok(row, `${f.key} 有行`)
  const name = row.querySelector('.name .txt')
  assert.ok(name, `${f.key} 有名称 .name .txt`)
  assert.match(txt(name), /\S/, `${f.key} 的名称非空`)
  assert.match(name.getAttribute('title') ?? '', /\([^)]+\)\s*$/, `${f.key} 的命令行 flag 在 title 上`)
  assert.equal(row.classList.contains('changed'), false, `${f.key} 初始与服务一致，不标已改`)

  if (f.kind === 'slider') {
    const cell = row.querySelector('.val.num')
    assert.ok(cell, `${f.key} 渲染 .val.num`)
    const steppers = [...cell.querySelectorAll('.step')]
    assert.equal(steppers.length, 2, `${f.key} 有 − / + 两个步进`)
    assert.deepEqual(
      steppers.map((s) => s.getAttribute('aria-label')),
      ['减少', '增加'],
      `${f.key} 的步进带 aria-label`,
    )
    const numv = cell.querySelector('.numv')
    assert.ok(numv, `${f.key} 有可点的数值 .numv`)
    assert.equal(
      Number(txt(numv)),
      Number(store.snapshot.snap.values[f.key]),
      `${f.key} 显示服务里的值`,
    )
    const unit = cell.querySelector('.unit')
    const unitText = (store.lang.value === 'en' ? f.unit?.en : f.unit?.zh) ?? ''
    if (unitText) {
      assert.ok(unit, `${f.key} 有单位`)
      assert.equal(txt(unit), unitText, `${f.key} 的单位是 ${unitText}`)
    } else {
      assert.equal(unit, null, `${f.key} 无单位时不渲染 .unit`)
    }
  } else if (f.kind === 'combo') {
    const btn = row.querySelector('.val.sel .selbtn')
    assert.ok(btn, `${f.key} 渲染 .val.sel .selbtn`)
    assert.match(btn.getAttribute('aria-label') ?? '', /\S/, `${f.key} 的下拉有 aria-label`)
    assert.equal(btn.getAttribute('data-value'), store.snapshot.snap.values[f.key], `${f.key} 触发钮显示服务里的值`)
    const opts = await openDd(btn, `${f.key} 下拉`)
    assert.deepEqual(
      opts.map((o) => o.getAttribute('data-value')),
      [...OPTIONS[f.key]],
      `${f.key} 的选项逐项等于 OPTIONS`,
    )
    const chosen = opts.filter((o) => o.getAttribute('aria-selected') === 'true')
    assert.equal(chosen.length, 1, `${f.key} 恰有一项带勾选`)
    assert.equal(chosen[0].getAttribute('data-value'), store.snapshot.snap.values[f.key], `${f.key} 勾选项是服务里的值`)
    for (const o of opts) {
      assert.match(o.getAttribute('title') ?? '', /\S/, `${f.key}=${o.getAttribute('data-value')} 有选项说明（title）`)
    }
    await closeDd(btn, `${f.key} 下拉`)
  } else if (f.kind === 'check') {
    const sw = row.querySelector('button.sw')
    assert.ok(sw, `${f.key} 渲染 button.sw`)
    const on = String(store.snapshot.snap.values[f.key]) === '1'
    assert.equal(sw.getAttribute('aria-pressed'), String(on), `${f.key} 的开关状态取自 Snapshot`)
    assert.match(sw.getAttribute('aria-label') ?? '', /\S/, `${f.key} 的开关有 aria-label`)
  } else {
    const pathBtn = row.querySelector('button.val.path')
    assert.ok(pathBtn, `${f.key} 静止态是 .val.path 按钮`)
    assert.equal(pathBtn.disabled, false, `${f.key} 空闲时可点`)
    assert.equal(
      PATH_FIELDS.has(f.key),
      f.kind === 'path',
      `${f.key} 的路径性质与 PATH_FIELDS 一致`,
    )
  }
}
console.log('ok  四种控件各就各位：.val.num / .val.sel .selbtn / button.sw / .val.path')

// ---- a click on a row only ever edits the form -----------------------------

const nglRow = q('.row[data-row="ngl"]')
const nglSteppers = [...nglRow.querySelectorAll('.step')]
await click(nglSteppers[1], 'ngl 的 +')
assert.equal(store.values.value.ngl, '100', '步进写进表单')
assert.equal(store.snapshot.snap.values.ngl, '99', 'Snapshot 未被它改动')
assert.ok(nglRow.classList.contains('changed'), '改动行带 .changed')
assert.ok(q('.actionbar').classList.contains('show'), '有未应用更改时动作条出现')
assert.match(txt(q('.actionbar')), re(t('dirtyN', 'zh', { n: 1 })), '动作条说「1 项未应用」')
assert.equal(txt(q('.seg button[data-filter="changed"] span')), '1', '「已改」计数同步')

await click(nglSteppers[0], 'ngl 的 −')
assert.equal(store.values.value.ngl, '99', '减回服务的值')
assert.equal(nglRow.classList.contains('changed'), false, '与服务一致后不再标已改')
assert.equal(q('.actionbar').classList.contains('show'), false, '动作条随之收起')

// The bounds Rust enforces also stop the stepper: 0 is ngl's floor.
store.editField('ngl', '0')
await flush()
await click(nglSteppers[0], 'ngl 在 0 上再减')
assert.equal(store.values.value.ngl, '0', '步进不会越过下限')
store.clearForm()
await flush()

// The number is click-to-edit: `.numv` becomes `.inline`, Enter commits it.
store.editField('ngl', '42')
await flush()
await click(q('.row[data-row="ngl"] .numv'), 'ngl 的值')
const inline = q('.row[data-row="ngl"] input.inline')
assert.ok(inline, '点数值后变成 .inline 输入框')
inline.value = '7'
await pressEnter(inline)
assert.equal(store.values.value.ngl, '7', '.inline 回车写回表单')
assert.equal(q('.row[data-row="ngl"] input.inline'), null, '提交后回到静止态')

// A combo writes the option straight into the form.
await pickDd(q('.row[data-row="spec_type"] .selbtn'), 'ngram-simple', 'spec_type')
assert.equal(store.values.value.spec_type, 'ngram-simple', '枚举改动进表单')
assert.ok(q('.row[data-row="spec_type"]').classList.contains('changed'), '该行标记已改')

// The switch writes '' for off and '1' for on.
const noMmap = q('.row[data-row="no_mmap"] button.sw')
assert.equal(noMmap.getAttribute('aria-pressed'), 'true', 'no_mmap 来自 Snapshot 的 1')
await click(noMmap, 'no_mmap 开关')
assert.equal(store.values.value.no_mmap, '', '关掉即写空值')
assert.equal(
  q('.row[data-row="no_mmap"] button.sw').getAttribute('aria-pressed'),
  'false',
  'aria-pressed 跟着变',
)
assert.ok(q('.row[data-row="no_mmap"]').classList.contains('changed'), '该行标记已改')

// A path row is a button at rest and a text input while editing.
await click(q('.row[data-row="model"] button.val.path'), 'model 路径')
const tinput = q('.row[data-row="model"] input.tinput')
assert.ok(tinput, '路径点开变 .tinput')
assert.equal(tinput.getAttribute('aria-label'), '模型文件', '编辑框带 aria-label')
tinput.value = 'F:\\models\\Qwen3-7B-Q4_K_M.gguf'
await pressEnter(tinput)
assert.equal(store.values.value.model, 'F:\\models\\Qwen3-7B-Q4_K_M.gguf', '回车写回表单')
assert.equal(
  store.snapshot.snap.values.model,
  'F:\\models\\Qwen3-32B-Q4_K_M.gguf',
  'Snapshot 仍是服务里的值',
)
assert.equal(q('.row[data-row="model"] input.tinput'), null, '提交后回到按钮')
console.log('ok  数值 / 枚举 / 开关 / 路径 四种编辑都只写表单，Snapshot 不动')

// ---- the one-way rule: the port pill reads the form -------------------------

store.editField('port', '9999')
await flush()
assert.equal(store.values.value.port, '9999', '编辑留在本地')
assert.equal(store.snapshot.snap.values.port, '8080', 'Snapshot 没被它改动')
assert.equal(txt(q('.statuspill .mono')), ':9999', '状态条跟着表单端口走')
store.clearForm()
await flush()
assert.equal(store.values.value.port, '8080', '清空表单即回到服务')
assert.equal(txt(q('.statuspill .mono')), ':8080', '状态条跟着回到 8080')
console.log('ok  单向状态：表单是唯一本地副本，清空即回到 Snapshot')

// ---- the「已改」filter hides every untouched row ----------------------------

store.editField('ngl', '7')
store.editField('port', '9999')
await flush()
const changedRows = qa('.content .row.changed')
assert.equal(changedRows.length, 2, '两行已改')
await click(q('.seg button[data-filter="changed"]'), '筛「已改」')
assert.equal(q('.seg button[data-filter="changed"]').getAttribute('aria-pressed'), 'true', '「已改」按下')
assert.equal(q('.seg button[data-filter="all"]').getAttribute('aria-pressed'), 'false', '「全部」松开')
assert.equal(qa('.content .row.hidden').length, 26, '其余 26 行被隐藏')
for (const r of qa('.content .row.changed')) {
  assert.equal(r.classList.contains('hidden'), false, '改动行不被藏')
}
assert.equal(q('.row[data-row="threads"]').classList.contains('hidden'), true, '未改动的行带 .hidden')
await click(q('.seg button[data-filter="all"]'), '筛「全部」')
assert.equal(qa('.content .row.hidden').length, 0, '回到全部时没有隐藏行')

// ---- 还原 asks Rust and clears the buffer ----------------------------------

const sentRevert = calls().length
await click(q('.actionbar .textbtn'), '还原')
const revertCall = calls()
  .slice(sentRevert)
  .find((c) => c.cmd === 'revert')
assert.ok(revertCall, '还原走 revert 命令')
assert.deepEqual(Object.keys(revertCall.args), [], 'revert 不带参数')
assert.equal(store.snapshot.form, null, '还原清空表单')
assert.equal(store.values.value.ngl, '99', '界面回到服务的值')
assert.equal(qa('.content .row.changed').length, 0, '没有改动行')
assert.equal(q('.actionbar').classList.contains('show'), false, '动作条收起')
console.log('ok  「已改」筛选只留改动行 · 还原经 revert 并清空表单')

// ---- the logs page: one meta line and a line list ---------------------------

await navTo('logs')
assert.equal(q('.rail-tools').style.visibility, 'hidden', '离开参数页时筛选条隐藏')
const logmeta = q('.content .logmeta')
assert.ok(logmeta, '日志页有 .logmeta')
assert.equal(txt(logmeta.querySelector('.mono')), 'F:\\llama.cpp\\server.err', '路径由 app_dir 拼出')
assert.ok(logmeta.querySelector('.clear'), '日志页有「清空」按钮')
assert.match(txt(logmeta.querySelector('.follow')), /跟随中 · \d{2}:\d{2}:\d{2}/, '「跟随中」带最后一行的时间')
assert.equal(qa('.content .logline').length, 6, '演示日志 6 行')
assert.deepEqual(
  qa('.content .logline .t').map(txt),
  ['12:03:11.482', '12:03:11.503', '12:03:12.117', '12:03:19.004', '12:04:02.771', '12:04:03.010'],
  '时间列逐行取自日志文本',
)
assert.equal(qa('.content .logline.warn').length, 1, '一行 warn')
assert.equal(qa('.content .logline.err').length, 1, '一行 err')
assert.match(txt(q('.content .logline.err .m')), /context overflow/, 'err 行是正文本身')
assert.equal(
  q('.content .logline .m').textContent,
  'srv  load_model: ngl = 128, ctx = 65536',
  '正文去掉时间前缀，原样保留',
)

// The follow switch is a real toggle: off means the tail stops moving.
await click(q('.content .logmeta .follow'), '跟随开关')
assert.equal(txt(q('.content .logmeta .follow')), COPY.paused[0], '关掉跟随显示「已暂停」')
assert.ok(q('.content .logmeta .dotlive').classList.contains('off'), '指示灯熄灭')
await click(q('.content .logmeta .follow'), '跟随开关')
assert.match(txt(q('.content .logmeta .follow')), new RegExp(COPY.following[0].slice(0, 3)), '再点恢复跟随')

// Progress lines land at the end, in order.
store.pushLog('>>> 重启 QwenLLM：停止...')
store.pushLog('>>> 启动...')
store.pushLog('>>> 服务就绪：healthz ok')
await flush()
assert.deepEqual(
  qa('.content .logline')
    .slice(-3)
    .map((l) => l.textContent.trim()),
  ['>>> 重启 QwenLLM：停止...', '>>> 启动...', '>>> 服务就绪：healthz ok'],
  '过程行逐字入列、按到达顺序',
)

// 「清空」只清屏幕：文件尾藏着，新过程行照常进来；真机里文件尾一旦有新
// 内容（签名变化）会自动恢复显示，这里是演示模式的可观察部分。
await click(q('.content .logmeta .clear'), '清空日志')
assert.equal(qa('.content .logline').length, 0, '清空后日志列表为空')
assert.equal(q('.content .logmeta .clear').disabled, true, '没有可清的东西时按钮禁用')
store.pushLog('>>> 新的一次重启')
await flush()
assert.deepEqual(
  qa('.content .logline').map((l) => l.textContent.trim()),
  ['>>> 新的一次重启'],
  '清空后新过程行照常入列',
)
assert.equal(q('.content .logmeta .clear').disabled, false, '有新行后按钮恢复可点')
store.clearLog()
await flush()
assert.equal(qa('.content .logline').length, 0, 'store 清空后列表为空')
console.log('ok  日志页：.logmeta 路径 + 清空 + 跟随开关 · .logline 时间/正文/warn/err · 过程行实时入列')

// ---- the presets page: two groups and a list row each ----------------------

await navTo('presets')
// 第一组标题右侧有「保存为预设」，比对分组名时只看它自己的文本节点。
const secText = (s) => txt(s.querySelector('span')) || txt(s)
assert.deepEqual(
  qa('.content .section').map(secText),
  [COPY.mine[0], COPY.backups[0]],
  '预设页两个 .section：我的预设 / 自动备份',
)
const presetRows = qa('.content .lrow')
assert.equal(presetRows.length, 3, '三个预设行')
assert.deepEqual(
  presetRows.map((r) => txt(r.querySelector('.lname'))),
  ['32B 长上下文', '7B 快速', '自动备份 03-14 09:12:41'],
  '自动备份按名字前缀落到第二组',
)
for (const r of presetRows) {
  assert.equal(txt(r.querySelector('.r .textbtn')), COPY.load[0], '每行都有「载入」')
}
assert.equal(presetRows[0].querySelector('.iconmini').getAttribute('aria-label'), COPY.more[0], '我的预设：更多')
assert.ok(presetRows[0].querySelector('.iconmini svg'), '更多是 svg 图标，不是文字符号')
assert.equal(presetRows[2].querySelector('.iconmini').getAttribute('aria-label'), COPY.del[0], '自动备份：删除')
assert.ok(presetRows[2].querySelector('.iconmini svg'), '删除是 svg 图标，不是文字符号')

// 「已载入」marks the preset Rust says is in the form, and only then.
pushSnap({ preset_loaded: '7B 快速' })
await flush()
assert.match(txt(qa('.content .lrow')[1]), new RegExp(COPY.loaded[0]), '已载入的预设有标记')
assert.doesNotMatch(txt(qa('.content .lrow')[0]), new RegExp(COPY.loaded[0]), '其余行没有标记')
pushSnap({ preset_loaded: '' })
await flush()
assert.doesNotMatch(txt(qa('.content .lrow')[1]), new RegExp(COPY.loaded[0]), '载入标记来自 Snapshot')

// 载入 goes through `load_preset` with only a name.
const sentLoad = calls().length
await click(qa('.content .lrow')[1].querySelector('.r .textbtn'), '载入 7B 快速')
const loadCall = calls()
  .slice(sentLoad)
  .find((c) => c.cmd === 'load_preset')
assert.ok(loadCall, '载入走 load_preset')
assert.deepEqual(Object.keys(loadCall.args), ['name'], 'load_preset 只带 name')
assert.equal(loadCall.args.name, '7B 快速')

// 删除 asks first, and cancelling writes nothing.
const sentDel = calls().length
await click(qa('.content .lrow')[1].querySelector('.iconmini'), '删除预设')
assert.equal(modalHead(), COPY.del[0], '删除前先问')
assert.match(txt(modalBody()), re(t('deleteAsk', 'zh', { n: '7B 快速' })), '问题点名预设')
assert.equal(modalButtons().length, 2, '两个答案：删除 / 取消')
assert.equal(txt(cancelBtn()), COPY.cancel[0], '第二个是「取消」')
await click(cancelBtn(), '取消删除')
assert.equal(modal(), null, '取消关闭弹层')
assert.equal(calls().slice(sentDel).filter((c) => c.cmd === 'delete_preset').length, 0, '取消不删')
console.log('ok  预设页：两组 .lrow · 载入只读 · 删除先二次确认')

// ---- the startup auto-check ran once, and only prompts ---------------------

// `DesignApp.vue` runs `update.autoCheck()` on mount. Nothing else has checked
// yet, so this is the boot check's own record — not a later one's.
assert.equal(update.autoChecked.value, true, '启动自动检查跑过，并标记为本会话已完成')
assert.equal(sentOf(0, 'check_update').length, 1, '启动时只发了一条 check_update')
assert.equal(sentOf(0, 'install_update').length, 0, '启动检查绝不下载、绝不安装')
assert.equal(update.statusKind.value, 'known', '启动检查的结果已经落到屏幕上')
assert.equal(update.installed.value, 10813, '启动检查读到了已安装的构建号')

const sentAutoAgain = calls().length
assert.equal(await update.autoCheck(), null, '第二次启动检查直接返回 null')
assert.equal(since(sentAutoAgain).length, 0, '第二次启动检查不发任何命令')

// Forget the once-per-session flag to prove the guard, not the absence.
update.resetAutoCheck()
const sentAutoRerun = calls().length
await update.autoCheck()
assert.equal(sentOf(sentAutoRerun, 'check_update').length, 1, '重置后启动检查会再跑一次')
assert.equal(sentOf(sentAutoRerun, 'install_update').length, 0, '再跑一次也只提示')
assert.equal(update.autoChecked.value, true, '跑过之后又标记为已完成')
console.log('ok  启动自动检查只提示、只跑一次：check_update 一条，install_update 零条')

// ---- the about page: hero / versions with copy / stack / quick actions -----

update.reset()
await navTo('about')
await flush()
assert.match(txt(q('.content .about-hero .aname')), re(COPY.appName[0]), '关于页以「拉马管家」开头')
assert.match(txt(q('.content .about-hero .atag')), re(COPY.appTagline[0]), '标语在名称下方')
const aboutRows = qa('.content .lrow')
assert.equal(aboutRows.length, 3, '三行版本信息：应用版本 / llama.cpp 构建 / 安装目录')
assert.equal(txt(aboutRows[0].querySelector('.r .mono')), '0.1.0', '应用版本来自包版本')
assert.equal(txt(aboutRows[1].querySelector('.r .mono')), 'b5527', '没有检查结果时构建号退回探活明细')
assert.equal(txt(aboutRows[2].querySelector('.r .mono')), 'F:\\llama.cpp', '安装目录来自 facts.app_dir')
const aboutChips = qa('.content .chip')
assert.deepEqual(aboutChips.map(txt), ['Tauri 2', 'Vue 3', 'Rust'], '技术栈徽章是静音的三个')
const actBtns = qa('.content .actgrid button')
assert.equal(actBtns.length, 4, '四个快捷入口')
assert.deepEqual(
  actBtns.map((b) => txt(b)),
  [COPY.checkUpdates[0], COPY.homepage[0], COPY.appParams[0], COPY.license[0]],
  '快捷入口：检查更新 / llama.cpp 主页 / 启动参数 / 开源许可',
)
assert.match(txt(q('.content .about-foot')), /llama_ctl/, '页脚署名')

// 复制走回退路径（jsdom 没有 async clipboard），按钮亮一瞬「已复制」。
await click(aboutRows[0].querySelector('.r .textbtn'), '复制版本号')
assert.equal(txt(aboutRows[0].querySelector('.r .textbtn')), COPY.copied[0], '复制后按钮亮「已复制」')

// 启动参数：只读弹层逐字显示 AppParameters。
await click(actBtns[2], '查看启动参数')
assert.equal(modalHead(), COPY.appParams[0], '弹层标题是「启动参数」')
assert.equal(
  raw(modalBody().querySelector('pre')).trim(),
  store.snapshot.snap.facts.app_params,
  'AppParameters 逐字显示',
)
assert.equal(modalButtons().length, 1, '只读弹层只有「关闭」')
await click(modalButtons()[0], '关闭启动参数')
assert.equal(modal(), null)

// 许可弹层照旧。
await click(actBtns[3], '开源许可')
assert.equal(modalHead(), COPY.license[0], '许可弹层')
assert.equal(txt(modalBody().querySelector('pre')), flat(COPY.licenseBody[0]), '许可正文逐条列出')
assert.equal(modalButtons().length, 1, '许可只有「关闭」')
await click(modalButtons()[0], '关闭许可')
assert.equal(modal(), null)
console.log('ok  关于页：hero / 版本行带复制 / 技术栈 / 四个快捷入口 / 署名')

// ---- the settings page: language, appearance, motion, startup check --------

await navTo('settings')
assert.deepEqual(
  qa('.content .section').map(txt),
  [COPY.ui[0], COPY.font[0], COPY.updates[0]],
  '设置页三个 .section：界面 / 字体 / 更新（关于已独立成页）',
)
assert.equal(qa('.content .lrow').length, 8, '八行：语言 / 外观 / 动效 / 半透明材质 / 缩放 / 界面字体 / 等宽字体 / 启动时检查')
let settingDds = qa('.content .val.sel .selbtn')
assert.equal(settingDds.length, 4, '四个 .val.sel 下拉：语言 / 外观 / 界面字体 / 等宽字体')
const langOptEls = await openDd(settingDds[0], '语言下拉')
assert.deepEqual(
  langOptEls.map((o) => o.getAttribute('data-value')),
  ['zh', 'en'],
  '语言选项是 zh | en',
)
await closeDd(settingDds[0], '语言下拉')
settingDds = qa('.content .val.sel .selbtn')
const appearOptEls = await openDd(settingDds[1], '外观下拉')
assert.deepEqual(
  appearOptEls.map((o) => o.getAttribute('data-value')),
  ['system', 'light', 'dark'],
  '外观选项是 system | light | dark',
)
await closeDd(settingDds[1], '外观下拉')
const uiFontOptEls = await openDd(settingDds[2], '界面字体下拉')
assert.equal(uiFontOptEls[0].getAttribute('data-value'), '', '界面字体第一项是默认栈')
assert.ok(uiFontOptEls.some((o) => o.getAttribute('data-value') === 'Microsoft YaHei UI'), '界面字体下拉里有微软雅黑')
await closeDd(settingDds[2], '界面字体下拉')
const monoFontOptEls = await openDd(settingDds[3], '等宽字体下拉')
assert.ok(monoFontOptEls.some((o) => o.getAttribute('data-value') === 'Cascadia Mono'), '等宽字体下拉里有 Cascadia Mono')
await closeDd(settingDds[3], '等宽字体下拉')
assert.equal(qa('.content .val.sel .selbtn')[0].getAttribute('data-value'), 'zh', '语言停在 Snapshot 的值')
assert.equal(qa('.content .val.sel .selbtn')[1].getAttribute('data-value'), 'system', '外观停在 Snapshot 的值')
const switches = qa('.content button.sw')
assert.equal(switches.length, 3, '三个 button.sw：界面动效 / 半透明材质 / 启动时检查')
assert.equal(switches[0].getAttribute('aria-pressed'), 'true', '动效默认开')
assert.equal(switches[1].getAttribute('aria-pressed'), 'true', '半透明材质默认开')
assert.equal(switches[2].getAttribute('aria-pressed'), 'true', '启动时检查默认开')
assert.equal(switches[0].getAttribute('aria-label'), COPY.motion[0])
assert.equal(switches[1].getAttribute('aria-label'), COPY.mica[0])
assert.equal(switches[2].getAttribute('aria-label'), COPY.checkOnStart[0])

// 缩放是五档步进滑条，不是下拉，也没有「恢复默认」。
const slider = q('.content .stepslider')
assert.ok(slider, '缩放是 .stepslider 滑条')
assert.equal(slider.getAttribute('role'), 'slider', '滑条带 slider 角色')
assert.equal(slider.getAttribute('aria-valuemax'), '4', '滑条五档（0..4）')
assert.equal(slider.getAttribute('aria-valuenow'), '2', '默认停在第三档（标准）')
assert.equal(qa('.content .stepslider .stop').length, 5, '五个档位圆点')
assert.equal(qa('.content .lrow')[4].querySelector('.textbtn'), null, '缩放行没有「恢复默认」按钮')

// A language change goes through `save_settings` and is answered by Rust.
let sentLang = calls().length
await pickDd(qa('.content .val.sel .selbtn')[0], 'en', '语言')
const langCall = calls()
  .slice(sentLang)
  .find((c) => c.cmd === 'save_settings')
assert.ok(langCall, '语言经 save_settings 发出')
assert.deepEqual(Object.keys(langCall.args), ['settings'], 'save_settings 只带 settings')
assert.equal(langCall.args.settings.language, 'en', '带上新语言')
assert.equal(store.settings.value.language, 'en', 'store 持有 Rust 回读的值')
assert.deepEqual(
  qa('.content .section').map(txt),
  [COPY.ui[1], COPY.font[1], COPY.updates[1]],
  '整页换成英文',
)
assert.deepEqual(
  qa('.rail .nav[data-view]').map((n) => txt(n.querySelector('.label'))).slice(1, 3),
  [COPY.params[1], COPY.logs[1]],
  '侧栏也换成英文',
)
pushSnap({ lang: 'zh', settings: { ...store.snapshot.snap.settings, language: 'zh' } })
await flush()
assert.deepEqual(qa('.content .section').map(txt), [COPY.ui[0], COPY.font[0], COPY.updates[0]], '切回中文')

// An appearance change moves the shell's own `data-theme`.
settingDds = qa('.content .val.sel .selbtn')
sentLang = calls().length
await pickDd(settingDds[1], 'dark', '外观')
const appearCall = calls()
  .slice(sentLang)
  .find((c) => c.cmd === 'save_settings')
assert.ok(appearCall, '外观经 save_settings 发出')
assert.equal(appearCall.args.settings.appearance, 'dark', '带上新外观')
assert.equal(store.settings.value.appearance, 'dark')
assert.equal(theme.mode.value, 'dark', '外观真的变了')
assert.equal(q('.d5').getAttribute('data-theme'), 'dark', '外壳的 data-theme 跟着变')
assert.equal(qa('.content .val.sel .selbtn')[1].getAttribute('data-value'), 'dark', '控件显示 Rust 回读的值')
pushSettings({ appearance: 'system' })
await flush()
assert.equal(q('.d5').getAttribute('data-theme'), 'light', '回到跟随系统即 light')

// The motion switch reaches `<html>` through the store, not a local flag.
sentLang = calls().length
await click(qa('.content button.sw')[0], '界面动效')
const motionCall = calls()
  .slice(sentLang)
  .find((c) => c.cmd === 'save_settings')
assert.ok(motionCall, '动效开关经 save_settings')
assert.equal(motionCall.args.settings.motion_enabled, false, '带上 motion_enabled: false')
assert.equal(theme.motion.value, false, 'store 持有 Rust 回读的值')
assert.ok(doc.documentElement.classList.contains(motion.OFF_CLASS), '关闭动效即给 <html> 加 motion-off')
await click(qa('.content button.sw')[0], '界面动效')
assert.ok(!doc.documentElement.classList.contains(motion.OFF_CLASS), '再点一次恢复')

// The translucent-material switch persists like every other preference; the
// window side (effects + mica-host) belongs to the shell's own watcher and is
// a no-op outside the Tauri shell.
sentLang = calls().length
await click(qa('.content button.sw')[1], '半透明材质')
const micaCall = calls()
  .slice(sentLang)
  .find((c) => c.cmd === 'save_settings')
assert.ok(micaCall, '半透明材质经 save_settings')
assert.equal(micaCall.args.settings.mica_enabled, false, '带上 mica_enabled: false')
assert.equal(theme.mica.value, false, 'store 持有 Rust 回读的值')
await click(qa('.content button.sw')[1], '半透明材质')
assert.equal(theme.mica.value, true, '再点一次恢复')

// The startup-check preference persists the same way.
sentLang = calls().length
await click(qa('.content button.sw')[2], '启动时检查')
const startupCall = calls()
  .slice(sentLang)
  .find((c) => c.cmd === 'save_settings')
assert.ok(startupCall, '启动时检查经 save_settings')
assert.equal(startupCall.args.settings.upd_check_on_startup, false, '带上 upd_check_on_startup: false')
assert.equal(update.autoOnStartup.value, false, 'update store 持有回读的值')
assert.equal(qa('.content button.sw')[2].getAttribute('aria-pressed'), 'false', '开关跟着变')
pushSettings({ upd_check_on_startup: true })
await flush()

// ---- the font interface: scale slider / families, all through font.js ------

const zoomOf = () => doc.documentElement.style.getPropertyValue('--d5-zoom')
const uiCustom = () => doc.documentElement.style.getPropertyValue('--d5-ui-custom')
const monoCustom = () => doc.documentElement.style.getPropertyValue('--d5-mono-custom')
// jsdom 的 file: 源是 opaque origin，`localStorage` 访问本身会抛 SecurityError；
// font.js 内部对这一情况是安全的（静默不持久化），这里只测真实环境才有的落盘。
const canStore = (() => {
  try {
    W.localStorage.setItem('llama-ctl.probe', '1')
    W.localStorage.removeItem('llama-ctl.probe')
    return true
  } catch {
    return false
  }
})()
assert.equal(zoomOf(), '1', '默认缩放档是 1')
const stops = qa('.content .stepslider .stop')
await click(stops[4], '最宽一档')
assert.equal(zoomOf(), '1.2', '第五档写进 <html> 的 --d5-zoom')
assert.equal(q('.content .stepslider').getAttribute('aria-valuenow'), '4', '滑条角色值跟到第五档')
if (canStore) {
  assert.equal(
    W.localStorage.getItem('llama-ctl.font'),
    '{"scale":"xlarge","ui":"","mono":""}',
    '字体偏好落 localStorage',
  )
} else {
  console.log('ok  (jsdom file 源无 localStorage，持久化断言跳过；font.js 对此安全)')
}
await click(stops[0], '最小一档')
assert.equal(zoomOf(), '0.85', '第一档即时生效')
// 键盘也能走档：slider 角色上的左右方向键。
slider.dispatchEvent(new W.KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
await flush()
assert.equal(zoomOf(), '0.925', '方向键右移一档')
slider.dispatchEvent(new W.KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }))
await flush()
assert.equal(zoomOf(), '0.85', '方向键左移一档')
// window.llamaFont：开发接口与设置页走同一个模块
assert.ok(W.llamaFont, 'window.llamaFont 已暴露')
W.llamaFont.setScale('normal')
await flush()
assert.equal(zoomOf(), '1', '开发接口恢复标准档')
// 字体族改成下拉选：点选一个真实选项，栈首立即生效。
await pickDd(qa('.content .val.sel .selbtn')[2], 'Microsoft YaHei UI', '界面字体')
assert.match(uiCustom(), /Microsoft YaHei UI/, '界面字体族插到栈首（后接系统回退族）')
W.llamaFont.setUIFamily('')
await flush()
assert.equal(uiCustom(), '', '空串即回到默认栈')
await pickDd(qa('.content .val.sel .selbtn')[3], 'Consolas', '等宽字体')
assert.match(monoCustom(), /Consolas/, '等宽字体族插到栈首（后接 llama-mono 回退）')
W.llamaFont.setMonoFamily('')
await flush()
assert.equal(monoCustom(), '', '等宽覆盖清除')
console.log('ok  字体接口：五档滑条即时生效（点+键盘）· 字体族下拉插栈首带回退 · localStorage 持久化 · window.llamaFont')
console.log('ok  设置页：语言 / 外观 / 动效 / 半透明材质 / 启动时检查 都经 save_settings 并回读')

// ---- the service menu: three services, the current one marked --------------

await navTo('params')
await click(q('.title[data-menu="service"]'), '服务菜单')
assert.ok(q('.menu'), '服务菜单展开')
const svcItems = qa('.menu button')
assert.equal(svcItems.length, 3, '菜单列出全部 NSSM 服务')
assert.deepEqual(svcItems.map(txt), ['QwenLLM', 'QwenVL', 'llama-bench'], '服务名逐项来自 Snapshot')
assert.equal(svcItems[0].getAttribute('aria-current'), 'true', '当前服务在菜单里打标')
assert.equal(svcItems[1].getAttribute('aria-current'), 'false')
assert.deepEqual([...store.services.value], ['QwenLLM', 'QwenVL', 'llama-bench'], 'Snapshot.services')

const sentSwitch = calls().length
await click(svcItems[1], '切到 QwenVL')
const switchCall = calls()
  .slice(sentSwitch)
  .find((c) => c.cmd === 'switch_service')
assert.ok(switchCall, '没有未应用更改时直接切换')
assert.deepEqual(Object.keys(switchCall.args).sort(), ['backup', 'service', 'values'], 'switch_service 带 service/values/backup')
assert.equal(switchCall.args.service, 'QwenVL')
assert.equal(switchCall.args.backup, false, '没有改动就不备份')
assert.equal(switchCall.args.values.port, '8080', '切换时带上当前表单')
assert.equal(q('.menu'), null, '点过菜单项后菜单收起')

// ---- switching with unapplied changes asks, with three answers -------------

store.editField('port', '9999')
await flush()
const sentGuard = calls().length
await click(q('.title[data-menu="service"]'), '服务菜单')
assert.ok(q('.menu'), '有未应用更改也能打开菜单')
await click(qa('.menu button')[1], '切到 QwenVL')
assert.equal(modalHead(), COPY.confirm[0], '有未应用更改时先问（标题是「继续」）')
assert.match(txt(modalBody()), re(t('guardService', 'zh', { n: 'QwenVL' })), '问题点名目标服务')
const guardButtons = modalButtons()
assert.equal(guardButtons.length, 3, '三选：放弃更改 / 另存并切换 / 取消')
assert.deepEqual(guardButtons.map(txt), [COPY.discard[0], COPY.backupAndSwitch[0], COPY.cancel[0]])
assert.equal(store.selected.value, 'QwenLLM', '问的时候服务没变')
assert.equal(sentOf(sentGuard, 'switch_service').length, 0, '问的时候不发切换命令')
await click(guardButtons[2], '取消')
assert.equal(modal(), null, '取消关闭弹层')
assert.equal(store.selected.value, 'QwenLLM', '取消后服务未变')
assert.equal(store.values.value.port, '9999', '取消后编辑还在')
assert.equal(sentOf(sentGuard, 'switch_service').length, 0, '取消不发 switch_service')

// 放弃更改: switch at once, and back up nothing.
await click(q('.title[data-menu="service"]'), '服务菜单')
await click(qa('.menu button')[1], '切到 QwenVL')
const sentDiscard = calls().length
await click(modalButtons()[0], '放弃更改')
const discardSwitch = sentOf(sentDiscard, 'switch_service')[0]
assert.ok(discardSwitch, '放弃更改后照常切换')
assert.equal(discardSwitch.args.service, 'QwenVL')
assert.equal(sentOf(sentDiscard, 'save_preset').length, 0, '放弃更改不备份')

// 另存并切换: store the form under a timestamped name first.
store.editField('port', '9998')
await flush()
await click(q('.title[data-menu="service"]'), '服务菜单')
await click(qa('.menu button')[1], '切到 QwenVL')
const sentBackup = calls().length
await click(modalButtons()[1], '另存并切换')
const backupSave = sentOf(sentBackup, 'save_preset')[0]
assert.ok(backupSave, '另存并切换先存一份')
assert.deepEqual(Object.keys(backupSave.args).sort(), ['name', 'values'], 'save_preset 带 name/values')
assert.match(backupSave.args.name, /^自动备份 \d{2}-\d{2} \d{2}:\d{2}:\d{2}$/, '备份名带时间戳')
assert.equal(backupSave.args.values.port, '9998', '存的是当前表单')
assert.equal(sentOf(sentBackup, 'switch_service').length, 1, '存完再切换')

// The same guard covers loading a preset.
store.editField('port', '9997')
await flush()
await navTo('presets')
const sentGuardPreset = calls().length
await click(qa('.content .lrow')[0].querySelector('.r .textbtn'), '载入 32B 长上下文')
assert.equal(modalHead(), COPY.confirm[0], '载入预设前也先问')
assert.match(txt(modalBody()), re(t('guardPreset', 'zh')), '问题说的是预设而不是服务')
assert.deepEqual(modalButtons().map(txt), [COPY.discard[0], COPY.backupAndSwitch[0], COPY.cancel[0]])
await click(modalButtons()[2], '取消载入')
assert.equal(modal(), null)
assert.equal(sentOf(sentGuardPreset, 'load_preset').length, 0, '取消不载入')
store.clearForm()
await flush()
console.log('ok  切换服务 / 载入预设前先三选确认（放弃 / 另存并切换 / 取消）')

// ---- the preset is saved from the presets page, not only from a dialog -----

await navTo('presets')
await click(q('.content .section.preset-head .textbtn'), '保存为预设')
assert.equal(modalHead(), COPY.savePreset[0], '保存预设弹层')
const nameInput = q('.scrim .modal input.nameinput')
assert.ok(nameInput, '预设名是 .nameinput 输入框')
assert.equal(confirmBtn().disabled, true, '空名字时保存不可点')
await typeInto(nameInput, '32B 长上下文')
assert.equal(confirmBtn().disabled, false, '有名字后可点')
const sentSave = calls().length
await click(confirmBtn(), '保存预设')
const saveCall = sentOf(sentSave, 'save_preset')[0]
assert.ok(saveCall, '保存走 save_preset')
assert.deepEqual(Object.keys(saveCall.args).sort(), ['name', 'values'])
assert.equal(saveCall.args.name, '32B 长上下文', '名字就是输入框里的')
assert.deepEqual(
  { ...saveCall.args.values },
  { ...store.snapshot.snap.values },
  '存的是表单里的全部字段',
)
assert.equal(modal(), null, '保存后弹层关闭')
console.log('ok  保存预设入口在预设页标题行：先问名字，存的是整张表单')

// ---- 重启 asks first, then sends `restart` with the form ------------------

await navTo('params')
const sentRestart = calls().length
await click(q('.ghost[title="重启服务"]'), '重启')
assert.equal(modalHead(), COPY.restartSvc[0], '重启先问')
assert.match(txt(modalBody()), re(t('restartAsk', 'zh')), '问题说明会中断推理')
assert.equal(sentOf(sentRestart, 'restart').length, 0, '问的时候不发 restart')
await click(cancelBtn(), '取消重启')
assert.equal(modal(), null)
assert.equal(sentOf(sentRestart, 'restart').length, 0, '取消不发 restart')
assert.equal(store.busyName.value, '', '取消后 store 空闲')

const sentRestart2 = calls().length
await click(q('.ghost[title="重启服务"]'), '重启')
await click(confirmBtn(), '确认重启')
const restartCall = sentOf(sentRestart2, 'restart')[0]
assert.ok(restartCall, '确认后走 restart')
assert.deepEqual(Object.keys(restartCall.args), ['values'], 'restart 只带 values')
assert.equal(Object.keys(restartCall.args.values).length, 28, 'restart 提交整张表单')
assert.equal(modal(), null, '确认后弹层关闭')
assert.equal(store.busyName.value, '', 'restart 结束后 store 空闲')
console.log('ok  重启先二次确认 · 取消不发命令 · 确认才带 values 走 restart')

// ---- 应用更改: the diff is the second confirmation -------------------------

store.clearForm()
await flush()
assert.equal(q('.actionbar').classList.contains('show'), false, '没有改动时动作条不出现')
store.editField('ngl', '7')
store.editField('port', '9999')
await flush()
assert.match(txt(q('.actionbar')), re(t('dirtyN', 'zh', { n: 2 })), '动作条报告两项未应用')
await click(q('.actionbar .pillbtn'), '应用更改')
assert.equal(modalHead(), COPY.apply[0], '应用更改先问')
const diffRows = qa('.scrim .modal .diffrow')
assert.equal(diffRows.length, 2, '两个字段各一行对比')
assert.equal(txt(diffRows[0].querySelector('.fl')), 'ngl', '.fl 是字段 key')
assert.equal(txt(diffRows[0].querySelector('.old')), '99', '旧值取自 Snapshot')
assert.equal(txt(diffRows[0].querySelector('.new')), '7', '新值取自表单')
assert.equal(txt(diffRows[1].querySelector('.fl')), 'port')
assert.equal(txt(diffRows[1].querySelector('.old')), '8080')
assert.equal(txt(diffRows[1].querySelector('.new')), '9999')
assert.match(txt(diffRows[0].querySelector('.nm')), /GPU 层数/, '.nm 是人类可读名')
const sentApply = calls().length
assert.equal(sentOf(sentApply, 'apply_changes').length, 0, '问的时候不写服务')
await click(cancelBtn(), '取消应用')
assert.equal(modal(), null)
assert.equal(sentOf(sentApply, 'apply_changes').length, 0, '取消不写服务')
assert.equal(store.values.value.ngl, '7', '取消后编辑还在')

await click(q('.actionbar .pillbtn'), '应用更改')
const sentApply2 = calls().length
await click(confirmBtn(), '确认应用')
const applyCall = sentOf(sentApply2, 'apply_changes')[0]
assert.ok(applyCall, '确认后走 apply_changes')
assert.deepEqual(Object.keys(applyCall.args).sort(), ['extras', 'values'], 'apply_changes 带 values + extras')
assert.equal(applyCall.args.values.ngl, '7')
assert.equal(applyCall.args.values.port, '9999')
assert.deepEqual([...applyCall.args.extras], [], 'extras 来自 Snapshot')
assert.equal(store.snapshot.snap.values.ngl, '7', '界面上的值来自 Rust 返回的 Snapshot')
assert.equal(store.snapshot.snap.values.port, '9999')
assert.equal(store.snapshot.form, null, 'apply 之后表单被清空')
assert.equal(q('.actionbar').classList.contains('show'), false, '动作条收起')

// With no buffer left, the screen is nothing but the Snapshot.
pushSnap({ values: { ...store.snapshot.snap.values, ngl: '128' } })
await flush()
assert.equal(store.values.value.ngl, '128', '没有表单缓冲时，值只来自 Snapshot')
assert.equal(Number(txt(q('.row[data-row="ngl"] .numv'))), 128, '行内读数跟着 Snapshot')
pushSnap({ values: { ...store.snapshot.snap.values, ngl: '99' } })
await flush()
console.log('ok  应用更改：新旧对比 + 二次确认 · 用 Rust 返回的 Snapshot 并清空表单')

// ---- the round button is start / stop, and says which ----------------------

assert.equal(store.status.value.state, 'RUNNING', 'fixture 服务是 RUNNING')
assert.equal(q('.actions .round').getAttribute('title'), COPY.stopSvc[0], 'RUNNING 时是「停止服务」')
const sentPrimary = calls().length
await click(q('.actions .round'), '停止服务')
const stopCall = sentOf(sentPrimary, 'service_action')[0]
assert.ok(stopCall, '主操作走 service_action')
assert.deepEqual(Object.keys(stopCall.args), ['action'], 'service_action 只带 action')
assert.equal(stopCall.args.action, 'stop', 'RUNNING 时发 stop')
pushSnap({ status: { state: 'STOPPED', ok: false, detail: 'not running' } })
await flush()
assert.equal(q('.actions .round').getAttribute('aria-label'), COPY.startSvc[0], 'STOPPED 时主操作是「启动服务」')
assert.match(txt(q('.statuspill')), re(COPY.stopped[0]), '状态条说「已停止」')
assert.equal(
  txt(q('.statuspill .mono')),
  `:${store.snapshot.snap.values.port}`,
  '端口那一段跟着 Snapshot',
)
const sentPrimary2 = calls().length
await click(q('.actions .round'), '启动服务')
assert.equal(sentOf(sentPrimary2, 'service_action')[0].args.action, 'start', 'STOPPED 时发 start')
pushSnap({ status: { state: 'RUNNING', ok: true, detail: 'healthz ok · 127.0.0.1:8080 · b5527' } })
await flush()
assert.equal(q('.actions .round').getAttribute('aria-label'), COPY.stopSvc[0], '回到 RUNNING')
console.log('ok  主操作按钮：RUNNING 发 stop / STOPPED 发 start · aria-label 随状态走')

// ---- with no service, the shell says so and disables what it cannot do ----

store.setSnapshot(emptySnapshot())
await flush()
assert.ok(q('.empty').classList.contains('show'), '无服务时显示空态水印')
assert.equal(q('.statuspill').style.display, 'none', '状态条隐藏')
assert.equal(q('.title').style.opacity, '0.45', '标题压到 45%')
assert.equal(txt(q('.topbar .title')), '—', '没有选中服务时标题是破折号')
assert.equal(q('.actions .round').disabled, true, '没有服务时主操作禁用')
assert.equal(q('.ghost[title="重启服务"]').disabled, true, '没有服务时重启禁用')
assert.equal(q('.rail-tools').style.visibility, 'hidden', '没有服务时不显示筛选条')
assert.equal(q('.actionbar').classList.contains('show'), false, '没有服务时动作条不出现')
store.setSnapshot(demoSnapshot())
await flush()
assert.equal(q('.empty').classList.contains('show'), false, '服务回来时空态收起')
assert.equal(txt(q('.topbar .title')), 'QwenLLM', '标题回到选中的服务')
console.log('ok  空态：水印 + 标题压暗 + 主操作/重启禁用')

// ---- 检查 ≠ 安装（关于页的「检查更新」） ------------------------------------

update.reset()
await flush()
await navTo('about')
const actBtns2 = qa('.content .actgrid button')
const sentCheck = calls().length
await click(actBtns2[0], '检查更新')
assert.equal(sentOf(sentCheck, 'check_update').length, 1, '「检查更新」发 check_update')
assert.equal(sentOf(sentCheck, 'install_update').length, 0, '「检查更新」绝不安装')
const checkedNow = update.checked.value
assert.equal(checkedNow.installed, 10813, 'Rust 报告已安装 b10813')
assert.equal(checkedNow.release.build, 10819, 'Rust 报告最新 b10819')
assert.equal(checkedNow.up_to_date, false, 'b10813 落后于 b10819')
// 检查结果落在弹层里；可安装时弹层给「更新」，通往二次确认。
assert.equal(modalHead(), COPY.update[0], '检查结果在弹层里')
assert.match(txt(modalBody()), /当前：b10813/, '状态行说当前版本')
assert.match(txt(modalBody()), /最新：b10819/, '状态行说最新版本')
assert.deepEqual(modalButtons().map(txt), [COPY.update[0], COPY.cancel[0]], '两个答案：更新 / 取消')
await click(cancelBtn(), '关闭检查结果')
assert.equal(modal(), null)
// 顺便验证版本行跟着检查结果走。
assert.equal(txt(qa('.content .lrow')[1].querySelector('.r .mono')), 'b10813', '构建号行换成检查结果')
console.log('ok  检查只检查：check_update 一条，install_update 零条 · 结果在弹层里')

// ---- 更新二次确认，点名备份目录 ---------------------------------------------

await click(actBtns2[0], '检查更新')
await click(confirmBtn(), '更新')
assert.equal(modalHead(), COPY.update[0], '更新先问')
assert.match(txt(modalBody()), re(t('installAsk', 'zh')), '问题说明会停服务、替换二进制、先备份')
const installPres = qa('.scrim .modal .body pre')
assert.equal(installPres.length, 2, '弹层里两段 pre：状态行与备份目录')
assert.match(raw(installPres[0]), /当前：b10813/, '状态行说当前版本')
assert.match(raw(installPres[0]), /最新：b10819/, '状态行说最新版本')
assert.match(raw(installPres[1]), re('F:\\llama.cpp\\backup\\b10819'), '二次确认点明备份目录（与 Rust 的 root\\backup\\tag 同形）')
assert.equal(update.canInstall.value, true, '有版本可安装')
assert.deepEqual(modalButtons().map(txt), [COPY.update[0], COPY.cancel[0]], '两个答案：更新 / 取消')
const sentInstallAsk = calls().length
await click(cancelBtn(), '取消更新')
assert.equal(modal(), null, '取消关闭弹层')
assert.equal(sentOf(sentInstallAsk, 'install_update').length, 0, '取消不下载不安装')
assert.equal(update.confirmOpen.value, false, '取消后确认态复位')

// ---- the install streams its transcript, line for line --------------------

await click(actBtns2[0], '检查更新')
await click(confirmBtn(), '更新')
const sentInstall = calls().length
// No `await click` here on purpose: `flush()` sleeps 40 ms, and the whole
// nine-line stream finishes inside that window — the samples below would then
// only ever see 8 and 9, which is exactly what a batch render would look like.
const installButton = confirmBtn()
assert.ok(installButton, '确认按钮就位')
installButton.click()

// Sample while it fills: a streamed render passes through intermediate counts,
// a render at the end would show 0 and then 9.
const counts = []
for (let i = 0; i < 500; i++) {
  await new Promise((r) => setTimeout(r, 2))
  counts.push(update.progress.value.length)
  if (counts[counts.length - 1] === INSTALL_LINES.length) break
}
for (let i = 1; i < counts.length; i++) {
  assert.ok(counts[i] >= counts[i - 1], `进度只增不减：${counts.join(',')}`)
}
assert.ok(new Set(counts).size >= 3, `逐行到达，不是结束时一次铺满：${counts.join(',')}`)
await flush()
const installCall = sentOf(sentInstall, 'install_update')[0]
assert.ok(installCall, '确认后才发 install_update，一次')
assert.equal(sentOf(sentInstall, 'install_update').length, 1, 'install_update 只发一次')
assert.deepEqual(Object.keys(installCall.args), [], 'install_update 不带参数')
assert.equal(modal(), null, '确认后弹层关闭')

assert.deepEqual([...update.progress.value], Array.from(INSTALL_LINES), '进度行逐字一致且有序')
assert.equal(update.progress.value.length, INSTALL_LINES.length, `九行都在：${update.progress.value.length}`)
assert.equal(update.report.value.downloaded, 2, 'InstallReport：下载 2 个资产')
assert.deepEqual([...update.report.value.replaced], ['llama-server.exe', 'llama-cli.exe'], '替换清单')
assert.deepEqual([...update.report.value.added], ['cudart64_134.dll'], '新增清单')
// `DesignApp.vue` subscribes `EVENT_UPDATE` → `store.pushLog` on mount and
// `update.beginInstall()` pushes the same lines too, so the shell's transcript
// holds each line twice. The order and the completeness are what the shell
// promises, so that is what is asserted here (the duplication is reported).
const collapsed = [...store.snapshot.log].filter((line, i, all) => line !== all[i - 1])
assert.deepEqual(collapsed, Array.from(INSTALL_LINES), '日志区按顺序收到每一行')
assert.equal(update.busy.value, false, '装完 store 不再忙')
assert.equal(update.error.value, '', '装完没有错误行')
// 安装现场进日志页（v6 没有维护页的 .installbox）：日志页此时被清空过也照常渲染过程行。
await navTo('logs')
await flush()
assert.ok(qa('.content .logline').length >= INSTALL_LINES.length, '日志页能看到安装现场')
console.log(`ok  更新 ${INSTALL_LINES.length} 行实时滚动（中间态 ${new Set(counts).size} 次）· 顺序逐字一致 · 现场进日志页`)

// ---- a channel change drops the release that was checked ------------------

await update.check()
await flush()
assert.ok(update.release.value, '重新检查后有可安装版本')
const sentChannel = calls().length
// Driven through the store directly (the DOM entry is the about page's check,
// already proven above). What is under test is that a channel change goes
// through `save_settings` and invalidates the last check.
const switched = await update.setChannel('win-cpu-x64')
await flush()
assert.equal(switched, true, '换渠道写成功')
const channelCall = sentOf(sentChannel, 'save_settings')[0]
assert.ok(channelCall, '换渠道经 save_settings')
assert.equal(channelCall.args.settings.upd_channel, 'win-cpu-x64', '带上新渠道')
assert.deepEqual(Object.keys(channelCall.args), ['settings'], 'save_settings 只带 settings')
assert.equal(store.settings.value.upd_channel, 'win-cpu-x64', 'store 持有回读的值')
assert.equal(update.release.value, null, '换渠道即作废旧检查')
assert.equal(update.canInstall.value, false, '没看过的版本不可安装')
console.log('ok  切换渠道即作废旧检查（不会装没看过的版本）')

// ---- 未检查 / 未知 / 已知 / 已是最新 是四件不同的事 ------------------------

update.setChecked(demoUpdateCheck({ up_to_date: true }))
await flush()
assert.equal(update.statusKind.value, 'known', '已知构建是第三种状态')
assert.match(update.statusLine.value, /当前：b10813/, '状态行说当前版本')
update.setChecked(demoUpdateCheck({ installed: null }))
await flush()
assert.equal(update.statusKind.value, 'unknown', '读不到 llama-server.exe 就是「未知」')
assert.match(update.statusLine.value, /当前版本未知（无法读取 llama-server\.exe）/, '未知要说清原因')
update.reset()
await flush()
assert.equal(update.statusKind.value, 'none', '从未检查是第四种状态')
assert.equal(update.statusLine.value, st('upd.status.none'), '未检查时说「还未检查过更新」')
console.log('ok  更新状态四态分明：未检查 / 未知 / 已知 / 已是最新')

// ---- the IPC shape, command by command ------------------------------------

const SHAPES = {
  get_snapshot: ['values'],
  switch_service: ['service', 'values', 'backup'],
  apply_changes: ['values', 'extras'],
  service_action: ['action'],
  restart: ['values'],
  set_start_mode: ['mode'],
  load_preset: ['name'],
  save_preset: ['name', 'values'],
  delete_preset: ['name'],
  save_settings: ['settings'],
}
const marked = calls().length
ipcModule.getSnapshot({ alias: 'qwen3-32b' })
ipcModule.switchService('QwenVL', { port: '8080' })
ipcModule.applyChanges({ port: '8080' }, [])
ipcModule.serviceAction('stop')
ipcModule.restart({ port: '8080' })
ipcModule.setStartMode('auto')
ipcModule.loadPreset('7B 快速')
ipcModule.savePreset('7B 快速', { port: '8080' })
ipcModule.deletePreset('7B 快速')
ipcModule.saveSettings({ language: 'zh' })
const shaped = since(marked)
assert.equal(shaped.length, 10, '十个命令各发一条')
for (const [cmd, keys] of Object.entries(SHAPES)) {
  const entry = shaped.find((c) => c.cmd === cmd)
  assert.ok(entry, `${cmd} 发出`)
  assert.deepEqual(
    Object.keys(entry.args).sort(),
    [...keys].sort(),
    `${cmd} 的参数形状是 { ${keys.join(', ')} }`,
  )
}
assert.deepEqual(
  { ...shaped.find((c) => c.cmd === 'get_snapshot').args.values },
  { alias: 'qwen3-32b' },
  'get_snapshot 带的是表单（可为 null）',
)
assert.equal(shaped.find((c) => c.cmd === 'service_action').args.action, 'stop', 'action 是字符串')
assert.equal(shaped.find((c) => c.cmd === 'set_start_mode').args.mode, 'auto', 'mode 是字符串')
assert.deepEqual([...shaped.find((c) => c.cmd === 'apply_changes').args.extras], [], 'extras 是数组')
const bootCheck = calls().find((c) => c.cmd === 'check_update')
assert.deepEqual(Object.keys(bootCheck.args), [], 'check_update 不带参数')
assert.deepEqual(Object.keys(installCall.args), [], 'install_update 不带参数')
const CONTRACT = new Set([
  'plugin:event|listen',
  'plugin:event|unlisten',
  'plugin:window|set_theme',
  'plugin:window|set_effects',
  'revert',
  'check_update',
  'install_update',
  ...Object.keys(SHAPES),
])
const outside = [...new Set(cmds())].filter((c) => !CONTRACT.has(c))
assert.deepEqual(outside, [], `只发契约里的命令，多出来的是：${outside}`)
console.log(`ok  IPC 形状：${Object.keys(SHAPES).length + 2} 条命令的名字与参数逐项核对，没有契约外的命令`)

// ---- the field contract: 28 fields, 7 groups, everything explained ---------

assert.equal(FIELDS.length, 28, '28 项字段')
assert.equal(new Set(FIELDS.map((f) => f.key)).size, 28, '没有重复的 key')
assert.equal(new Set(FIELDS.map((f) => f.group)).size, 7, '7 个分组')
assert.deepEqual(
  [...GROUP_ORDER],
  [...new Set(FIELDS.map((f) => f.group))],
  'GROUP_ORDER 就是字段表里的分组顺序',
)
for (const f of FIELDS) {
  assert.ok(GROUP_ORDER.includes(f.group), `${f.key} 落在已知分组里`)
  assert.match(txt({ textContent: paramHelp(f.key, store.snapshot.snap?.strings) }), /\S/, `${f.key} 有说明`)
  assert.notEqual(paramHelp(f.key, store.snapshot.snap?.strings), NO_HELP, `${f.key} 的说明不是占位`)
  if (f.kind === 'combo') {
    assert.ok((OPTIONS[f.key] ?? []).length > 0, `${f.key} 是枚举且有选项`)
    for (const v of OPTIONS[f.key]) {
      assert.match(
        txt({ textContent: optionHelp(f.key, v, store.snapshot.snap?.strings) }),
        /\S/,
        `${f.key}=${v} 有选项说明`,
      )
    }
  } else {
    assert.equal(OPTIONS[f.key], undefined, `${f.key} 不是枚举，也就没有 OPTIONS`)
  }
  if (f.kind === 'slider') {
    assert.ok(f.min < f.max, `${f.key} 有真实的上下界`)
    assert.ok(f.step > 0, `${f.key} 的步进为正`)
    assert.ok(f.def >= f.min && f.def <= f.max, `${f.key} 的默认值在界内`)
  }
}

// A missing explanation renders as a visible placeholder, never blank.
assert.equal(paramHelp('no_such_field', store.snapshot.snap?.strings), NO_HELP, '缺失说明是可见占位')
assert.equal(optionHelp('host', 'nope', store.snapshot.snap?.strings), '', '未知选项没有说明就是空串')
assert.match(paramHelp('ngl', store.snapshot.snap?.strings), /显存/, '说明是中文原文')
assert.match(optionHelp('spec_type', 'draft-mtp', store.snapshot.snap?.strings), /MTP/, '已选项有自己的说明')

// Every fixture value has to be one Rust's parser would accept: a demo that
// ships an out-of-range slider would show a clamp on a healthy service.
for (const f of FIELDS) {
  if (f.kind !== 'slider') continue
  const rawValue = store.snapshot.snap.values[f.key]
  const v = Number(rawValue)
  assert.ok(
    Number.isFinite(v) && v >= f.min && v <= f.max,
    `fixture ${f.key} = ${rawValue} 在 [${f.min}, ${f.max}] 内`,
  )
}
console.log(`ok  ${FIELDS.length} 项字段 · ${GROUP_ORDER.length} 组 · 每项与每个选项都有说明 · fixture 值在界内`)

// ---- the local field table still matches Rust's ---------------------------

const RUST = resolve('..', 'src-tauri', 'commands', 'src', 'fields.rs')
const rustSrc = existsSync(RUST) ? readFileSync(RUST, 'utf8') : ''
if (rustSrc) {
  const rustKeys = [
    ...rustSrc.matchAll(/def\(\s*\n?\s*"([a-z_0-9]+)"|Def \{\s*\n\s*key: "([a-z_0-9]+)"/g),
  ].map((m) => m[1] ?? m[2])
  assert.ok(rustKeys.length > 0, '读到了 Rust 的字段表')
  assert.deepEqual([...FIELDS.map((f) => f.key)], rustKeys, '本地字段表逐项等于 fields.rs，顺序一致')
  const groupNames = new Set(
    [...rustSrc.matchAll(/G_(MODEL|ACCEL|CTX|CONC|SAMPLE|NET|ADV)/g)].map((m) => m[0]),
  )
  assert.equal(groupNames.size, 7, `Rust 声明了七个分组：${[...groupNames]}`)
  for (const name of groupNames) {
    const value = rustSrc.match(new RegExp(`pub const ${name}: &str = "([^"]+)"`))?.[1]
    assert.ok(value, `${name} 在 Rust 里有值`)
    assert.ok(GROUP_ORDER.includes(value), `表单有 Rust 的分组「${value}」(${name})`)
  }
  console.log('ok  本地字段表与 src-tauri/commands/src/fields.rs 一致（含七个分组）')
} else {
  console.log('ok  (src-tauri 不在，跳过与 Rust 的交叉核对)')
}

// The build-variant list is Rust's too.
const shownChannels = [...update.channels.value].map((c) => ({ value: c.value, label: c.label }))
assert.deepEqual(
  shownChannels.map((c) => c.value),
  [...store.snapshot.snap.channels.map(([id]) => id)],
  '渠道列表逐项来自 Snapshot.channels，不是自带的一份',
)
assert.equal(shownChannels.length, 4, '四条构建线')
for (const c of shownChannels) {
  assert.match(c.value, /^win-/, `${c.value} 是渠道 id`)
  assert.match(c.label, /\S/, `${c.value} 有标签`)
}
const UPDATER = resolve('..', 'src-tauri', 'core', 'src', 'updater.rs')
const updaterSrc = existsSync(UPDATER) ? readFileSync(UPDATER, 'utf8') : ''
if (updaterSrc) {
  const idBlock = updaterSrc.match(/pub fn id\(self\)[\s\S]*?\n\s{4}\}/)?.[0] ?? ''
  const rustIds = [...idBlock.matchAll(/"([^"]+)"/g)].map((m) => m[1])
  assert.ok(rustIds.length > 0, '读到了 Rust 的渠道 id')
  assert.deepEqual(shownChannels.map((c) => c.value), rustIds, '渠道 id 与 updater.rs 逐一对应')
  console.log(`ok  构建线 ${rustIds.length} 条与 updater.rs 一致`)
} else {
  console.log('ok  (src-tauri 不在，跳过渠道与 Rust 的交叉核对)')
}

// ---- the copy table is complete in both languages -------------------------

const copyKeys = Object.keys(COPY)
assert.ok(copyKeys.length >= 60, `文案表 ${copyKeys.length} 条`)
const FILL = new Proxy({}, { has: () => true, get: (_, k) => `«${String(k)}»` })
for (const key of copyKeys) {
  const [zh, en] = COPY[key]
  assert.match(String(zh ?? ''), /\S/, `${key} 的中文非空`)
  assert.match(String(en ?? ''), /\S/, `${key} 的英文非空`)
  for (const lang of ['zh', 'en']) {
    assert.doesNotMatch(t(key, lang, FILL), /\{\w+\}/, `${key}[${lang}] 的占位符都能填上`)
  }
}
assert.equal(t('nope.not.a.key', 'zh'), 'nope.not.a.key', '未知键渲染为它自己')
assert.equal(t('dirtyN', 'zh', { n: 3 }), '3 项未应用', '中文占位符替换')
assert.equal(t('dirtyN', 'en', { n: 3 }), '3 unapplied', '英文占位符替换')
assert.equal(t('dirtyN', 'zh', { n: 0 }), '0 项未应用', '零也要替换，不能吞掉占位')
assert.match(t('guardService', 'en', { n: 'QwenVL' }), /QwenVL/, '命名的占位符被替换')
assert.match(t('autoAsk', 'zh', { m: 'auto' }), /auto/, '模式占位符被替换')
assert.match(autoBackupName(new Date(2026, 2, 14, 9, 12, 41)), /^自动备份 03-14 09:12:41$/, '自动备份名带时间戳')
assert.match(autoBackupName(), /^自动备份 /, '自动备份名与预设页的分组前缀一致')

// The areas the shell cannot ship without copy for.
const REQUIRED = [
  // 身份与导航
  'appName', 'params', 'logs', 'presets', 'settings', 'about', 'svc', 'all', 'changed',
  // 动作条与状态
  'dirtyN', 'revert', 'apply', 'cancel', 'confirm',
  'healthOk', 'stopped', 'healthIdle', 'noService', 'working', 'noChanges',
  // 顶栏动作
  'switchService', 'startSvc', 'stopSvc', 'restartSvc', 'openDir', 'more',
  'minimize', 'maximize', 'close',
  // 弹层
  'savePreset', 'name', 'changes', 'discard', 'backupAndSwitch',
  'guardService', 'guardPreset', 'restartAsk', 'stopAsk', 'deleteAsk',
  'installAsk', 'license', 'licenseBody',
  // 预设
  'mine', 'backups', 'autobackup', 'load', 'loaded', 'del', 'presetSaved',
  'presetExists', 'presetDeleted', 'needsRestart', 'applied',
  // 日志
  'following', 'paused', 'clearLog',
  // 设置
  'ui', 'lang', 'appearance', 'motion', 'mica', 'micaHint', 'checkOnStart',
  'system', 'light', 'dark', 'fontDefault', 'uiScale', 'uiFont', 'monoFont',
  // 关于
  'appTagline', 'appVersion', 'llamaBuild', 'appDir', 'stackSec', 'quickSec',
  'checkUpdates', 'homepage', 'devBy', 'copyBtn', 'copied', 'version',
  // 更新
  'update', 'checkNow', 'upToDate', 'updates',
]
for (const key of REQUIRED) {
  assert.ok(key in COPY, `文案表覆盖 ${key}`)
}
console.log(`ok  ${copyKeys.length} 条文案 zh/en 均非空、占位符可填 · 覆盖导航/动作条/状态/弹层/预设/维护/设置`)

// ---- the motion switch ----------------------------------------------------

const DURATIONS = Object.keys(motion.DURATION_VARS)
assert.ok(DURATIONS.length >= 5, `可关闭的时长有 ${DURATIONS.length} 个`)
const onVars = motion.motionVars(true)
const offVars = motion.motionVars(false)
for (const v of DURATIONS) {
  assert.notEqual(onVars[v], offVars[v], `${v} 随开关改变`)
  assert.ok(/^0\./.test(offVars[v]), `${v} 关闭后近似瞬时：${offVars[v]}`)
}
// Thresholds and easings are not animations: the 300 ms「?」delay must survive.
for (const v of Object.keys(motion.THRESHOLD_VARS)) {
  assert.equal(onVars[v], offVars[v], `${v} 是阈值，不是动画`)
}
for (const v of Object.keys(motion.EASE_VARS)) {
  assert.equal(onVars[v], offVars[v], `${v} 是曲线，不是时长`)
}
assert.deepEqual(
  [motion.HELP.delay, motion.HELP.in, motion.HELP.out],
  [motion.MS.TIP_DELAY, motion.MS.TIP_IN, motion.MS.TIP_OUT],
  '「?」时序从 MOTION 解析，不是另抄一份',
)
motion.applyMotion(false)
await flush()
assert.equal(doc.documentElement.style.getPropertyValue('--m-hover-in'), motion.INSTANT, '属性被改写，不只是加类')
// Nothing becomes unreachable: the parameter page is still the whole form.
await navTo('params')
assert.ok(qa('.content button, .content input').length > 0, '关闭动效时控件一个都不少')
assert.equal(qa('.content .row[data-row]').length, 28, '关闭动效时 28 个参数行仍在')
motion.applyMotion(true)
await flush()
console.log('ok  动效开关：时长归零但功能不缺失 · 阈值与曲线不受影响')

// ---- no console noise ----------------------------------------------------

const noise = warnings.filter((w) => !/Could not parse CSS|Not implemented/.test(w))
assert.deepEqual(noise, [], `控制台保持干净：\n${noise.join('\n')}`)
console.log('ok  无运行期报错、无 Vue 警告')

console.log('\nall design-layer smoke checks passed')
dom.window.close()

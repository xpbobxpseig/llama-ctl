/**
 * 界面标注层（开发专用，`?annotate=1` 时由 main.js 动态加载）。
 *
 * 目的：设计评审直接在真实界面上做——vite dev 起的浏览器 demo 就是
 * DesignApp 本体（真实 design.css / Dd / fixture 数据），这层只在上面
 * 浮一个 Shadow DOM 工具条，绝不触碰应用代码路径：
 *  - 标注模式开：document 捕获阶段吞掉点击，悬停高亮、点选元素、
 *    写反馈（可加 问题/建议/文案 标签），生成编号徽钉；
 *  - 标注模式关：一个字节的行为都不改变；
 *  - 数据存 localStorage，可导出 Markdown（复制 + 下载 .md）。
 *
 * 生产壳（Tauri）不带 query 且非 DEV，这个分支不可达；动态 import
 * 保证它永远不在主包里。
 */

const LS_KEY = 'lmk-annotate-v1'
const TAGS = [
  ['issue', '问题'],
  ['idea', '建议'],
  ['copy', '文案'],
]
const TAG_NAME = Object.fromEntries(TAGS)

let started = false

export function startAnnotate() {
  if (started) return
  started = true

  // ---- 状态 ---------------------------------------------------------------

  let items = []
  let on = true
  let activeId = null
  let seq = 0

  function load() {
    try {
      const raw = localStorage.getItem(LS_KEY)
      const arr = raw ? JSON.parse(raw) : []
      if (Array.isArray(arr)) {
        items = arr.filter((it) => it && it.id && typeof it.label === 'string')
        seq = items.reduce((m, it) => Math.max(m, Number(String(it.id).split('-')[1]) || 0), 0)
      }
    } catch {
      items = []
    }
  }
  function save() {
    try {
      localStorage.setItem(LS_KEY, JSON.stringify(items))
    } catch {
      /* 隐私模式等：只影响持久化 */
    }
  }

  // ---- 元素定位 ------------------------------------------------------------

  function cssSel(el) {
    const parts = []
    let e = el
    while (e && e !== document.documentElement) {
      if (e.id && e.id !== 'app') {
        parts.unshift('#' + CSS.escape(e.id))
        break
      }
      const tag = e.tagName.toLowerCase()
      const parent = e.parentElement
      let nth = 1
      for (let s = e.previousElementSibling; s; s = s.previousElementSibling) {
        if (s.tagName === e.tagName) nth++
      }
      parts.unshift(`${tag}:nth-of-type(${nth})`)
      e = parent
    }
    return parts.join(' > ')
  }

  function findEl(it) {
    try {
      return document.querySelector(it.sel)
    } catch {
      return null
    }
  }

  function labelOf(el) {
    const tag = el.tagName.toLowerCase()
    const cls = el.classList && el.classList.length ? '.' + el.classList[0] : ''
    const txt = (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60)
    return tag + cls + (txt ? ` 「${txt}」` : '')
  }

  function ctxOf(el) {
    const sec = el.closest && el.closest('.section')
    if (sec) return '「' + sec.textContent.replace(/\s+/g, ' ').trim() + '」区'
    const view = el.closest && el.closest('[data-view]')
    if (view) return view.dataset.view + ' 页'
    const nav = el.closest && el.closest('.market-head')
    if (nav) return '工具行'
    return '当前页'
  }

  /** 文档坐标（.content 是唯一滚动容器；window 不滚）。 */
  function docPos(el) {
    const r = el.getBoundingClientRect()
    const sc = document.querySelector('.d5 .content')
    return {
      x: r.left + (sc ? sc.scrollLeft : 0),
      y: r.top + (sc ? sc.scrollTop : 0),
    }
  }

  /** 视口坐标：活元素实时取，丢失的元素按文档坐标减滚动量兜底。 */
  function viewPos(it) {
    const el = findEl(it)
    if (el) {
      const r = el.getBoundingClientRect()
      const p = docPos(el)
      it.x = p.x
      it.y = p.y
      return { x: r.right - 8, y: r.top - 8, r, el }
    }
    const sc = document.querySelector('.d5 .content')
    return {
      x: it.x - (sc ? sc.scrollLeft : 0),
      y: it.y - (sc ? sc.scrollTop : 0),
      r: null,
      el: null,
    }
  }

  // ---- Shadow DOM 骨架 ------------------------------------------------------

  const host = document.createElement('div')
  host.id = 'lmk-anno-host'
  host.style.cssText = 'position:fixed;inset:0;z-index:2147483000;pointer-events:none;'
  const root = host.attachShadow({ mode: 'open' })
  root.innerHTML = `
  <style>
    :host { all: initial; }
    * { box-sizing: border-box; }
    .ui {
      --t-bg: light-dark(#ffffff, #211f1b);
      --t-border: light-dark(#e3e3e8, #35312b);
      --t-bsoft: light-dark(#ececf1, #2b2823);
      --t-text: light-dark(#1d1d1f, #eae5dd);
      --t-mut: light-dark(#6e6e73, #a49e94);
      --t-acc: light-dark(#1f6b58, #6ec9a8);
      --t-accfg: light-dark(#ffffff, #171614);
      --t-soft: light-dark(rgba(31,107,88,.12), rgba(110,201,168,.20));
      --t-hover: light-dark(#f2f2f6, #262320);
      --t-err: light-dark(#b23a30, #ed8076);
      color: var(--t-text);
      font-family: "Segoe UI", "Segoe UI Variable Text", "Microsoft YaHei UI", system-ui, sans-serif;
      font-size: 13px; line-height: 1.5;
    }
    .hl {
      position: fixed; pointer-events: none; z-index: 1; border-radius: 8px;
      border: 2px solid var(--t-acc); background: var(--t-soft);
    }
    .bar {
      position: fixed; left: 16px; bottom: 16px; z-index: 6; pointer-events: auto;
      display: flex; align-items: center; gap: 8px; padding: 6px 8px 6px 12px;
      background: var(--t-bg); border: 1px solid var(--t-border); border-radius: 999px;
      box-shadow: 0 12px 40px rgba(0,0,0,.22);
    }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--t-acc); }
    .dot.off { background: var(--t-mut); }
    .bar b { font-weight: 600; }
    .bar .cnt { color: var(--t-mut); }
    .tbtn {
      height: 26px; padding: 0 10px; border-radius: 6px; border: 0; cursor: pointer;
      background: none; color: var(--t-text); font: 500 12.5px/1 inherit-font, "Segoe UI", "Microsoft YaHei UI", sans-serif;
    }
    .tbtn:hover { background: var(--t-hover); }
    .tbtn.warn:hover { color: var(--t-err); }
    .tbtn.pri { background: var(--t-acc); color: var(--t-accfg); font-weight: 600; }
    .tbtn.pri:hover { filter: brightness(1.08); }
    .pin {
      position: fixed; z-index: 3; pointer-events: auto; cursor: pointer;
      width: 22px; height: 22px; border-radius: 50%; padding: 0;
      border: 2px solid var(--t-acc); background: var(--t-bg); color: var(--t-acc);
      font: 600 11px/1 "Segoe UI", sans-serif;
      display: inline-flex; align-items: center; justify-content: center;
      box-shadow: 0 2px 8px rgba(0,0,0,.25);
    }
    .pin.filled { background: var(--t-acc); color: var(--t-accfg); }
    .pin.active { box-shadow: 0 0 0 4px var(--t-soft); }
    .editor, .panel {
      position: fixed; z-index: 5; pointer-events: auto;
      background: var(--t-bg); border: 1px solid var(--t-border); border-radius: 12px;
      box-shadow: 0 18px 48px rgba(0,0,0,.28); padding: 12px;
    }
    .editor { width: 300px; }
    .panel { left: 16px; bottom: 62px; width: 320px; max-height: 46vh; overflow: auto; }
    .ed-name { font-weight: 600; font-size: 12.5px; margin-bottom: 2px; }
    .ed-ctx, .ed-label { color: var(--t-mut); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .ed-label { margin-bottom: 8px; }
    .tags { display: flex; gap: 6px; margin-bottom: 8px; }
    .tag {
      height: 22px; padding: 0 10px; border-radius: 999px; cursor: pointer; font-size: 12px;
      border: 1px solid var(--t-border); background: none; color: var(--t-mut);
    }
    .tag[aria-pressed="true"] { background: var(--t-acc); border-color: var(--t-acc); color: var(--t-accfg); }
    textarea {
      width: 100%; min-height: 64px; resize: vertical; padding: 7px 9px; border-radius: 8px;
      border: 1px solid var(--t-border); background: var(--t-hover); color: var(--t-text);
      font: 13px/1.55 "Segoe UI", "Microsoft YaHei UI", sans-serif;
    }
    textarea:focus { outline: none; border-color: var(--t-acc); }
    .ed-foot { display: flex; justify-content: space-between; margin-top: 8px; }
    .prow { display: flex; align-items: center; gap: 8px; padding: 7px 6px; border-radius: 8px; cursor: pointer; }
    .prow:hover { background: var(--t-hover); }
    .prow .no { flex: none; color: var(--t-acc); font-weight: 600; }
    .prow .lb { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12.5px; }
    .prow .tx { color: var(--t-mut); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 40%; }
    .prow .del { flex: none; border: 0; background: none; color: var(--t-mut); cursor: pointer; font-size: 12px; padding: 2px 6px; border-radius: 6px; }
    .prow .del:hover { color: var(--t-err); background: none; }
    .panel h4 { margin: 2px 6px 6px; font-size: 12px; font-weight: 600; color: var(--t-mut); }
    .empty { color: var(--t-mut); padding: 8px 6px; font-size: 12.5px; }
    [hidden] { display: none !important; }
  </style>
  <div class="ui">
    <div class="hl" hidden></div>
    <div class="pinset"></div>
    <div class="editor" hidden>
      <div class="ed-name"></div>
      <div class="ed-ctx"></div>
      <div class="ed-label"></div>
      <div class="tags"></div>
      <textarea placeholder="这里要改什么？（Ctrl+Enter 完成）"></textarea>
      <div class="ed-foot">
        <button class="tbtn warn" data-act="del">删除标注</button>
        <button class="tbtn pri" data-act="done">完成</button>
      </div>
    </div>
    <div class="panel" hidden>
      <h4>标注列表</h4>
      <div class="plist"></div>
    </div>
    <div class="bar">
      <span class="dot"></span>
      <b title="点击元素 = 标注；Alt+点击 = 正常操作界面；侧栏导航始终直通">标注模式</b>
      <span class="cnt"></span>
      <button class="tbtn" data-act="list">列表</button>
      <button class="tbtn" data-act="export">导出 Markdown</button>
      <button class="tbtn warn" data-act="clear">清空</button>
      <button class="tbtn" data-act="toggle">关闭</button>
    </div>
  </div>`
  document.documentElement.appendChild(host)

  const $ = (s) => root.querySelector(s)
  const hl = $('.hl')
  const pinset = $('.pinset')
  const editor = $('.editor')
  const panel = $('.panel')
  const bar = $('.bar')
  const dot = $('.dot')
  const cnt = $('.cnt')

  // ---- 渲染 -----------------------------------------------------------------

  function itemById(id) {
    return items.find((it) => it.id === id) || null
  }

  function refreshBar() {
    const filled = items.filter((it) => (it.text || '').trim()).length
    dot.classList.toggle('off', !on)
    cnt.textContent = on ? `· ${items.length} 处（${filled} 有内容）` : `· 已关闭（${items.length} 处）`
    bar.querySelector('[data-act="toggle"]').textContent = on ? '关闭' : '开启'
  }

  function renderPins() {
    pinset.textContent = ''
    if (!on) return
    items.forEach((it, i) => {
      const p = viewPos(it)
      const b = document.createElement('button')
      b.className = 'pin' + ((it.text || '').trim() ? ' filled' : '') + (activeId === it.id ? ' active' : '')
      b.textContent = String(i + 1)
      b.style.left = Math.max(2, p.x - 11) + 'px'
      b.style.top = Math.max(2, p.y - 11) + 'px'
      b.title = it.label
      b.addEventListener('click', (e) => {
        e.stopPropagation()
        openEditor(it, p)
      })
      pinset.appendChild(b)
    })
  }

  function renderPanel() {
    const list = $('.plist')
    list.textContent = ''
    if (!items.length) {
      const d = document.createElement('div')
      d.className = 'empty'
      d.textContent = '还没有标注：点界面上的任意元素开始。'
      list.appendChild(d)
      return
    }
    items.forEach((it, i) => {
      const row = document.createElement('div')
      row.className = 'prow'
      const no = document.createElement('span')
      no.className = 'no'
      no.textContent = String(i + 1)
      const lb = document.createElement('span')
      lb.className = 'lb'
      lb.textContent = it.label
      const tx = document.createElement('span')
      tx.className = 'tx'
      tx.textContent = (it.text || '').trim().slice(0, 24) || '—'
      const del = document.createElement('button')
      del.className = 'del'
      del.textContent = '删'
      del.addEventListener('click', (e) => {
        e.stopPropagation()
        items = items.filter((x) => x !== it)
        if (activeId === it.id) closeEditor()
        save()
        renderAll()
      })
      row.append(no, lb, tx, del)
      row.addEventListener('click', () => {
        const p = viewPos(it)
        const el = findEl(it)
        if (el) el.scrollIntoView({ block: 'nearest' })
        openEditor(it, p)
        panel.hidden = true
      })
      list.appendChild(row)
    })
  }

  function renderTags(it) {
    const box = editor.querySelector('.tags')
    box.textContent = ''
    TAGS.forEach(([key, name]) => {
      const b = document.createElement('button')
      b.className = 'tag'
      b.textContent = name
      b.setAttribute('aria-pressed', String((it.tags || []).includes(key)))
      b.addEventListener('click', () => {
        it.tags = it.tags || []
        const i = it.tags.indexOf(key)
        if (i >= 0) it.tags.splice(i, 1)
        else it.tags.push(key)
        save()
        renderTags(it)
        renderPins()
      })
      box.appendChild(b)
    })
  }

  function openEditor(it, p) {
    activeId = it.id
    editor.hidden = false
    editor.querySelector('.ed-name').textContent = '标注 ' + (items.indexOf(it) + 1)
    editor.querySelector('.ed-ctx').textContent = it.ctx || ''
    editor.querySelector('.ed-label').textContent = it.label
    const ta = editor.querySelector('textarea')
    ta.value = it.text || ''
    renderTags(it)
    if (p && p.r) {
      const vw = window.innerWidth
      const vh = window.innerHeight
      let x = Math.min(p.r.right + 10, vw - 312)
      let y = Math.min(p.r.bottom + 10, vh - 260)
      x = Math.max(10, Math.min(x, vw - 310))
      y = Math.max(10, y)
      editor.style.left = x + 'px'
      editor.style.top = y + 'px'
    } else {
      editor.style.left = '50%'
      editor.style.top = '80px'
      editor.style.transform = 'translateX(-50%)'
    }
    renderPins()
    setTimeout(() => ta.focus(), 0)
  }

  function closeEditor() {
    activeId = null
    editor.hidden = true
    renderPins()
  }

  function renderAll() {
    refreshBar()
    renderPins()
    renderPanel()
  }

  // ---- 拾取（捕获阶段吞点击，应用完全无感） -----------------------------------

  function inOurUi(e) {
    return e.target === host
  }

  function onDocClick(e) {
    if (!on || inOurUi(e)) return
    // Alt+点击：直通应用（切详情、开关、下载等交互照常触发）；
    // 侧栏 .nav：始终直通（评审时要来回换视图，不该被标注拦住）。
    // 两者对所有事件类型都完全放行——只放行 click 会让按下/悬停行为残缺。
    if (e.altKey) return
    if (e.target && e.target.closest && e.target.closest('.rail .nav')) return
    e.preventDefault()
    e.stopImmediatePropagation()
    if (e.type === 'click') {
      const t = e.target
      const skip =
        !t ||
        t === document.documentElement ||
        t === document.body ||
        (t.id && t.id === 'app') ||
        (t.classList && (t.classList.contains('d5') || t.classList.contains('pop-layer'))) ||
        (t.closest && t.closest('.grips'))
      if (skip) return
      const it = {
        id: 'a-' + ++seq + '-' + Date.now().toString(36),
        sel: cssSel(t),
        label: labelOf(t),
        ctx: ctxOf(t),
        x: 0,
        y: 0,
        text: '',
        tags: [],
      }
      const p = docPos(t)
      it.x = p.x
      it.y = p.y
      items.push(it)
      save()
      renderAll()
      openEditor(it, { r: t.getBoundingClientRect() })
    }
  }

  function onDocOver(e) {
    if (!on || inOurUi(e)) return
    const t = e.target
    if (!t || t === document.documentElement || t === document.body || t.id === 'app') {
      hl.hidden = true
      return
    }
    const r = t.getBoundingClientRect()
    if (!r.width && !r.height) {
      hl.hidden = true
      return
    }
    hl.hidden = false
    hl.style.left = r.left - 3 + 'px'
    hl.style.top = r.top - 3 + 'px'
    hl.style.width = r.width + 6 + 'px'
    hl.style.height = r.height + 6 + 'px'
  }

  // ---- 导出 -----------------------------------------------------------------

  function buildMd() {
    const lines = ['# 市场模块 · 真机界面标注', '']
    lines.push('- 环境：`npm run dev` + `?annotate=1`（浏览器 demo 数据）')
    lines.push(`- 标注数：${items.length}（${items.filter((it) => (it.text || '').trim()).length} 处有内容）`)
    lines.push('')
    items.forEach((it, i) => {
      const tags = (it.tags || []).map((k) => TAG_NAME[k] || k).join('/')
      lines.push(`## ${i + 1} · ${it.ctx || '页面'}`)
      lines.push('')
      lines.push('- 元素：`' + it.label + '`')
      lines.push(it.text.trim()
        ? '- 标注' + (tags ? '[' + tags + ']' : '') + '：' + it.text.trim().replace(/\n+/g, '；')
        : '- 标注：（空）')
      lines.push('')
    })
    return lines.join('\n')
  }

  async function doExport() {
    const md = buildMd()
    let ok = false
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(md)
        ok = true
      }
    } catch { /* 走下载兜底 */ }
    try {
      const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' })
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = 'market-annotations.md'
      document.body.appendChild(a)
      a.click()
      setTimeout(() => {
        URL.revokeObjectURL(a.href)
        a.remove()
      }, 400)
    } catch { /* 至少复制成功即可 */ }
    cnt.textContent = ok ? '· 已复制 + 已下载 ✓' : '· 已下载 market-annotations.md ✓'
    setTimeout(refreshBar, 2500)
  }

  // ---- 事件 -----------------------------------------------------------------

  document.addEventListener('mousedown', onDocClick, true)
  document.addEventListener('click', onDocClick, true)
  document.addEventListener('mouseover', onDocOver, true)
  document.addEventListener('mouseleave', () => { hl.hidden = true })

  editor.addEventListener('click', (e) => {
    const act = e.target.closest && e.target.closest('[data-act]')
    if (!act) return
    const it = itemById(activeId)
    if (!it) return
    if (act.dataset.act === 'done') closeEditor()
    if (act.dataset.act === 'del') {
      items = items.filter((x) => x !== it)
      save()
      closeEditor()
      renderAll()
    }
  })
  editor.querySelector('textarea').addEventListener('input', (e) => {
    const it = itemById(activeId)
    if (!it) return
    it.text = e.target.value
    save()
    renderPins()
  })
  editor.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) closeEditor()
    e.stopPropagation()
  })

  bar.addEventListener('click', (e) => {
    const act = e.target.closest && e.target.closest('[data-act]')
    if (!act) return
    const k = act.dataset.act
    if (k === 'toggle') {
      on = !on
      if (!on) {
        hl.hidden = true
        closeEditor()
        panel.hidden = true
      }
      renderAll()
    }
    if (k === 'list') {
      panel.hidden = !panel.hidden
      if (!panel.hidden) renderPanel()
    }
    if (k === 'export') doExport()
    if (k === 'clear') {
      if (items.length && confirm('清空全部标注？')) {
        items = []
        save()
        closeEditor()
        renderAll()
      }
    }
  })

  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && on) {
      if (!editor.hidden) closeEditor()
      else panel.hidden = true
    }
  })

  // 徽钉跟随布局：滚动 / 视图切换 / 弹层开合都实时重算（dev 工具，成本可忽略）
  ;(function tick() {
    if (on && (items.length || activeId)) renderPins()
    requestAnimationFrame(tick)
  })()

  load()
  renderAll()
}

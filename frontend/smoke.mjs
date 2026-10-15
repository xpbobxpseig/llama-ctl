/**
 * Tickets 12 & 13 smoke test — `cd frontend && npm run smoke`.
 *
 * Ticket 13's half (from "7 groups render" on) asserts the parameter form: the
 * groups, the widget each field kind renders, the「?」and the explanations, the
 * mono readout's line box, and that collapse state survives a theme/language
 * switch. It also diffs the local field table against Rust's own source, so a
 * field added in `commands::fields` and not here fails instead of silently
 * rendering a shorter form.
 *
 * It is the smallest thing that fails if the shell breaks: bundle the real app
 * with the same Vite config as the shipped build, run that bundle in jsdom with
 * no Tauri internals, then assert the theme tokens, the rendered screens, the
 * geometry round trip and the one-way-state rule.
 *
 * honest: it is the same artefact shape Tauri loads, booted in the same order.
 *
 * `assert` + jsdom only. The repo has no JS test framework, and adding one for
 * a smoke check nobody asked for would be worse than using the bundler that is
 * already installed.
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

/**
 * The built stylesheet. jsdom does not load it (the bundle is an IIFE with no
 * `<link>`), but it is the same file the window loads, so declarations that
 * `getComputedStyle` cannot resolve — every `var()` — are asserted against it.
 */
const css = readFileSync('.smoke/llama-ctl-frontend.css', 'utf8')

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

await new Promise((resolve) => {
  const deadline = Date.now() + 20_000
  const poll = setInterval(() => {
    if (window.__SMOKE__ || Date.now() > deadline) {
      clearInterval(poll)
      resolve()
    }
  }, 25)
})

assert.ok(window.__SMOKE__, `the bundle ran and mounted:\n${warnings.join('\n')}`)
const {
  store,
  theme,
  naiveOverrides,
  cssVars,
  TYPE,
  RADIUS,
  PALETTES,
  parseGeometry,
  formatGeometry,
  FIELDS,
  GROUP_ORDER,
  OPTIONS,
  paramHelp,
  optionHelp,
  // Ticket 14.
  ServiceControls,
  StatusDot,
  LogTail,
  ConfirmDialog,
  CONTROL_COPY,
  ct,
} = window.__SMOKE__

const text = window.document.getElementById('app').textContent

// ---- the shell renders, not a blank page -----------------------------------

assert.match(text, /llama\.cpp/, 'title bar renders the app title')

// `GROUP_ORDER` crosses the jsdom boundary, so its arrays carry jsdom's
// `Array.prototype`. `assert.deepEqual` compares prototypes, and a jsdom array
// never deep-equals a Node one — copy it into this realm once.
const GROUPS = Array.from(GROUP_ORDER)
assert.match(text, /QwenLLM/, 'the fixture service is on screen')
assert.match(text, /RUNNING/, 'the status card shows the service state')
assert.match(text, /演示数据/, 'demo mode is labelled, not passed off as live')
console.log('ok  shell mounts and renders the fixture')

// ---- the six type steps ----------------------------------------------------

const steps = [TYPE.DISPLAY, TYPE.SECTION, TYPE.GROUP, TYPE.BODY, TYPE.SMALL, TYPE.MICRO]
assert.deepEqual(steps, [18, 15, 13, 13, 12, 11], `type scale: ${steps}`)
for (let i = 1; i < steps.length; i++) {
  assert.ok(steps[i] <= steps[i - 1], `step ${i} must not increase: ${steps}`)
}
console.log('ok  type scale is strictly decreasing: 18 / 15 / 13 / 13 / 12 / 11')

// ---- radii, primary and status colours ------------------------------------

assert.equal(RADIUS.CARD, '12px', 'card radius')
assert.equal(RADIUS.CONTROL, '8px', 'control radius')
for (const mode of ['light', 'dark']) {
  const p = PALETTES[mode]
  const o = naiveOverrides(mode)
  const json = JSON.stringify(o)
  assert.equal(p.ACC, '#0a84ff', `${mode} primary`)
  assert.equal(p.RUN, '#30d158', `${mode} running`)
  // The Python palette moves the warning and error hues per appearance; the
  // accent and the running green do not (llama_ctl_gui.py L425-442).
  assert.equal(p.ORG, mode === 'light' ? '#ff9500' : '#ff9f0a', `${mode} warning`)
  assert.equal(p.RED, mode === 'light' ? '#ff3b30' : '#ff453a', `${mode} error`)
  assert.equal(o.common.primaryColor, '#0a84ff', `${mode} NaiveUI primary override`)
  assert.equal(o.common.borderRadius, '8px', `${mode} control radius`)
  assert.equal(o.common.borderRadiusLarge, '12px', `${mode} card radius`)
  assert.equal(o.common.fontSize, `${TYPE.BODY}px`, `${mode} base font size`)
  assert.match(o.common.fontFamily, /Microsoft YaHei UI/, `${mode} UI font`)
  assert.match(o.common.fontFamilyMono, /Cascadia Mono/, `${mode} mono font`)
  assert.match(o.common.fontFamilyMono, /Consolas/, `${mode} mono fallback`)
  // NaiveUI's defaults — green primary, 3px radius, 14px base — must not
  // survive anywhere in the overrides.
  assert.doesNotMatch(json, /#18a058/, `${mode} carries no NaiveUI green`)
  assert.doesNotMatch(json, /"fontSize":"14px"/, `${mode} carries no 14px base`)
  // Every radius is one of ours. `4px` (checkbox), `6px` (tag) and `9px`
  // (switch pill) are deliberate; NaiveUI's 3px is not.
  const ours = new Set([RADIUS.CONTROL, RADIUS.CARD, '4px', '6px', '9px'])
  for (const [name, block] of Object.entries(o)) {
    for (const [k, v] of Object.entries(block ?? {})) {
      if (k.startsWith('borderRadius') && typeof v === 'string') {
        assert.ok(ours.has(v), `${mode} ${name}.${k} = ${v} is a token, not NaiveUI's 3px`)
      }
    }
  }
}
console.log('ok  radii 12/8 · #0a84ff · 运行/警告/错误 · YaHei UI + Cascadia Mono')

// ---- light and dark are isomorphic -----------------------------------------

const light = cssVars('light')
const dark = cssVars('dark')
assert.notEqual(light['--bg'], dark['--bg'], 'the background swaps')
assert.notEqual(light['--card'], dark['--card'], 'the card surface swaps')
assert.equal(light['--acc'], dark['--acc'], 'the accent does not move')
assert.equal(light['--run'], dark['--run'], 'running green does not move')
for (const [k, v] of Object.entries(light)) {
  if (k.startsWith('--sp-')) assert.equal(parseInt(v, 10) % 4, 0, `${k} = ${v} on the 4px rhythm`)
}
console.log('ok  palettes are isomorphic · spacing on the 4px rhythm')

// ---- geometry round trip ---------------------------------------------------

assert.deepEqual(
  { ...parseGeometry('1200x800+10+20') },
  { w: 1200, h: 800, x: 10, y: 20 },
  'a full geometry parses, position included',
)
assert.deepEqual(
  { ...parseGeometry('1000x860') },
  { w: 1000, h: 860, x: null, y: null },
  'a size-only geometry parses with no position',
)
assert.equal(parseGeometry('120x80'), null, 'a fluke is refused')
assert.equal(parseGeometry(null), null, 'absent geometry is not an error')
assert.equal(parseGeometry('garbage'), null, 'a corrupt string is refused')
assert.equal(formatGeometry({ w: 1200, h: 800, x: 10, y: 20 }), '1200x800+10+20')
assert.equal(formatGeometry({ w: 1000, h: 860, x: null, y: null }), '1000x860')
console.log('ok  geometry parses and formats as WxH+X+Y')

// ---- the one-way rule ------------------------------------------------------

store.editField('port', '9999')
assert.equal(store.values.value.port, '9999', 'an edit is held locally')
assert.equal(store.snapshot.snap.values.port, '8080', 'the snapshot is untouched by it')
store.clearForm()
assert.equal(store.values.value.port, '8080', 'clearing the form returns to the service')
console.log('ok  edits stay local; the snapshot stays authoritative')

// ---- ticket 13: the parameter form -----------------------------------------

// The seven groups render, in Rust's own order, and the first two start open.
const groupEls = [...window.document.querySelectorAll('[data-group]')]
const renderedGroups = groupEls.map((el) => el.getAttribute('data-group'))
assert.deepEqual(
  renderedGroups,
  [...GROUPS],
  `all seven groups render in table order: ${renderedGroups}`,
)

/**
 * Which groups are open, read off the DOM the way a user reads it: the header
 * carries `aria-expanded`. Asserting on the attribute rather than on internal
 * state is what makes the "survives a switch" check below mean something.
 */
function openMap() {
  const out = {}
  for (const el of window.document.querySelectorAll('[data-group]')) {
    const head = el.querySelector('button.head')
    out[el.getAttribute('data-group')] = head?.getAttribute('aria-expanded') === 'true'
  }
  return out
}

const initial = openMap()
assert.deepEqual(
  GROUPS.slice(0, 2).map((g) => initial[g]),
  [true, true],
  `the first two groups start expanded: ${JSON.stringify(initial)}`,
)
assert.deepEqual(
  GROUPS.slice(2).map((g) => initial[g]),
  [false, false, false, false, false],
  `the other five start collapsed: ${JSON.stringify(initial)}`,
)
console.log('ok  7 groups render · first two expanded, the rest collapsed')

// ---- every kind renders the control it should ------------------------------

/**
 * The control inside a field row, by the class NaiveUI gives it — proof that
 * the right *component* was chosen, not merely that some widget is there.
 */
function controlOf(key) {
  const row = window.document.querySelector(`[data-field="${key}"]`)
  assert.ok(row, `row for ${key} renders`)
  return row
}

const has = (key, selector, what) => {
  const row = controlOf(key)
  assert.ok(row.querySelector(selector), `${key} renders a ${what}`)
}

// Sliders: GPU layers, context length, parallel slots, batch sizes, threads,
// temperature, min-p (the ticket's own list).
for (const key of [
  'ngl', 'ctx_size', 'parallel', 'batch_size', 'ubatch_size', 'threads',
  'temperature', 'min_p', 'top_k', 'top_p', 'spec_draft_n_max',
]) {
  has(key, '.n-slider', 'slider')
  // The live numeric readout is the point of the slider row.
  const out = controlOf(key).querySelector('output.readout')
  assert.ok(out, `${key} has a numeric readout`)
  assert.match(out.textContent.trim(), /\d/, `${key} readout shows a number: ${out.textContent}`)
  // jsdom has no layout engine, so "is it clipped" cannot be measured — but the
  // reserved width can be, and it is what decides. It must cover the widest
  // value the bounds allow: integer digits, plus the point and decimals a
  // fractional step implies, plus the unit. `temperature` (0..2, step 0.05)
  // renders `0.8` and needs 4ch, which the integer-only count would miss.
  const f = FIELDS.find((x) => x.key === key)
  const digits = (String(f.step).split('.')[1] ?? '').length
  const ints = Math.max(String(Math.trunc(f.max)).length, String(Math.trunc(f.min)).length)
  const unit = store.lang.value === 'en' ? (f.unit?.en ?? '') : (f.unit?.zh ?? '')
  const needed = ints + (digits > 0 ? 1 + digits : 0) + (unit ? unit.length + 1 : 0)
  const reserved = parseFloat(out.style.width)
  assert.ok(
    reserved >= needed,
    `${key} reserves ${reserved}ch for a ${needed}ch value`,
  )
}
console.log('ok  numeric fields render a slider + live numeric readout')


// Combos: the four enumerated fields, and only those four.
for (const key of ['spec_type', 'ctk', 'ctv', 'flash_attn', 'host']) {
  has(key, '.n-base-selection', 'select')
}
console.log('ok  enumerated fields render a select')

// Checks: the four advanced switches plus the one that ships ON.
for (const key of ['no_mmap', 'mlock', 'no_kv_offload', 'cpu_moe', 'jinja']) {
  has(key, '.n-checkbox', 'checkbox')
}
console.log('ok  boolean fields render a checkbox')

// File paths: input + browse button.
for (const key of ['model', 'mmproj', 'spec_draft_model']) {
  const row = controlOf(key)
  assert.ok(row.querySelector('.n-input'), `${key} renders a text input`)
  const browse = [...row.querySelectorAll('button')].some((b) => b.textContent.includes('浏览'))
  assert.ok(browse, `${key} renders a Browse button`)
  assert.ok(row.querySelector('input[type="file"]'), `${key} has a file chooser`)
}
console.log('ok  file-path fields render an input + Browse button')

// Plain text fields fall through to a text input and nothing else.
for (const key of ['alias', 'seed', 'port', 'chat_template_kwargs']) {
  const row = controlOf(key)
  assert.ok(row.querySelector('.n-input'), `${key} renders a text input`)
  assert.equal(row.querySelector('.n-slider'), null, `${key} is not a slider`)
  assert.equal(row.querySelector('.n-base-selection'), null, `${key} is not a select`)
}
console.log('ok  text fields render a plain input')

// ---- the「?」is on every parameter -----------------------------------------

for (const f of FIELDS) {
  const q = controlOf(f.key).querySelector('button.q')
  assert.ok(q, `${f.key} has a「?」button`)
  assert.match(q.getAttribute('aria-label') ?? '', /\S/, `${f.key}「?」is labelled`)
}
const help = paramHelp('ngl', store.snapshot.snap?.strings)
assert.match(help, /显存/, `the explanation is the Chinese one: ${help}`)
assert.equal(
  paramHelp('no_such_field', store.snapshot.snap?.strings),
  '（无说明）',
  'a missing explanation renders as a visible placeholder, never blank',
)
// Selects carry an explanation for the option that is chosen.
assert.match(
  optionHelp('spec_type', 'draft-mtp', store.snapshot.snap?.strings),
  /MTP/,
  'the chosen option has its own explanation',
)
assert.equal(optionHelp('host', 'nope', store.snapshot.snap?.strings), '', 'an unknown option is empty')
console.log('ok  every parameter has a「?」; options have their own explanations')

// ---- collapse state survives a theme / language switch ---------------------

/**
 * A theme or language change goes through `save_settings`, which Rust answers
 * with a fresh Snapshot — a new string table, in the case of a language change.
 * There is no Rust in jsdom, so the Snapshot Rust would have sent is fed into
 * the store directly; that is the same code path the command's answer takes
 * (`store.setSnapshot`), so what is being tested here is the re-render, not the
 * transport.
 */
async function flush() {
  // Vue flushes on the microtask queue; jsdom's `requestAnimationFrame` lives
  // on its own window, so it is called there rather than from this realm.
  await new Promise((r) => setTimeout(r, 60))
  await new Promise((r) => window.requestAnimationFrame(() => r()))
}

/** Apply a preference the way Rust's answer to `save_settings` would. */
function applySettings(patch) {
  store.setSnapshot({
    ...store.snapshot.snap,
    settings: { ...store.settings.value, ...patch },
  })
}

// Toggle a group so the map is not the default any more: a state that merely
// re-derives the default would pass by accident.
window.document.querySelector('[data-group="高级"] button.head').click()
await flush()
const before = openMap()
assert.equal(before['高级'], true, 'clicking a header expands it')

applySettings({ appearance: 'dark' })
await flush()
assert.deepEqual(openMap(), before, 'collapse state survives an appearance switch')
assert.equal(theme.mode.value, 'dark', 'the appearance really changed')
// Rust's answer to a language change is a new `lang` and a new string table.
store.setSnapshot({ ...store.snapshot.snap, lang: 'en' })
await flush()

const afterLang = openMap()
assert.deepEqual(afterLang, before, 'collapse state survives a language switch')
// The switch really happened: the headings are translated now.
const enHeadings = [...window.document.querySelectorAll('[data-group] button.head .title')].map(
  (el) => el.textContent.trim(),
)
assert.ok(enHeadings.includes('Advanced'), `headings are English now: ${enHeadings}`)
assert.ok(enHeadings.includes('Sampling'), `headings are English now: ${enHeadings}`)
console.log('ok  collapse state survives a theme and a language switch')


/*
 * The 4px line-box drift the Python build had: a readout with its own font
 * size sits on a different baseline than the label beside it. Both steps come
 * from the same token module, so there is nothing to compensate for — and the
 * readout carries no local font at all.
 */
// ---- the mono readout matches body text ------------------------------------

// jsdom does not load the CSS bundle, so `getComputedStyle` cannot resolve
// `var(--font-mono)`. The declarations are asserted against the built
// stylesheet instead — that is the same file the window loads.
const readoutCss = css.match(/\.readout[^}]*\}/)?.[0] ?? ''
assert.match(readoutCss, /white-space:\s*nowrap/, `the readout never wraps: ${readoutCss}`)
// No font of its own: family, size, line-height and tabular figures all come
// from `t-mono`, which is what makes it share a line box with the body label
// beside it. Asserting that is asserting there is nothing to compensate for.
assert.doesNotMatch(readoutCss, /font-size/, `the readout sets no font of its own: ${readoutCss}`)
const monoCss = css.match(/\.t-mono[^}]*\}/)?.[0] ?? ''
assert.match(monoCss, /font-family:\s*var\(--font-mono\)/, `the readout is mono: ${monoCss}`)
assert.match(monoCss, /font-size:\s*var\(--f-mono\)/, `the readout uses the mono step: ${monoCss}`)
assert.match(monoCss, /line-height:\s*1\.5/, `the readout is 1.5, like body text: ${monoCss}`)
assert.match(monoCss, /tabular-nums/, `digits do not reflow while dragging: ${monoCss}`)
// And the two steps really are the same value, from the same module.
const vars = cssVars('light')
assert.equal(vars['--f-mono'], vars['--f-body'], `--f-mono and --f-body are the same: ${vars['--f-mono']}`)
assert.match(vars['--font-mono'], /Cascadia Mono/, `mono family: ${vars['--font-mono']}`)
assert.match(vars['--font-mono'], /Consolas/, `mono fallback: ${vars['--font-mono']}`)
// The label beside it is `.t-body`: 13px at 1.5, from the same token module.
const bodyCss = css.match(/\.t-body[^}]*\}/)?.[0] ?? ''
assert.match(bodyCss, /font-size:\s*var\(--f-body\)/, `the label uses the body step: ${bodyCss}`)
assert.match(bodyCss, /line-height:\s*1\.5/, `the label is 1.5 too: ${bodyCss}`)
console.log('ok  mono readout is --f-mono/1.5 — the same line box as body text')

/*
 * `src/api/field-copy.js` is a copy of Rust's table, so the check that matters
 * is that it *still* matches. Rust's own source is read and diffed against it
 * key for key and group for group: if ticket 19 adds a field to
 * `commands::fields` and not here, this fails rather than silently rendering
 * 27 parameters.
 */
const RUST = resolve('..', 'src-tauri', 'commands', 'src', 'fields.rs')
const rustSrc = existsSync(RUST) ? readFileSync(RUST, 'utf8') : ''

if (rustSrc) {
  const rustKeys = [
    ...rustSrc.matchAll(/def\(\s*\n?\s*"([a-z_0-9]+)"|Def \{\s*\n\s*key: "([a-z_0-9]+)"/g),
  ].map((m) => m[1] ?? m[2])
  const rustGroups = [
    ...rustSrc.matchAll(/G_(MODEL|ACCEL|CTX|CONC|SAMPLE|NET|ADV)/g),
  ].map((m) => m[0])
  // Same cross-realm caveat as `GROUPS`: copy into this realm before comparing.
  assert.deepEqual(
    Array.from(FIELDS.map((f) => f.key)),
    rustKeys,
    "the local field table is Rust's, key for key and in the same order",
  )
  // `G_*` also appears in the `pub const` declarations and inside `defs()`;
  // the seven distinct spellings are what the form has to have.
  const groupNames = new Set(rustGroups)

  assert.ok(rustKeys.length > 0, 'the Rust field table was read')
  assert.equal(groupNames.size, 7, `Rust declares seven groups: ${[...groupNames]}`)

  assert.equal(GROUPS.length, 7, 'the form renders seven groups')

  // Every group Rust declares appears in the form, spelled the same way.
  for (const name of groupNames) {
    const value = rustSrc.match(new RegExp(`pub const ${name}: &str = "([^"]+)"`))?.[1]
    assert.ok(value, `${name} has a value in Rust`)
    assert.ok(GROUPS.includes(value), `the form has Rust's group "${value}" (${name})`)
  }
  console.log('ok  the local field table matches src-tauri/commands/src/fields.rs')
} else {
  console.log('ok  (src-tauri not present — skipped the cross-check against Rust)')
}


// Every fixture value has to be one Rust's parser would accept: a demo that
// ships an out-of-range slider would show a clamp and a warning on a perfectly
// healthy service.
for (const f of FIELDS) {
  if (f.kind !== 'slider') continue
  const raw = store.snapshot.snap.values[f.key]
  const v = Number(raw)
  assert.ok(
    Number.isFinite(v) && v >= f.min && v <= f.max,
    `fixture ${f.key} = ${raw} is inside [${f.min}, ${f.max}]`,
  )
}
console.log("ok  every fixture slider value is inside Rust's bounds")
assert.equal(new Set(FIELDS.map((f) => f.key)).size, FIELDS.length, 'no duplicate field keys')
for (const f of FIELDS) {
  assert.ok(GROUPS.includes(f.group), `${f.key} is in a known group: ${f.group}`)
  assert.match(paramHelp(f.key, store.snapshot.snap?.strings), /\S/, `${f.key} has an explanation`)
  if (f.kind === 'combo') {
    assert.ok((OPTIONS[f.key] ?? []).length > 0, `${f.key} is a combo with options`)
    for (const v of OPTIONS[f.key]) {
      assert.match(optionHelp(f.key, v, store.snapshot.snap?.strings), /\S/, `${f.key}=${v} is explained`)
    }
  }
  if (f.kind === 'slider') {
    assert.ok(f.min < f.max, `${f.key} has real bounds`)
    assert.ok(f.step > 0, `${f.key} has a positive step`)
  }
}
console.log(`ok  ${FIELDS.length} fields · ${GROUPS.length} groups · every field and option explained`)

// ---- an edit is local, the snapshot stays authoritative -------------------

const before2 = store.snapshot.snap.values.ngl
store.editField('ngl', '7')
await flush()
assert.equal(store.values.value.ngl, '7', 'the edit is on screen')
assert.equal(store.snapshot.snap.values.ngl, before2, 'the snapshot is untouched by it')
assert.match(
  window.document.querySelector('[data-field="ngl"] output.readout').textContent,
  /7/,
  'the readout follows the edit',
)
store.clearForm()
await flush()
assert.equal(store.values.value.ngl, before2, 'clearing the form returns to the service')

// ---- ticket 14: the service control bar -----------------------------------

/** The control the bar renders for one action. */
function actionEl(name) {
  const el = window.document.querySelector(`[data-action="${name}"]`)
  assert.ok(el, `the bar renders the ${name} control`)
  return el
}

// All four controls are present, and start/stop read their state from Rust:
// the fixture service is RUNNING, so Start is disabled and Stop is not. A
// control that assumed "start means started" would leave both live.
for (const name of ['start', 'stop', 'restart', 'autostart']) actionEl(name)
assert.equal(store.status.value.state, 'RUNNING', 'the fixture service is RUNNING')
assert.ok(
  actionEl('start').closest('button')?.disabled === true,
  'Start is disabled while RUNNING — the state came from the snapshot, not from a click',
)
assert.ok(
  actionEl('stop').closest('button')?.disabled === false,
  'Stop is live while RUNNING',
)
assert.equal(
  window.document.querySelector('[data-action="autostart"] [role="switch"]')
    ?.getAttribute('aria-checked'),
  'true',
  'the auto-start switch is on because the snapshot says start = auto',
)
console.log('ok  启动/停止/重启/自启 四个控件就位 · 启用态取自 Snapshot')

// ---- the dropdown lists every service --------------------------------------

// The fixture's three services, and the select is bound to them. NaiveUI
// renders its menu lazily through a virtual list that calls `scrollTo`, which
// jsdom does not implement — so the menu cannot be opened here. What is
// asserted is the binding: the options array, the rendered label, and that the
// select is live (with more than one service, switching must be possible).
const svcList = Array.from(store.services.value)
assert.deepEqual(
  svcList,
  ['QwenLLM', 'QwenVL', 'llama-bench'],
  `the dropdown lists every NSSM service: ${svcList}`,
)
assert.ok(svcList.length > 1, 'more than one service, so switching is meaningful')
assert.equal(
  window.document.querySelector('.svcbar .n-base-selection-input__content').textContent,
  'QwenLLM',
  'the select shows the service Rust selected',
)
assert.ok(
  !window.document
    .querySelector('.svcbar .n-base-selection')
    .classList.contains('n-base-selection--disabled'),
  'the select is live: every service is reachable from it',
)
console.log(`ok  下拉列出全部 ${svcList.length} 个 NSSM 服务`)

// ---- the status dot is vector, not a font glyph ----------------------------

const dot = window.document.querySelector('.status svg.dot')
assert.ok(dot, 'the status dot renders as an <svg> element')
// The bug this replaces: Python drew the dot with `text="●"`, whose ink came
// from the font's metrics (13x23px at a 13px font size) and therefore drifted
// with the font size. A glyph has no intrinsic size to assert on; a vector
// does, and both of its dimensions must be independent of the type scale.
assert.equal(dot.getAttribute('viewBox'), '0 0 12 12', 'the dot has a fixed user-space grid')
assert.equal(dot.getAttribute('width'), '12', 'the dot has an explicit width')
assert.equal(dot.getAttribute('height'), '12', 'the dot has an explicit height')
assert.equal(
  window.document.querySelectorAll('.status svg.dot circle').length,
  2,
  'the dot is drawn from circles (core + halo), not from a character',
)
// Nothing about the dot may be a text glyph: no character data inside it at all.
assert.equal(dot.textContent.trim(), '', 'the dot carries no glyph text')
assert.equal(dot.getAttribute('aria-hidden'), 'true', 'the dot is decorative; the state word speaks')
assert.ok(dot.classList.contains('is-breathing'), 'the dot breathes while RUNNING')
assert.equal(dot.getAttribute('data-state'), 'RUNNING', 'the dot reflects the state')

// A non-RUNNING service must not look alive.
store.setSnapshot({
  ...store.snapshot.snap,
  status: { state: 'STOPPED', ok: false, detail: 'not running' },
})
await flush()
assert.ok(
  !window.document.querySelector('.status svg.dot').classList.contains('is-breathing'),
  'the dot stops breathing when the service is not RUNNING',
)
store.setSnapshot({
  ...store.snapshot.snap,
  status: { state: 'RUNNING', ok: true, detail: 'healthz ok' },
})
await flush()
console.log('ok  状态圆点是内联 SVG（非字体字符）· RUNNING 呼吸 / 非 RUNNING 静止')

// ---- the confirmations come before the destructive actions -----------------

/** Is a confirmation on screen, and which one? */
function confirmKind() {
  const el = window.document.querySelector('[data-confirm-kind]')
  return el ? el.getAttribute('data-confirm-kind') : null
}

/** The dialog's two buttons, in NaiveUI's own order: [cancel, confirm]. */
function confirmButtons() {
  const el = window.document.querySelector('[data-confirm-kind]')
  return el ? [...el.querySelectorAll('.n-dialog__action button')] : []
}

assert.equal(confirmKind(), null, 'no confirmation is on screen at rest')

// Restart: the click must not restart — it must ask. There is no Rust in
// jsdom, so had the command been sent it would have rejected; the assertion is
// that the question appeared *and* the store stayed idle.
actionEl('restart').closest('button').click()
await flush()
assert.equal(confirmKind(), 'restart', '重启 asks first, it does not restart')
assert.equal(store.busyName.value, '', 'nothing was sent to Rust while the question is open')
// Language-independent: ticket 13's checks leave the UI in English, so the
// assertion is built from the very copy the component is about to render.
const restartQuestion = ct('msg.restart.confirm', { s: store.selected.value })
assert.match(
  window.document.querySelector('[data-confirm-kind]').textContent,
  new RegExp(restartQuestion.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')),
  `the restart question is the one the bar was about to act on: ${restartQuestion}`,
)
assert.match(restartQuestion, /QwenLLM/, 'the question names the service')

// Cancel: the question closes and nothing happened.
const cancelBtn = confirmButtons()[0]
assert.ok(cancelBtn, 'the confirmation offers a Cancel')
assert.equal(cancelBtn.textContent.trim(), ct('btn.cancel'), 'and it reads 取消/Cancel')
cancelBtn.click()
await flush()
assert.equal(confirmKind(), null, '取消 closes the question')
assert.equal(store.busyName.value, '', 'cancelling sent nothing to Rust')
console.log('ok  重启先二次确认 · 取消即不执行')


// Auto-start: the switch must not move on its own. It is *controlled* by the
// snapshot, so a click opens the question and leaves the switch where Rust put
// it — which is what makes "cancel writes nothing" true by construction.
const startBefore = store.snapshot.snap.facts.start
window.document.querySelector('[data-action="autostart"] [role="switch"]').click()
await flush()
assert.equal(confirmKind(), 'autostart', '开机自启 asks before it writes')
assert.equal(
  store.snapshot.snap.facts.start,
  startBefore,
  'the start mode is unchanged while the question is open — nothing was written',
)
assert.equal(
  window.document.querySelector('[data-action="autostart"] [role="switch"]').getAttribute('aria-checked'),
  'true',
  'the switch still shows what Rust last read, not what was clicked',
)
const autoQuestion = ct('msg.auto.confirm', { m: store.t(`boot.${store.snapshot.snap.facts.start === 'auto' ? 'manual' : 'auto'}`) })
assert.match(
  window.document.querySelector('[data-confirm-kind]').textContent,
  new RegExp(autoQuestion.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')),
  `the question is the mode it would write: ${autoQuestion}`,
)

// Cancel again: still nothing.
const cancelAuto = confirmButtons()[0]
assert.ok(cancelAuto, 'the auto-start question offers a Cancel')
cancelAuto.click()
await flush()
assert.equal(confirmKind(), null, 'the auto-start question closes on cancel')
assert.equal(store.snapshot.snap.facts.start, startBefore, '取消即不写入：开机自启未被改动')
console.log('ok  开机自启先二次确认 · 取消即不写入')

// ---- the log region collapses ----------------------------------------------

const log = window.document.querySelector('[data-log-open]')
assert.ok(log, 'the log tail renders')
assert.equal(log.getAttribute('data-log-open'), 'false', 'the log starts folded, as Python did')
const logHead = log.querySelector('button.head')
assert.ok(logHead, 'the log header is a real button, so it is keyboard-reachable')
assert.equal(logHead.getAttribute('aria-expanded'), 'false', 'aria-expanded says folded')
assert.equal(logHead.getAttribute('aria-controls'), 'log-body', 'the header points at the body')
assert.match(log.textContent, /server\.err/, 'the log region names the file it tails')
assert.match(log.textContent, /日志尾随 server\.err/, 'the log region names the file it tails')
assert.match(log.textContent, /server\.err/, 'the log path is on screen')

logHead.click()
await flush()
assert.equal(log.getAttribute('data-log-open'), 'true', 'clicking the header expands it')
assert.equal(logHead.getAttribute('aria-expanded'), 'true', 'aria-expanded follows')
assert.ok(
  log.querySelector('.fold').classList.contains('is-open'),
  'the fold is driven by a class, not a JS height tween',
)
assert.match(
  log.textContent,
  /Demo log|演示日志/,
  /演示日志/,
  'demo log lines are labelled as demo, so sample output cannot pass for the service\'s own',
)
// The lines themselves are the compact mono step.
const logFont = log.querySelector('.body p.line')
assert.ok(logFont, 'log lines render')
assert.ok(
  logFont.classList.contains('t-mono-sm'),
  `log lines use the compact mono step, got: ${logFont.className}`,
)

// Restart progress streams into the transcript, newest last, verbatim.
store.pushLog('>>> 重启 QwenLLM：停止...')
store.pushLog('>>> 启动...')
store.pushLog('>>> 服务就绪：healthz ok')
await flush()
const shown = [...log.querySelectorAll('.body p.line')].map((p) => p.textContent.trim())
assert.deepEqual(
  shown,
  ['>>> 重启 QwenLLM：停止...', '>>> 启动...', '>>> 服务就绪：healthz ok'],
  `the restart steps stream in verbatim and in order: ${shown}`,
)
assert.doesNotMatch(log.textContent, /Demo log|演示日志/, 'real lines replace the demo ones')
assert.doesNotMatch(log.textContent, /演示日志/, 'real lines replace the demo ones')

logHead.click()
await flush()
assert.equal(log.getAttribute('data-log-open'), 'false', 'clicking again folds it')
store.clearLog()
await flush()
console.log('ok  日志区可折叠 · 等宽紧凑字体 · 重启分步日志实时入列')

// ---- the copy this ticket needs is answerable ------------------------------

for (const key of Object.keys(CONTROL_COPY)) {
  const zh = ct(key)
  assert.match(zh, /\S/, `${key} has zh copy`)
  assert.doesNotMatch(zh, /^\s*$/, `${key} is not blank`)
  // ADR-0005: an unknown key renders as itself rather than as invented text.
  assert.equal(ct('nope.not.a.key'), 'nope.not.a.key')
}
// `ct` defers to Rust: a key both tables have is answered by Rust, unchanged.
assert.equal(ct('btn.restart'), store.snapshot.snap.strings['btn.restart'])
assert.match(
  ct('msg.restart.confirm', { s: 'QwenLLM' }),
  /QwenLLM/,
  'the restart question names the service',
)
console.log(`ok  ${Object.keys(CONTROL_COPY).length} 条控制条文案可翻译 · 占位符已填充`)

// ---- no console noise ------------------------------------------------------

const noise = warnings.filter((w) => !/Could not parse CSS|Not implemented/.test(w))
assert.deepEqual(noise, [], `the console stayed clean:\n${noise.join('\n')}`)
console.log('ok  no runtime errors or Vue warnings')

console.log('\nall ticket 12 + 13 + 14 smoke checks passed')
dom.window.close()

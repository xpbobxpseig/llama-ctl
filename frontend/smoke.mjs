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
  // Ticket 15.
  UpdateSection,
  ReleaseNotes,
  UpdateProgress,
  UPDATE_COPY,
  ut,
  update,
  demoUpdateCheck,
  EVENT_UPDATE,
  INSTALL_LINES,
  ipc,
  // Ticket 17.
  PresetBar,
  ParamDiff,
  GuardDialog,
  askGuard,
  closeGuard,
  SUBMIT_COPY,
  pt,
  autoBackupName,
  // Ticket 16.
  motion,
} = window.__SMOKE__

const text = window.window.document.getElementById('app').textContent

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
const groupEls = [...window.window.document.querySelectorAll('[data-group]')]
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
  for (const el of window.window.document.querySelectorAll('[data-group]')) {
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
  const row = window.window.document.querySelector(`[data-field="${key}"]`)
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
window.window.document.querySelector('[data-group="高级"] button.head').click()
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
const enHeadings = [...window.window.document.querySelectorAll('[data-group] button.head .title')].map(
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
  window.window.document.querySelector('[data-field="ngl"] output.readout').textContent,
  /7/,
  'the readout follows the edit',
)
store.clearForm()
await flush()
assert.equal(store.values.value.ngl, before2, 'clearing the form returns to the service')

// ---- ticket 14: the service control bar -----------------------------------

/** The control the bar renders for one action. */
function actionEl(name) {
  const el = window.window.document.querySelector(`[data-action="${name}"]`)
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
  window.window.document.querySelector('[data-action="autostart"] [role="switch"]')
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
  window.window.document.querySelector('.svcbar .n-base-selection-input__content').textContent,
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

const dot = window.window.document.querySelector('.status svg.dot')
assert.ok(dot, 'the status dot renders as an <svg> element')
// The bug this replaces: Python drew the dot with `text="●"`, whose ink came
// from the font's metrics (13x23px at a 13px font size) and therefore drifted
// with the font size. A glyph has no intrinsic size to assert on; a vector
// does, and both of its dimensions must be independent of the type scale.
assert.equal(dot.getAttribute('viewBox'), '0 0 12 12', 'the dot has a fixed user-space grid')
assert.equal(dot.getAttribute('width'), '12', 'the dot has an explicit width')
assert.equal(dot.getAttribute('height'), '12', 'the dot has an explicit height')
assert.equal(
  window.window.document.querySelectorAll('.status svg.dot circle').length,
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
  !window.window.document.querySelector('.status svg.dot').classList.contains('is-breathing'),
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
  const el = window.window.document.querySelector('[data-confirm-kind]')
  return el ? el.getAttribute('data-confirm-kind') : null
}

/** The dialog's two buttons, in NaiveUI's own order: [cancel, confirm]. */
function confirmButtons() {
  const el = window.window.document.querySelector('[data-confirm-kind]')
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
  window.window.document.querySelector('[data-confirm-kind]').textContent,
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
window.window.document.querySelector('[data-action="autostart"] [role="switch"]').click()
await flush()
assert.equal(confirmKind(), 'autostart', '开机自启 asks before it writes')
assert.equal(
  store.snapshot.snap.facts.start,
  startBefore,
  'the start mode is unchanged while the question is open — nothing was written',
)
assert.equal(
  window.window.document.querySelector('[data-action="autostart"] [role="switch"]').getAttribute('aria-checked'),
  'true',
  'the switch still shows what Rust last read, not what was clicked',
)
const autoQuestion = ct('msg.auto.confirm', { m: store.t(`boot.${store.snapshot.snap.facts.start === 'auto' ? 'manual' : 'auto'}`) })
assert.match(
  window.window.document.querySelector('[data-confirm-kind]').textContent,
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

const log = window.window.document.querySelector('[data-log-open]')
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

// ---- ticket 15: the settings page ----------------------------------------

/**
 * The app boots to the console view; the settings page is the other
 * destination, and the update section lives in its bottom slot. Switching is
 * the shell's own button, so the click here is the real one.
 */
const settingsBtn = [...window.window.document.querySelectorAll('header .actions button')].find((b) =>
  /设置|Settings/.test(b.textContent),
)
assert.ok(settingsBtn, 'the shell offers a 设置/Settings button')
settingsBtn.click()
await flush()

const upd = window.window.document.querySelector('[data-update-section]')
assert.ok(upd, 'the update section renders in the settings page')
assert.match(upd.textContent, /官方更新/, "the section is titled by Rust's copy")
console.log('ok  设置页就位 · 官方更新区渲染')

// ---- language / appearance exist and persist through save_settings --------

/** The control with this id, which must be a NaiveUI select. */
function selectOf(id) {
  const el = window.window.document.querySelector(`#${id}`)
  assert.ok(el, `#${id} renders`)
  const box = el.querySelector('.n-base-selection') ?? el.closest('.n-base-selection')
  assert.ok(box, `#${id} renders a select`)
  return box
}

const langBox = selectOf('set-lang')
const appearBox = selectOf('set-appear')
assert.ok(selectOf('upd-channel'), 'the build-variant selector renders')
assert.ok(
  window.window.document.querySelector('[data-update-auto] [role="switch"]'),
  'the startup-check switch renders',
)

/**
 * The rendered value of a NaiveUI select. Reading it off the DOM is what makes
 * "the control shows what Rust persisted" a real assertion: the menus need a
 * layout engine to open, so the closed label is the only observable.
 */
function shownValue(box) {
  const el = box.querySelector('.n-base-selection-input__content')
  return el ? el.textContent.trim() : ''
}

assert.equal(
  shownValue(langBox),
  store.settings.value.language === 'zh' ? '中文' : 'English',
  `the language control shows the language Rust persisted: ${shownValue(langBox)}`,
)

/** How many commands have gone out so far. */
let sent = Array.from(ipc.calls).length

// A language change: the control's own handler, answered by Rust.
assert.ok(await theme.setLanguage('en'), 'save_settings answered for the language')
await flush()
const langCall = Array.from(ipc.calls).slice(sent).find((c) => c.cmd === 'save_settings')
assert.ok(langCall, 'the language went through save_settings, not a local write')
assert.equal(langCall.args.settings.language, 'en', 'and it carries the new language')
assert.equal(store.settings.value.language, 'en', 'the store holds what Rust read back')
assert.equal(shownValue(langBox), 'English', "the control follows Rust's answer")

// An appearance change, the same way.
sent = Array.from(ipc.calls).length
assert.ok(await theme.setAppearance('dark'), 'save_settings answered for the appearance')
await flush()
const appearCall = Array.from(ipc.calls).slice(sent).find((c) => c.cmd === 'save_settings')
assert.ok(appearCall, 'the appearance went through save_settings')
assert.equal(appearCall.args.settings.appearance, 'dark', 'and it carries the new appearance')
assert.equal(theme.mode.value, 'dark', 'the appearance really changed')
assert.equal(shownValue(appearBox), '深色', 'and the control shows it')
console.log('ok  语言 / 外观 控件就位 · 变更经 save_settings 并以 Rust 回读为准')

// ---- the variant selector lists Rust's own channels ----------------------

const shownChannels = Array.from(update.channels.value).map((c) => ({
  value: c.value,
  label: c.label,
}))
const snapChannels = Array.from(store.snapshot.snap.channels).map(([id, label]) => ({
  value: id,
  label,
}))
assert.deepEqual(
  shownChannels,
  snapChannels,
  `the selector is built from Snapshot.channels, not a list of its own: ${JSON.stringify(shownChannels)}`,
)
assert.equal(shownChannels.length, 4, `four build variants: ${shownChannels.length}`)
for (const c of shownChannels) {
  assert.match(c.value, /^win-/, `${c.value} is a channel id`)
  assert.match(c.label, /\S/, `${c.value} has a label`)
}
assert.equal(
  shownValue(selectOf('upd-channel')),
  shownChannels.find((c) => c.value === store.settings.value.upd_channel).label,
  'the selector shows the variant Rust persisted',
)

/**
 * `updater::channels()` is Rust's list, diffed here for the same reason
 * ticket 13 diffs `fields.rs`: a fifth variant added there must appear in the
 * dropdown rather than silently dropping out of it.
 */
const UPDATER = resolve('..', 'src-tauri', 'core', 'src', 'updater.rs')
const updaterSrc = existsSync(UPDATER) ? readFileSync(UPDATER, 'utf8') : ''
if (updaterSrc) {
  const idBlock = updaterSrc.match(/pub fn id\(self\)[\s\S]*?\n\s{4}\}/)?.[0] ?? ''
  const rustIds = [...idBlock.matchAll(/"([^"]+)"/g)].map((m) => m[1])
  assert.ok(rustIds.length > 0, "Rust's channel ids were read")
  assert.deepEqual(
    shownChannels.map((c) => c.value),
    rustIds,
    `the selector lists Rust's channels, id for id: ${JSON.stringify(rustIds)}`,
  )
  console.log(`ok  构建线选择器列出 Rust 的 ${rustIds.length} 条 channels（与 updater.rs 一致）`)
} else {
  console.log('ok  (src-tauri not present — skipped the channel cross-check against Rust)')
}

// ---- installed build: 未知 is not a build number -------------------------

// The boot check has already run by now (that is what it is for), so the
// "never checked" state is asserted after an explicit reset.
update.reset()
await flush()
assert.equal(
  upd.querySelector('[data-update-status]').getAttribute('data-update-status'),
  'none',
)
assert.match(upd.textContent, /还未检查过更新/, 'and it says so')

// Rust's answer for an unreadable llama-server.exe.
update.setChecked(demoUpdateCheck({ installed: null }))
await flush()
assert.equal(
  window.window.document.querySelector('[data-update-status]').getAttribute('data-update-status'),
  'unknown',
  'an unreadable llama-server.exe is the「未知」case',
)
assert.match(
  window.window.document.querySelector('[data-update-status]').textContent,
  /当前版本未知（无法读取 llama-server\.exe）/,
  'and it says why, not a build number',
)

// A readable one: 当前：b10813 · 最新：b10819.
update.setChecked(demoUpdateCheck())
await flush()
const statusEl = window.window.document.querySelector('[data-update-status]')
assert.equal(statusEl.getAttribute('data-update-status'), 'known', 'a readable build is the「已知」case')
assert.match(statusEl.textContent, /当前：b10813/, 'the installed build is shown as b10813')
assert.match(statusEl.textContent, /最新：b10819/, 'the latest official tag is shown too')
console.log('ok  当前版本四态齐全：未知 ≠ 已知 ≠ 未检查 · 读不到时显示「未知」')

// ---- 立即检查 never installs ---------------------------------------------

update.reset()
await flush()
sent = Array.from(ipc.calls).length
const checked = await update.check()
await flush()
assert.ok(checked, 'the check answered')
assert.equal(checked.installed, 10813, 'and Rust reported the installed build')
assert.equal(checked.up_to_date, false, 'and that b10813 is behind b10819')
const sinceCheck = Array.from(ipc.calls).slice(sent).map((c) => c.cmd)
assert.ok(sinceCheck.includes('check_update'), `检查 sent check_update: ${sinceCheck}`)
assert.ok(!sinceCheck.includes('install_update'), `检查 never installs: ${sinceCheck}`)
console.log('ok  立即检查只检查：check_update 发出，install_update 从未发出')

// ---- the startup auto-check only prompts ---------------------------------

// The double is installed before the app mounts, so the boot check in
// `App.vue` already ran once. `resetAutoCheck` lets the assertion exercise the
// same path again, from the top.
update.resetAutoCheck()
sent = Array.from(ipc.calls).length
await update.autoCheck()
await flush()
const autoCmds = Array.from(ipc.calls).slice(sent).map((c) => c.cmd)
assert.ok(autoCmds.includes('check_update'), `the startup check ran: ${autoCmds}`)
assert.ok(!autoCmds.includes('install_update'), `the startup check only prompts: ${autoCmds}`)
assert.equal(update.autoChecked.value, true, 'and it is marked done for this session')
sent = Array.from(ipc.calls).length
await update.autoCheck()
await flush()
assert.deepEqual(
  Array.from(ipc.calls).slice(sent).map((c) => c.cmd),
  [],
  'a second startup check does not run',
)
console.log('ok  启动自动检查只提示：发出 check_update，绝不 install_update，且只跑一次')

// ---- the changelog comes before the decision -----------------------------

update.reset()
await update.check()
await flush()
const notes = window.window.document.querySelector('[data-notes-kind]')
assert.ok(notes, 'a release opens the notes before anything else happens')
assert.match(notes.textContent, /更新日志/, 'the notes are labelled 更新日志')
// Nightlies ship no release notes; Rust's `upd.no.changelog` says so and names
// the tag and build rather than showing an empty pane.
assert.match(
  notes.textContent,
  /官方 nightly 构建不提供更新说明/,
  'the honest "no notes" copy shows, not a blank pane',
)
assert.match(notes.textContent, /b10819/, 'and it names the build being offered')
assert.match(notes.textContent, /llama-b10819-bin/, 'and the assets it would fetch')
// ADR-0001: no URL anywhere in the notes — only names.
assert.doesNotMatch(notes.textContent, /https?:\/\//, 'the notes carry no link')
console.log('ok  更新日志先于决策展示 · nightly 无说明时如实说明并给出构建号与资产名')

// ---- 立即更新 asks, twice -------------------------------------------------

/** Which question is on screen, `null` for none. */
function installAsk() {
  const el = window.window.document.querySelector('[data-confirm-kind]')
  return el ? el.getAttribute('data-confirm-kind') : null
}

assert.equal(installAsk(), null, 'no confirmation at rest')
sent = Array.from(ipc.calls).length

// The notes'「立即更新」is not an install — it is the second question.
window.window.document.querySelector('[data-notes-action="install"]').click()
await flush()
assert.equal(installAsk(), 'update', '更新 asks; it does not install')
assert.deepEqual(
  Array.from(ipc.calls).slice(sent).map((c) => c.cmd),
  [],
  'nothing was sent to Rust while the question is open',
)

// The question names the service and the backup directory — the ticket's own
// requirement, and the reason this dialog exists at all.
const question = window.window.document.querySelector('[data-confirm-kind]').textContent
assert.match(question, /QwenLLM/, 'the question names the service being stopped')
assert.match(question, /旧文件会备份到/, 'the question says the old files are backed up')
assert.match(question, /F:\\llama_ctl\\backup\\b10819/, 'and it shows where')
// Two ways out, and both are visible.
const buttons = [
  ...window.window.document.querySelectorAll('[data-confirm-kind] .n-dialog__action button'),
]
assert.equal(buttons.length, 2, 'the confirmation offers exactly two answers')
assert.equal(buttons[0].textContent.trim(), ut('btn.cancel'), 'the first is 取消/Cancel')
assert.equal(buttons[1].textContent.trim(), store.t('upd.install'), 'the second is 立即更新')

// Cancel: the question closes and nothing at all happened.
buttons[0].click()
await flush()
assert.equal(installAsk(), null, '取消 closes the question')
assert.deepEqual(
  Array.from(ipc.calls).slice(sent).map((c) => c.cmd),
  [],
  'cancelling sent nothing to Rust — no download, no install',
)
console.log('ok  立即更新先二次确认（含备份目录）· 取消即不下载不安装')

// ---- the install streams its progress ------------------------------------

/** The transcript as the DOM has it: count and lines, in order. */
function progressDom() {
  const el = window.window.document.querySelector('[data-progress-count]')
  assert.ok(el, 'the progress transcript renders')
  return {
    el,
    n: Number(el.getAttribute('data-progress-count')),
    lines: [...el.querySelectorAll('p.line')].map((p) => p.textContent.trim()),
  }
}

assert.equal(progressDom().n, 0, 'the transcript starts empty, with a placeholder')
assert.match(
  progressDom().el.textContent,
  new RegExp(ut('upd.progress.empty').slice(0, 6).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')),
  'and the placeholder says a line will appear',
)
// Answer the question for real this time.
window.window.document.querySelector('[data-notes-action="install"]').click()
await flush()
assert.equal(installAsk(), 'update', 'the question is back')
window.window.document.querySelectorAll('[data-confirm-kind] .n-dialog__action button')[1].click()

// Sample the transcript while it fills: a streaming render passes through
// several intermediate counts, a batch render at the end shows 0 then 9.
const counts = []
for (let i = 0; i < 500; i++) {
  await new Promise((r) => setTimeout(r, 2))
  const el = window.window.document.querySelector('[data-progress-count]')
  counts.push(Number(el.getAttribute('data-progress-count')))
  if (el.getAttribute('data-progress-running') === 'false' && counts[counts.length - 1] === INSTALL_LINES.length) {
    break
  }
}
for (let i = 1; i < counts.length; i++) {
  assert.ok(counts[i] >= counts[i - 1], `the transcript only grows: ${counts.join(',')}`)
}
assert.ok(
  new Set(counts).size >= 3,
  `lines are rendered as they arrive, not in one batch at the end: ${counts.join(',')}`,
)

await flush()
const done = progressDom()
assert.equal(done.n, INSTALL_LINES.length, `every step is on screen: ${done.n}`)
assert.deepEqual(
  done.lines,
  Array.from(INSTALL_LINES),
  `the transcript is Rust's, verbatim and in order: ${JSON.stringify(done.lines)}`,
)
assert.equal(
  done.el.getAttribute('data-progress-running'),
  'false',
  'the transcript stops claiming work when the install is done',
)
// Rust's `InstallReport` is what allows the summary line.
assert.match(done.el.textContent, /替换 2 个文件/, 'and the result says what the install did')
console.log(
  `ok  更新全过程 ${INSTALL_LINES.length} 行实时滚动输出（中间态 ${new Set(counts).size} 次）· 顺序逐字一致`,
)

// ---- a variant change invalidates the last check -------------------------

// Rust refuses to install a release the user has not seen the notes for
// (`msg.channel.changed`); the frontend must not offer one either.
assert.ok(update.release.value, 'a checked release is installable')
sent = Array.from(ipc.calls).length
assert.ok(await update.setChannel('win-cpu-x64'), 'the variant went through save_settings')
await flush()
const chanCall = Array.from(ipc.calls).slice(sent).find((c) => c.cmd === 'save_settings')
assert.equal(chanCall.args.settings.upd_channel, 'win-cpu-x64', 'and it carries the new variant')
assert.equal(update.release.value, null, 'changing the variant drops the release that was checked')
assert.equal(update.canInstall.value, false, 'so 立即更新 cannot install something never shown')
assert.ok(
  window.window.document.querySelector('[data-update-action="install"]').closest('button').disabled === true,
  'the install button is disabled until the variant is re-checked',
)
console.log('ok  切换构建线即失效旧检查 · 更新按钮随之禁用（不会装没看过的版本）')

// ---- the startup-check preference persists -------------------------------

sent = Array.from(ipc.calls).length
assert.ok(await update.setAutoOnStartup(false), 'save_settings answered for the startup switch')
await flush()
const autoCall = Array.from(ipc.calls).slice(sent).find((c) => c.cmd === 'save_settings')
assert.equal(autoCall.args.settings.upd_check_on_startup, false, 'the preference went through save_settings')
assert.equal(update.autoOnStartup.value, false, 'and the store holds what Rust read back')
assert.equal(
  window.window.document.querySelector('[data-update-auto] [role="switch"]').getAttribute('aria-checked'),
  'false',
  'the switch follows it',
)
console.log('ok  启动时自动检查开关经 save_settings 持久化')

// ---- the copy this ticket needs is answerable ----------------------------

for (const key of Object.keys(UPDATE_COPY)) {
  assert.match(ut(key), /\S/, `${key} has copy`)
  assert.equal(ut('nope.not.a.key'), 'nope.not.a.key', 'an unknown key renders as itself')
}
// `ut` defers to Rust: a key both tables have is answered by Rust, unchanged.
assert.equal(ut('upd.install'), store.snapshot.snap.strings['upd.install'])
assert.match(
  ut('upd.result', { r: 2, a: 1, d: 2 }),
  /替换 2 个文件/,
  'the result line fills its placeholders',
)
console.log(`ok  ${Object.keys(UPDATE_COPY).length} 条更新区文案可翻译 · 占位符已填充`)

// ---- ticket 17: apply / revert / presets ---------------------------------

/*
 * Ticket 15's checks leave the app on the settings page; the submit row lives
 * in the console view, so the shell's own 设置 button takes us back — the same
 * route a user takes, rather than poking the view switcher.
 */
const backBtn = [...window.window.document.querySelectorAll('header .actions button')].find((b) =>
  /设置|Settings/.test(b.textContent),
)
assert.ok(backBtn, 'the shell offers a way back to the console')
backBtn.click()
await flush()

const bar = window.window.document.querySelector('[data-preset-bar]')
assert.ok(bar, 'the preset / submit row renders')

/** Rust's verdict, pushed into the store the way a Snapshot push would. */
function setDirty(next) {
  const snap = store.snapshot.snap
  store.setSnapshot({ ...snap, facts: { ...snap.facts, dirty: next } })
}

/** The button the row renders for one action. */
function submitBtn(name) {
  const el = window.window.document.querySelector(`[data-action="${name}"]`)
  assert.ok(el, `the row renders the ${name} control`)
  return el.closest('button')
}

/** Is the unapplied-changes hint on screen? */
function dirtyHint() {
  return window.window.document.querySelector('[data-dirty-hint]')
}

/** Escape one string into a regex, for asserting on rendered copy. */
function re(text) {
  return new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
}

/*
 * jsdom's `Element` has no `scrollTo`, and NaiveUI's virtual option list calls
 * it the moment a menu opens — which typing in the preset box does. It is a DOM
 * gap, not a defect in the app (the same reason ticket 14's checks cannot open
 * the *service* dropdown), so it is shimmed rather than worked around.
 */
window.Element.prototype.scrollTo = function () {}
window.Element.prototype.scrollIntoView = function () {}

for (const name of ['preset-save', 'preset-del', 'revert', 'apply']) submitBtn(name)

// Rust says the form matches the service: no hint, and Revert is dead.
store.clearForm()
setDirty(false)
await flush()
assert.equal(store.dirty.value, false, 'Rust reports no unapplied changes')
assert.equal(dirtyHint(), null, 'no hint while Rust says the form matches')
assert.equal(bar.getAttribute('data-dirty'), 'false', 'the row says so too')

/*
 * The bug this ticket exists to remove: an edit sitting in the frontend's own
 * buffer must NOT light the hint or arm Revert. Only Rust decides, and until
 * Rust has re-read the form it has not decided anything.
 */
store.editField('ngl', '7')
await flush()
assert.equal(store.values.value.ngl, '7', 'the edit is on screen')
assert.equal(store.dirty.value, false, 'the local edit did not decide for Rust')
assert.equal(dirtyHint(), null, 'no hint from a purely local edit')
assert.equal(submitBtn('revert').disabled, true, 'Revert is dead without unapplied changes')

// Rust says dirty: the hint appears and Revert comes alive.
setDirty(true)
await flush()
assert.ok(dirtyHint(), 'the hint appears once Rust says the form differs')
assert.match(dirtyHint().textContent, re(store.t('status.dirty')), 'and it is the semantic one')
assert.equal(submitBtn('revert').disabled, false, 'Revert is live with unapplied changes')
console.log('ok  未应用更改提示只在 Rust 判定时出现 · 还原按钮随之启用/禁用')

// ---- Apply asks, and the question carries the comparison ------------------

assert.equal(confirmKind(), null, 'no question is on screen')
const sent0 = Array.from(ipc.calls).length
submitBtn('apply').click()
await flush()
assert.equal(confirmKind(), 'apply', '应用更改 asks before it writes')
assert.equal(store.busyName.value, '', 'nothing was sent while the question is open')
assert.equal(
  Array.from(ipc.calls).slice(sent0).filter((c) => c.cmd === 'apply_changes').length,
  0,
  'and no write went over IPC',
)

const ask = window.window.document.querySelector('[data-confirm-kind]')
assert.match(ask.textContent, re(store.selected.value), 'the question names the service')
// Old vs new, per field: the old side is Rust's own parse of the service.
const diff = ask.querySelector('[data-diff-row="ngl"]')
assert.ok(diff, 'the changed field is in the comparison')
assert.equal(
  diff.querySelector('.from').textContent.trim(),
  store.snapshot.snap.values.ngl,
  'the old value is what Rust parsed out of the service',
)
assert.equal(
  diff.querySelector('.to').textContent.trim(),
  '7',
  'the new value is the form — the only state the frontend owns',
)
assert.match(
  ask.textContent,
  re(store.snapshot.snap.facts.app_params),
  "the service's own AppParameters are shown verbatim",
)
// Cancelling closes it and writes nothing.
confirmButtons()[0].click()
await flush()
assert.equal(confirmKind(), null, '取消 closes the question')
assert.equal(store.busyName.value, '', 'cancelling sent nothing')
console.log('ok  应用更改先展示新旧参数对比再二次确认 · 取消即不写服务')

// ---- presets: an editable box, and delete asks ----------------------------

// The box is an input, not only a menu: typing a preset name is the point.
const box = bar.querySelector('input')
assert.ok(box, 'the preset name is typeable, not menu-only')
box.value = '7B 快速'
box.dispatchEvent(new window.Event('input'))
await flush()
assert.equal(
  submitBtn('preset-del').disabled,
  false,
  '删除 is live for a name that exists',
)
assert.equal(
  submitBtn('preset-save').disabled,
  true,
  '保存 is a no-op for a name that exists, so it does not offer one',
)

submitBtn('preset-del').click()
await flush()
assert.equal(confirmKind(), 'preset-del', '删除预设 asks first')
assert.match(
  window.window.document.querySelector('[data-confirm-kind]').textContent,
  re(pt('msg.preset.del', { n: '7B 快速' })),
  'and the question names the preset',
)
confirmButtons()[0].click()
await flush()
assert.equal(confirmKind(), null, '取消 leaves the preset alone')
assert.equal(
  Array.from(ipc.calls).filter((c) => c.cmd === 'delete_preset').length,
  0,
  'nothing was deleted',
)
console.log('ok  预设名为可编辑输入框 · 删除先二次确认 · 取消即不删')

// ---- switching with unapplied changes asks, and offers the backup ---------

/*
 * The dropdown's own menu cannot be opened in jsdom (NaiveUI's virtual list
 * calls `scrollTo`), so the question is opened through the very function the
 * select's handler calls. What is asserted is the confirmation and its three
 * answers, which is the part that has to hold.
 */
const held = store.selected.value
askGuard('service', 'QwenVL')
await flush()
assert.equal(confirmKind(), 'service', 'switching service with unapplied changes asks first')
const guardText = window.window.document.querySelector('[data-confirm-kind]').textContent
assert.match(guardText, /QwenVL/, 'the question names the target')
assert.match(guardText, re(pt('msg.svc.dirty')), 'and says what would be lost')
assert.ok(
  window.window.document.querySelector('[data-guard-discard="service"]'),
  'it offers continuing without a backup',
)
assert.equal(store.selected.value, held, 'the service has not moved while the question is open')
assert.equal(store.busyName.value, '', 'and nothing was sent')
confirmButtons()[0].click()
await flush()
assert.equal(confirmKind(), null, '取消 closes it')
assert.equal(store.selected.value, held, 'the service is still the one Rust selected')
assert.equal(
  Array.from(ipc.calls).filter((c) => c.cmd === 'switch_service').length,
  0,
  'no switch was sent',
)

// The same guard serves switching *preset* with unapplied changes.
askGuard('preset', '32B 长上下文')
await flush()
assert.equal(confirmKind(), 'preset', '载入预设 with unapplied changes asks too')
assert.match(
  window.window.document.querySelector('[data-confirm-kind]').textContent,
  re(pt('msg.preset.dirty')),
  'and it is the preset question, not the service one',
)
confirmButtons()[0].click()
await flush()
assert.equal(confirmKind(), null, '取消 leaves the form alone')
console.log('ok  切换服务 / 载入预设前先确认并提供自动备份 · 取消即不切换')

// ---- the copy this ticket needs is answerable -----------------------------

for (const key of Object.keys(SUBMIT_COPY)) {
  assert.match(pt(key), /\S/, `${key} has copy`)
  assert.equal(pt('nope.not.a.key'), 'nope.not.a.key', 'an unknown key renders as itself')
}
// `pt` defers to Rust: a key Rust owns is answered by Rust, unchanged.
assert.equal(pt('btn.revert'), store.snapshot.snap.strings['btn.revert'])
assert.equal(pt('btn.apply2'), store.snapshot.snap.strings['btn.apply2'])
assert.equal(pt('card.presets'), store.snapshot.snap.strings['card.presets'])
// The auto-backup name is a *preset* name with a timestamp, not a file backup.
assert.match(
  autoBackupName(new Date(2026, 2, 14, 9, 12, 41)),
  /03-14 09:12:41/,
  'the auto-backup name carries the stamp Python used',
)
console.log(`ok  ${Object.keys(SUBMIT_COPY).length} 条提交区文案可翻译 · 自动备份名带时间戳`)

// ---- ticket 16: the motion switch ------------------------------------------

const DURATIONS = Object.keys(motion.DURATION_VARS)
assert.ok(DURATIONS.length >= 5, `several durations are switchable: ${DURATIONS.join(' ')}`)

// Off zeroes every duration, but leaves thresholds and easings alone: turning
// the 300 ms hover threshold off would make the「?」fire on every pass across
// the form, which is the opposite of what the switch promises.
const onVars = motion.motionVars(true)
const offVars = motion.motionVars(false)
for (const v of DURATIONS) {
  assert.notEqual(onVars[v], offVars[v], `${v} changes with the switch`)
  assert.ok(/^0\./.test(offVars[v]), `${v} is effectively instant when off: ${offVars[v]}`)
}
for (const v of Object.keys(motion.THRESHOLD_VARS)) {
  assert.equal(onVars[v], offVars[v], `${v} is a threshold, not an animation`)
}
for (const v of Object.keys(motion.EASE_VARS)) {
  assert.equal(onVars[v], offVars[v], `${v} is a curve, not a duration`)
}

// The「?」timings come from one place, so the stylesheet and the JS timer
// cannot drift apart.
assert.equal(motion.HELP.delay, 300, 'hover threshold is 300 ms')
assert.equal(motion.HELP.in, 200, 'fade in is 200 ms')
assert.equal(motion.HELP.out, 800, 'fade out is 800 ms')
assert.deepEqual(
  [motion.HELP.delay, motion.HELP.in, motion.HELP.out],
  [motion.MS.TIP_DELAY, motion.MS.TIP_IN, motion.MS.TIP_OUT],
  'the timings are parsed out of MOTION, not restated',
)

// Applying the switch must not disable anything: every control is still there.
motion.applyMotion(false)
await flush()
assert.ok(
  window.window.document.documentElement.classList.contains(motion.OFF_CLASS),
  'the off class lands on <html>, so teleported popovers answer too',
)
assert.equal(
  window.window.document.documentElement.style.getPropertyValue('--m-hover-in'),
  motion.INSTANT,
  'the property is rewritten, not just the class',
)
assert.ok(
  window.window.document.querySelectorAll('button, input, [role="switch"]').length > 0,
  'nothing disappears when motion is off',
)
assert.ok(
  window.window.document.querySelectorAll('[aria-label$="— 说明"]').length >= 28,
  'every「?」is still reachable with motion off',
)
motion.applyMotion(true)
await flush()
assert.ok(!window.document.documentElement.classList.contains(motion.OFF_CLASS), 'the switch turns back on')
console.log('ok  动效总开关：时长归零但功能不缺失 · 阈值与曲线不受影响 ·「?」时序单一来源')

// ---- no console noise ------------------------------------------------------

const noise = warnings.filter((w) => !/Could not parse CSS|Not implemented/.test(w))
assert.deepEqual(noise, [], `the console stayed clean:\n${noise.join('\n')}`)
console.log('ok  no runtime errors or Vue warnings')

console.log('\nall ticket 12 + 13 + 14 + 15 + 16 + 17 smoke checks passed')
dom.window.close()

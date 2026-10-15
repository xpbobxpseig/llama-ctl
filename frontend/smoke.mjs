/**
 * Ticket 12 smoke test — `cd frontend && npm run smoke`.
 *
 * It is the smallest thing that fails if the shell breaks: bundle the real app
 * with the same Vite config as the shipped build, run that bundle in jsdom with
 * no Tauri internals, then assert the theme tokens, the rendered screens, the
 * geometry round trip and the one-way-state rule.
 *
 * Running the *client* bundle rather than SSR-loading the `.vue` files keeps it
 * honest: it is the same artefact shape Tauri loads, booted in the same order.
 *
 * `assert` + jsdom only. The repo has no JS test framework, and adding one for
 * a smoke check nobody asked for would be worse than using the bundler that is
 * already installed.
 */
import assert from 'node:assert/strict'
import { writeFileSync } from 'node:fs'
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
const { store, naiveOverrides, cssVars, TYPE, RADIUS, PALETTES, parseGeometry, formatGeometry } =
  window.__SMOKE__

const text = window.document.getElementById('app').textContent

// ---- the shell renders, not a blank page -----------------------------------

assert.match(text, /llama\.cpp/, 'title bar renders the app title')
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

// ---- no console noise ------------------------------------------------------

const noise = warnings.filter((w) => !/Could not parse CSS|Not implemented/.test(w))
assert.deepEqual(noise, [], `the console stayed clean:\n${noise.join('\n')}`)
console.log('ok  no runtime errors or Vue warnings')

console.log('\nall ticket 12 smoke checks passed')
dom.window.close()

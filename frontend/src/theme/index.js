/**
 * Design tokens — the single source of truth.
 *
 * Direction: a warm, precision instrument. The palette is bone paper and
 * charcoal rather than cold grey; the one interaction hue is a deep forest
 * green; the commit action stays ink. The type scale is deliberately
 * editorial — 28 / 20 / 15 / 13 / 12 / 11 — so the state headline, the page
 * title and a group heading are three distinct voices instead of one.
 *
 * Three rules keep the surface calm:
 *
 *   1. **Ink commits, forest interacts.** Buttons that write are filled with
 *      `PRIMARY` (near-black in light, warm white in dark). `ACC` belongs to
 *      sliders, switches, focus, links and the open group — never to a second
 *      primary button.
 *   2. **Status colours never decorate.** RUN / WARN / ERR paint the state dot,
 *      the dirty badge and destructive text, and nothing else.
 *   3. **Depth is a hairline.** Panels have a border, not a shadow. The only
 *      raised surface is an overlay (dialog, popover, menu).
 *
 * Fonts stay local (ADR-0001: no @font-face, nothing fetched). The stacks name
 * the Windows families that actually ship on the target machine, then fall
 * back through the generic families. `FONT_DISPLAY` is Segoe UI Variable's
 * display optical size, used only for 20px-and-up headings; body copy keeps
 * the text optical size.
 */

// ---- palettes --------------------------------------------------------------

/**
 * Light: macOS 白。纯白卡面浮在 #f5f5f7 的画布上，中性灰发丝线，近黑墨色。
 *
 * Contrast (WCAG 2.1, sRGB) against BG: ink 15.46:1, secondary 8.35:1,
 * muted 4.66:1, forest 5.84:1, run 4.83:1, amber 4.80:1, error 5.45:1.
 * Every text role clears AA at its intended size; muted is the floor.
 */
const LIGHT = {
  BG: '#f5f5f7',
  RAIL: '#fbfbfd',
  CARD: '#ffffff',
  FIELD: '#f0f0f3',
  BORDER: '#e3e3e8',
  BORDER_STRONG: '#c9c9d1',
  BORDER_SOFT: '#ececf1',
  TXT: '#1d1d1f',
  TXT2: '#48484d',
  MUT: '#6e6e73',
  ACC: '#1f6b58',
  ACCH: '#175244',
  ACC_SOFT: '#e6f2ee',
  PRIMARY: '#1d1d1f',
  PRIMARY_HOVER: '#2c2c2e',
  PRIMARY_ON: '#f5f5f7',
  SWITCH: '#1f6b58',
  RUN: '#2b7a4d',
  RUN_SOFT: '#e4f2e8',
  ORG: '#9a5f0f',
  WARN_SOFT: '#f8efe0',
  RED: '#b23a30',
  ERR_SOFT: '#fbe9e6',
  GRAY: '#a8a8ad',
  STOP: '#8e8e93',
  TIP: '#ffffff',
  CODE: '#f6f6f8',
  HOVER: '#f2f2f6',
  ACTIVE: '#e8e8ee',
  FOCUS: 'rgba(31, 107, 88, 0.18)',
  SHADOW: 'none',
  // The one shadow in the system: overlays only (dialog, popover, menu).
  SHADOW_RAISED:
    '0 18px 48px rgba(0, 0, 0, 0.16), 0 0 0 1px rgba(0, 0, 0, 0.04)',
}

/** Dark: the same system, inverted, with the forest and status hues lifted. */
const DARK = {
  BG: '#171614',
  RAIL: '#1c1a17',
  CARD: '#211f1b',
  FIELD: '#272420',
  BORDER: '#35312b',
  BORDER_STRONG: '#49433b',
  BORDER_SOFT: '#2b2823',
  TXT: '#eae5dd',
  TXT2: '#c0b9ae',
  MUT: '#a49e94',
  ACC: '#6ec9a8',
  ACCH: '#8fdcc0',
  ACC_SOFT: '#1b2f28',
  PRIMARY: '#eae5dd',
  PRIMARY_HOVER: '#fbf9f4',
  PRIMARY_ON: '#171614',
  SWITCH: '#2f8f73',
  RUN: '#5fd08d',
  RUN_SOFT: '#183024',
  ORG: '#e0b062',
  WARN_SOFT: '#322817',
  RED: '#ed8076',
  ERR_SOFT: '#351d1a',
  GRAY: '#5f5a52',
  STOP: '#7a746b',
  TIP: '#211f1b',
  CODE: '#131210',
  HOVER: '#272420',
  ACTIVE: '#2f2b26',
  FOCUS: 'rgba(110, 201, 168, 0.30)',
  SHADOW: 'none',
  SHADOW_RAISED: '0 22px 60px rgba(0, 0, 0, 0.60)',
}

export const PALETTES = { light: LIGHT, dark: DARK }

// ---- type ------------------------------------------------------------------

/**
 * Six UI steps, strictly decreasing: 28 / 20 / 15 / 13 / 12 / 11.
 *
 * DISPLAY is the state headline and the settings page title. SECTION is a page
 * or parameter title. GROUP is a collapsible group header. BODY is every
 * control label, input and button. Mono stays 13 so a value and its label share
 * a baseline; the log step is 12 for a little more air.
 */
export const TYPE = {
  DISPLAY: 28, // state headline / settings title
  SECTION: 20, // page + section title
  GROUP: 15, // collapsible group header
  BODY: 13, // labels, buttons, inputs
  SMALL: 12, // helper text
  MICRO: 11, // eyebrows, metadata
  MONO: 13, // numeric readouts
  MONO_SM: 12, // log lines
}

/**
 * Display / body / mono stacks.
 *
 * `Segoe UI Variable` is the Windows 11 UI face; the Display optical size is
 * used for headings above body size. `Microsoft YaHei UI` covers the Chinese
 * glyphs; Cascadia Mono is the default Windows terminal mono.
 */
export const FONT_UI =
  '"Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI", "PingFang SC", system-ui, sans-serif'
export const FONT_DISPLAY =
  '"Segoe UI Variable Display", "Segoe UI", "Microsoft YaHei UI", "PingFang SC", system-ui, sans-serif'
export const FONT_MONO =
  '"Cascadia Mono", Consolas, "SFMono-Regular", "DejaVu Sans Mono", monospace'

// ---- geometry & motion -----------------------------------------------------

/** 12px panels, 8px controls, 6px chips. Restrained, not pill-shaped. */
export const RADIUS = { CARD: '12px', CONTROL: '8px', CHIP: '6px', PILL: '999px' }

/** 4/8/12/16/20/24/32. Every gap in the app is one of these. */
export const SPACE = { XS: 4, SM: 8, MD: 12, LG: 16, XL: 20, XXL: 24, XXXL: 32 }

/**
 * Elevation. Panels get a hairline, never a shadow — the whole point of the
 * canvas is that depth is carried by contrast, not by blur.
 */
export const SHADOW = {
  light: LIGHT.SHADOW,
  dark: DARK.SHADOW,
  raised: {
    light: LIGHT.SHADOW_RAISED,
    dark: DARK.SHADOW_RAISED,
  },
}

/**
 * Motion tokens.
 *
 * Fast in (the control answers the pointer), slow out (the highlight decays),
 * and one 200ms entrance for a view. The「?」timings are a single source: the
 * 300ms threshold is anti-mistouch and is *not* governed by the motion switch.
 */
export const MOTION = {
  HOVER_IN: '120ms',
  HOVER_OUT: '600ms',
  ENTER: '200ms',
  TIP_DELAY: '300ms',
  TIP_IN: '200ms',
  TIP_OUT: '800ms',
  EASE_OUT: 'cubic-bezier(0.2, 0, 0, 1)',
  EASE_DECAY: 'cubic-bezier(0.4, 0, 0.2, 1)',
}

// ---- NaiveUI overrides -----------------------------------------------------

/**
 * NaiveUI ships a 14px, 3px-radius, green-primary world. This object maps every
 * component the app actually renders back onto the tokens above, so a library
 * control and a hand-written one cannot disagree about a colour or a radius.
 *
 * The library is used for *behaviour* — focus management, virtualised options,
 * sliders — not for its look. Anything below that reads like a second design
 * language is a bug.
 */

// ---- custom properties -----------------------------------------------------

/** The custom properties every plain-DOM element reads. */
export function cssVars(mode) {
  const p = PALETTES[mode] ?? LIGHT
  return {
    '--bg': p.BG,
    '--rail': p.RAIL,
    '--card': p.CARD,
    '--field': p.FIELD,
    '--border': p.BORDER,
    '--border-strong': p.BORDER_STRONG,
    '--border-soft': p.BORDER_SOFT,
    '--txt': p.TXT,
    '--txt-2': p.TXT2,
    '--mut': p.MUT,
    '--acc': p.ACC,
    '--acch': p.ACCH,
    '--acc-soft': p.ACC_SOFT,
    '--acc-on': p.PRIMARY_ON,
    '--primary': p.PRIMARY,
    '--primary-hover': p.PRIMARY_HOVER,
    '--primary-on': p.PRIMARY_ON,
    '--run': p.RUN,
    '--run-soft': p.RUN_SOFT,
    '--org': p.ORG,
    '--warn-soft': p.WARN_SOFT,
    '--red': p.RED,
    '--err-soft': p.ERR_SOFT,
    '--gray': p.GRAY,
    '--stop': p.STOP,
    '--tip': p.TIP,
    '--code': p.CODE,
    '--hover': p.HOVER,
    '--active': p.ACTIVE,
    '--focus-ring': p.FOCUS,
    '--r-card': RADIUS.CARD,
    '--r-ctl': RADIUS.CONTROL,
    '--r-chip': RADIUS.CHIP,
    '--r-pill': RADIUS.PILL,
    '--shadow': SHADOW[mode],
    '--shadow-raised': SHADOW.raised[mode],
    // Spacing on the 4px rhythm. `global.css` reads only these, never a literal,
    // so the rhythm cannot drift per component.
    '--sp-xs': `${SPACE.XS}px`,
    '--sp-sm': `${SPACE.SM}px`,
    '--sp-md': `${SPACE.MD}px`,
    '--sp-lg': `${SPACE.LG}px`,
    '--sp-xl': `${SPACE.XL}px`,
    '--sp-xxl': `${SPACE.XXL}px`,
    '--sp-xxxl': `${SPACE.XXXL}px`,
    '--f-display': `${TYPE.DISPLAY}px`,
    '--f-section': `${TYPE.SECTION}px`,
    '--f-group': `${TYPE.GROUP}px`,
    '--f-body': `${TYPE.BODY}px`,
    '--f-small': `${TYPE.SMALL}px`,
    '--f-micro': `${TYPE.MICRO}px`,
    '--f-mono': `${TYPE.MONO}px`,
    '--f-mono-sm': `${TYPE.MONO_SM}px`,
    '--font-ui': FONT_UI,
    '--font-display': FONT_DISPLAY,
    '--font-mono': FONT_MONO,
    '--m-hover-in': MOTION.HOVER_IN,
    '--m-hover-out': MOTION.HOVER_OUT,
    '--m-enter': MOTION.ENTER,
    '--m-ease-out': MOTION.EASE_OUT,
    '--m-ease-decay': MOTION.EASE_DECAY,
    '--m-tip-delay': MOTION.TIP_DELAY,
    '--m-tip-in': MOTION.TIP_IN,
    '--m-tip-out': MOTION.TIP_OUT,
  }
}

/** `"system" | "light" | "dark"` → the appearance actually in effect. */
export function resolveMode(preference, systemIsDark) {
  if (preference === 'light' || preference === 'dark') return preference
  return systemIsDark ? 'dark' : 'light'
}

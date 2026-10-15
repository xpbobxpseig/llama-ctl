/**
 * The one source of truth for the app's design tokens (ticket 12).
 *
 * NaiveUI is used for *components only* — slider, select, modal, popover —
 * and its default theme (3px radius, green `#18a058` primary, 14px base) is
 * wrong for this app. Everything below overrides it back to the existing
 * CustomTkinter design language, token for token:
 *
 *   palettes  ← llama_ctl_gui.py L425-442 (`PALETTES`)
 *   type scale← llama_ctl_gui.py L497-504 (`F_DISPLAY` … `F_MONO_SM`),
 *               cross-checked against the left panel of
 *               docs/design/naiveui-vs-current.html
 *   radii     ← 12px cards / 8px controls (same file, `--RAD` / `--RAD_S`)
 *
 * Rules this module holds the rest of the app to:
 *   - the six type steps decrease strictly: 18 > 15 > 13 = 13 > 12 > 11.
 *     `F_GROUP` and `F_BODY` are both 13 and are told apart by weight, never
 *     by size — Tk has only normal|bold, and that split is what gives the
 *     group headers their own rank.
 *   - UI text is Microsoft YaHei UI; **numbers and log lines** are Cascadia
 *     Mono with a Consolas fallback. Both are system fonts (ADR-0001: no
 *     remote font, no @font-face).
 *   - light and dark are isomorphic: the accent blue does not move.
 */

// ---- palettes --------------------------------------------------------------

/** The light palette, verbatim from `PALETTES["light"]`. */
const LIGHT = {
  BG: '#f5f5f7',
  CARD: '#ffffff',
  BORDER: '#e3e3e8',
  FIELD: '#fafafa',
  TXT: '#1d1d1f',
  MUT: '#86868b',
  ACC: '#0a84ff',
  ACCH: '#0071e3',
  RED: '#ff3b30',
  ORG: '#ff9500',
  GRAY: '#aeaeb2',
  RUN: '#30d158',
  STOP: '#8e8e93',
  TIP: '#f0f0f2',
}

/** The dark palette, verbatim from `PALETTES["dark"]`. */
const DARK = {
  BG: '#1e1e20',
  CARD: '#2c2c2e',
  BORDER: '#3a3a3c',
  FIELD: '#252527',
  TXT: '#f5f5f7',
  MUT: '#98989d',
  ACC: '#0a84ff',
  ACCH: '#0071e3',
  RED: '#ff453a',
  ORG: '#ff9f0a',
  GRAY: '#636366',
  RUN: '#30d158',
  STOP: '#636366',
  TIP: '#2c2c2e',
}

export const PALETTES = { light: LIGHT, dark: DARK }

// ---- type ------------------------------------------------------------------

/** The six steps. Strictly decreasing, with 13 shared by group + body. */
export const TYPE = {
  DISPLAY: 18, // window title
  SECTION: 15, // card title
  GROUP: 13, // collapsible group header (bold)
  BODY: 13, // labels, buttons, inputs
  SMALL: 12, // helper text
  MICRO: 11, // status sub-line
  MONO: 13, // numeric readouts — same size as BODY so baselines align
  MONO_SM: 11, // log lines
}

export const FONT_UI = '"Microsoft YaHei UI", system-ui, -apple-system, sans-serif'
export const FONT_MONO = '"Cascadia Mono", Consolas, "Courier New", monospace'

// ---- geometry & motion -----------------------------------------------------

/** Card radius; controls get the smaller one. */
export const RADIUS = { CARD: '12px', CONTROL: '8px' }
/** 4px rhythm: every gap below is a multiple of 4. */
export const SPACE = { XS: 4, SM: 8, MD: 12, LG: 16, XL: 24 }
export const SHADOW = {
  light: '0 1px 2px rgba(0, 0, 0, 0.04)',
  dark: '0 1px 2px rgba(0, 0, 0, 0.25)',
}

/**
 * Motion tokens. Ticket 16 owns the full motion system; these are the two
 * durations the shell already needs, and they are deliberately short because
 * they carry **state**, not decoration: hover/press must answer immediately.
 */
export const MOTION = {
  HOVER_IN: '100ms', // button reaches its highlight and stays
  HOVER_OUT: '800ms', // exponential-feeling decay back to rest
  ENTER: '260ms', // card / view entrance
  EASE_OUT: 'cubic-bezier(0.22, 1, 0.36, 1)', // spring-like, no overshoot
  EASE_DECAY: 'cubic-bezier(0.4, 0, 0.2, 1)',
}

// ---- NaiveUI theme overrides -----------------------------------------------

/**
 * The NaiveUI `GlobalThemeOverrides` for one resolved appearance.
 *
 * NaiveUI derives most of its own surface colours from `common`, and the
 * handful it composes rather than copies (`buttonColor2Hover` and friends)
 * are pinned explicitly so a hover state cannot drift back to green.
 *
 * `fontSize` is the base every component multiplies; setting it to BODY (13)
 * is what turns NaiveUI's 14px world into this app's 13px one. Components
 * that need a larger step take it from `TYPE`, not from a second base.
 */
export function naiveOverrides(mode) {
  const p = PALETTES[mode] ?? LIGHT
  const dark = mode === 'dark'
  return {
    common: {
      // Fonts first: NaiveUI's `v-sans` / `v-mono` are its own stacks, and
      // leaving them in place would render every label in the wrong family.
      fontFamily: FONT_UI,
      fontFamilyMono: FONT_MONO,
      fontSize: `${TYPE.BODY}px`,
      fontSizeSmall: `${TYPE.SMALL}px`,
      fontSizeMedium: `${TYPE.BODY}px`,
      fontSizeLarge: `${TYPE.SECTION}px`,
      fontSizeHuge: `${TYPE.DISPLAY}px`,

      // Radii: 12px cards, 8px controls. NaiveUI ships 3px for all of them.
      borderRadius: RADIUS.CONTROL,
      borderRadiusSmall: RADIUS.CONTROL,
      borderRadiusLarge: RADIUS.CARD,

      // Surfaces.
      bodyColor: p.BG,
      cardColor: p.CARD,
      modalColor: p.CARD,
      popoverColor: p.CARD,
      tableColor: p.CARD,
      baseColor: p.FIELD,
      inputColor: p.FIELD,
      inputColorDisabled: dark ? p.FIELD : p.TIP,
      borderColor: p.BORDER,
      dividerColor: p.BORDER,
      textColorBase: p.TXT,
      textColor1: p.TXT,
      textColor2: p.TXT,
      textColor3: p.MUT,
      textColorDisabled: p.GRAY,
      placeholderColor: p.MUT,
      placeholderColorDisabled: p.GRAY,
      iconColor: p.MUT,
      iconColorDisabled: p.GRAY,
      boxShadow1: SHADOW[mode],
      boxShadow2: SHADOW[mode],
      boxShadow3: SHADOW[mode],

      // Semantic colours. `primaryColor` is the one that would otherwise be
      // NaiveUI green; the rest keep the status palette of the Python build.
      primaryColor: p.ACC,
      primaryColorHover: p.ACCH,
      primaryColorPressed: p.ACCH,
      primaryColorSuppl: p.ACCH,
      successColor: p.RUN,
      successColorHover: p.RUN,
      successColorPressed: p.RUN,
      successColorSuppl: p.RUN,
      warningColor: p.ORG,
      warningColorHover: p.ORG,
      warningColorPressed: p.ORG,
      warningColorSuppl: p.ORG,
      errorColor: p.RED,
      errorColorHover: p.RED,
      errorColorPressed: p.RED,
      errorColorSuppl: p.RED,
      infoColor: p.ACC,
      infoColorHover: p.ACCH,
      infoColorPressed: p.ACCH,
      infoColorSuppl: p.ACCH,

      // Control heights on the 4px rhythm, tall enough for a 13px base.
      heightSmall: '28px',
      heightMedium: '32px',
      heightLarge: '38px',
    },
    Button: {
      borderRadiusSmall: RADIUS.CONTROL,
      borderRadiusMedium: RADIUS.CONTROL,
      borderRadiusLarge: RADIUS.CONTROL,
      fontSizeSmall: `${TYPE.SMALL}px`,
      fontSizeMedium: `${TYPE.BODY}px`,
      fontSizeLarge: `${TYPE.SECTION}px`,
      // Without these, a secondary button's hover is computed from the
      // default green and the whole control flashes the wrong hue.
      color2Hover: p.TIP,
      color2Pressed: p.TIP,
      color2Focus: p.TIP,
      textColor2Hover: p.ACC,
      textColor2Pressed: p.ACCH,
      textColor2Focus: p.ACC,
      border2Hover: `1px solid ${p.ACC}`,
      border2Pressed: `1px solid ${p.ACCH}`,
      border2Focus: `1px solid ${p.ACC}`,
      textColorGhostFocus: p.ACC,
      textColorGhostHover: p.ACC,
      textColorTextHover: p.ACC,
      textColorTextPressed: p.ACCH,
      textColorPrimary: '#ffffff',
      colorPrimary: p.ACC,
      colorHoverPrimary: p.ACCH,
      colorPressedPrimary: p.ACCH,
      colorFocusPrimary: p.ACCH,
    },
    Card: {
      borderRadius: RADIUS.CARD,
      borderColor: p.BORDER,
      color: p.CARD,
      titleFontSizeSmall: `${TYPE.SMALL}px`,
      titleFontSizeMedium: `${TYPE.SECTION}px`,
      titleFontSizeLarge: `${TYPE.DISPLAY}px`,
      titleFontWeight: '700',
      titleTextColor: p.TXT,
      fontSizeSmall: `${TYPE.SMALL}px`,
      fontSizeMedium: `${TYPE.BODY}px`,
      fontSizeLarge: `${TYPE.SECTION}px`,
      paddingSmall: '12px',
      paddingMedium: '14px 16px',
      paddingLarge: '18px 20px',
    },
    Input: {
      borderRadius: RADIUS.CONTROL,
      heightSmall: '28px',
      heightMedium: '32px',
      heightLarge: '38px',
      fontSizeSmall: `${TYPE.SMALL}px`,
      fontSizeMedium: `${TYPE.BODY}px`,
      fontSizeLarge: `${TYPE.SECTION}px`,
      borderHover: `1px solid ${p.ACC}`,
      borderFocus: `1px solid ${p.ACC}`,
      boxShadowFocus: `0 0 0 2px ${dark ? 'rgba(10, 132, 255, 0.28)' : 'rgba(10, 132, 255, 0.18)'}`,
    },
    Select: {
      borderRadius: RADIUS.CONTROL,
      heightSmall: '28px',
      heightMedium: '32px',
      heightLarge: '38px',
      fontSizeSmall: `${TYPE.SMALL}px`,
      fontSizeMedium: `${TYPE.BODY}px`,
      fontSizeLarge: `${TYPE.SECTION}px`,
      peers: {
        InternalSelection: {
          borderRadius: RADIUS.CONTROL,
          fontSizeSmall: `${TYPE.SMALL}px`,
          fontSizeMedium: `${TYPE.BODY}px`,
          fontSizeLarge: `${TYPE.SECTION}px`,
          heightSmall: '28px',
          heightMedium: '32px',
          heightLarge: '38px',
          textColor: p.TXT,
          color: p.FIELD,
          colorActive: p.FIELD,
          borderHover: `1px solid ${p.ACC}`,
          borderActive: `1px solid ${p.ACC}`,
          borderFocus: `1px solid ${p.ACC}`,
          boxShadowActive: `0 0 0 2px ${dark ? 'rgba(10, 132, 255, 0.28)' : 'rgba(10, 132, 255, 0.18)'}`,
          boxShadowFocus: `0 0 0 2px ${dark ? 'rgba(10, 132, 255, 0.28)' : 'rgba(10, 132, 255, 0.18)'}`,
        },
        InternalSelectMenu: {
          borderRadius: RADIUS.CARD,
          color: p.CARD,
          optionFontSizeSmall: `${TYPE.SMALL}px`,
          optionFontSizeMedium: `${TYPE.BODY}px`,
          optionFontSizeLarge: `${TYPE.SECTION}px`,
          optionTextColor: p.TXT,
          optionTextColorActive: p.ACC,
          optionColorActive: p.TIP,
          optionColorHover: p.TIP,
          optionTextColorHover: p.TXT,
        },
      },
    },
    Slider: {
      // The Python build's CTkSlider: a 6px track with a 16px knob, not
      // NaiveUI's hairline rail.
      railHeight: '6px',
      handleSize: '16px',
      railColor: p.GRAY,
      railColorHover: p.GRAY,
      fillColor: p.ACC,
      fillColorHover: p.ACCH,
      handleColor: '#ffffff',
      handleBoxShadow: `0 0 0 1px ${dark ? 'rgba(0, 0, 0, 0.4)' : 'rgba(0, 0, 0, 0.08)'}`,
      handleBoxShadowHover: `0 0 0 1px ${dark ? 'rgba(0, 0, 0, 0.4)' : 'rgba(0, 0, 0, 0.08)'}`,
      handleBoxShadowActive: `0 0 0 1px ${dark ? 'rgba(0, 0, 0, 0.4)' : 'rgba(0, 0, 0, 0.08)'}`,
      indicatorColor: p.TXT,
      indicatorTextColor: p.TXT,
      indicatorFontSize: `${TYPE.MONO}px`,
      fontSize: `${TYPE.BODY}px`,
      dotColor: p.GRAY,
      dotColorActive: p.ACC,
    },
    Checkbox: {
      borderRadius: '4px',
      fontSizeSmall: `${TYPE.SMALL}px`,
      fontSizeMedium: `${TYPE.BODY}px`,
      fontSizeLarge: `${TYPE.SECTION}px`,
      color: p.FIELD,
      colorChecked: p.ACC,
      borderChecked: `1px solid ${p.ACC}`,
      borderFocus: `1px solid ${p.ACC}`,
      boxShadowFocus: `0 0 0 2px ${dark ? 'rgba(10, 132, 255, 0.28)' : 'rgba(10, 132, 255, 0.18)'}`,
    },
    Switch: {
      borderRadius: '9px',
      railColor: p.GRAY,
      railColorActive: p.ACC,
      buttonColor: '#ffffff',
      buttonBoxShadow: `0 0 0 1px ${dark ? 'rgba(0, 0, 0, 0.4)' : 'rgba(0, 0, 0, 0.08)'}`,
    },
    Tooltip: {
      borderRadius: RADIUS.CONTROL,
      color: p.TIP,
      textColor: p.TXT,
      fontSize: `${TYPE.SMALL}px`,
      boxShadow: SHADOW[mode],
    },
    Popover: {
      borderRadius: RADIUS.CARD,
      color: p.CARD,
      textColor: p.TXT,
      fontSize: `${TYPE.BODY}px`,
      boxShadow: SHADOW[mode],
    },
    Modal: {
      borderRadius: RADIUS.CARD,
      color: p.CARD,
      textColor: p.TXT,
      titleFontSize: `${TYPE.SECTION}px`,
      titleFontWeight: '700',
      titleTextColor: p.TXT,
      contentFontSize: `${TYPE.BODY}px`,
      boxShadow: SHADOW[mode],
    },
    Dialog: {
      borderRadius: RADIUS.CARD,
      color: p.CARD,
      titleFontSize: `${TYPE.SECTION}px`,
      titleFontWeight: '700',
      titleTextColor: p.TXT,
      contentFontSize: `${TYPE.BODY}px`,
      contentTextColor: p.TXT,
      actionFontSize: `${TYPE.BODY}px`,
      iconColor: p.ORG,
      iconColorInfo: p.ACC,
      iconColorSuccess: p.RUN,
      iconColorWarning: p.ORG,
      iconColorError: p.RED,
      boxShadow: SHADOW[mode],
    },
    Collapse: {
      titleFontSize: `${TYPE.GROUP}px`,
      titleFontWeight: '700',
      titleTextColor: p.TXT,
      textColor: p.TIP,
      dividerColor: p.BORDER,
      arrowColor: p.MUT,
      arrowColorDisabled: p.GRAY,
      fontSize: `${TYPE.BODY}px`,
    },
    CollapseTransition: {},
    Tag: {
      borderRadius: '6px',
      fontSize: `${TYPE.MICRO}px`,
      color: p.TIP,
      textColor: p.MUT,
      colorChecked: p.ACC,
      textColorCheckable: p.TXT,
      textColorChecked: '#ffffff',
      border: `1px solid ${p.BORDER}`,
      borderChecked: `1px solid ${p.ACC}`,
    },
    Alert: {
      borderRadius: RADIUS.CONTROL,
      color: p.TIP,
      colorInfo: p.TIP,
      colorSuccess: p.TIP,
      colorWarning: p.TIP,
      colorError: p.TIP,
      titleFontSize: `${TYPE.BODY}px`,
      fontSize: `${TYPE.BODY}px`,
      titleFontWeight: '700',
      iconColorInfo: p.ACC,
      iconColorSuccess: p.RUN,
      iconColorWarning: p.ORG,
      iconColorError: p.RED,
      border: `1px solid ${p.BORDER}`,
      borderInfo: `1px solid ${p.ACC}`,
      borderSuccess: `1px solid ${p.RUN}`,
      borderWarning: `1px solid ${p.ORG}`,
      borderError: `1px solid ${p.RED}`,
    },
    Divider: { color: p.BORDER },
    Scrollbar: {
      color: `${p.GRAY}66`,
      colorHover: `${p.GRAY}aa`,
    },
    Empty: {
      fontSize: `${TYPE.BODY}px`,
      textColor: p.MUT,
      iconColor: p.GRAY,
    },
    Spin: { color: p.ACC, textColor: p.MUT, fontSize: `${TYPE.BODY}px` },
    Progress: {
      // A 4px pill on a 6px rail — on the rhythm, and visibly not NaiveUI's
      // inherited 3px. The rail matches the slider's so the two read alike.
      borderRadius: '4px',
      railHeight: '6px',
      railColor: p.BORDER,
      fillColor: p.ACC,
      fontSize: `${TYPE.MONO}px`,
      textColor: p.MUT,
    },
    Dropdown: {
      borderRadius: RADIUS.CARD,
      color: p.CARD,
      textColor: p.TXT,
      fontSize: `${TYPE.BODY}px`,
      optionColorActive: p.TIP,
      optionTextColorActive: p.ACC,
      optionColorHover: p.TIP,
      optionTextColorHover: p.TXT,
      boxShadow: SHADOW[mode],
    },
  }
}

/**
 * The custom properties every plain-DOM element reads. Kept in the same
 * module as the NaiveUI overrides so the two cannot disagree about what
 * "the border colour" is.
 */
export function cssVars(mode) {
  const p = PALETTES[mode] ?? LIGHT
  return {
    '--bg': p.BG,
    '--card': p.CARD,
    '--border': p.BORDER,
    '--field': p.FIELD,
    '--txt': p.TXT,
    '--mut': p.MUT,
    '--acc': p.ACC,
    '--acch': p.ACCH,
    '--red': p.RED,
    '--org': p.ORG,
    '--gray': p.GRAY,
    '--run': p.RUN,
    '--stop': p.STOP,
    '--tip': p.TIP,
    '--r-card': RADIUS.CARD,
    '--r-ctl': RADIUS.CONTROL,
    // Spacing on the 4px rhythm. `global.css` reads only these, never a
    // literal, so the rhythm cannot drift per component.
    '--sp-xs': `${SPACE.XS}px`,
    '--sp-sm': `${SPACE.SM}px`,
    '--sp-md': `${SPACE.MD}px`,
    '--sp-lg': `${SPACE.LG}px`,
    '--sp-xl': `${SPACE.XL}px`,
    '--f-display': `${TYPE.DISPLAY}px`,
    '--f-section': `${TYPE.SECTION}px`,
    '--f-group': `${TYPE.GROUP}px`,
    '--f-body': `${TYPE.BODY}px`,
    '--f-small': `${TYPE.SMALL}px`,
    '--f-micro': `${TYPE.MICRO}px`,
    '--f-mono': `${TYPE.MONO}px`,
    '--f-mono-sm': `${TYPE.MONO_SM}px`,
    '--font-ui': FONT_UI,
    '--font-mono': FONT_MONO,
    '--shadow': SHADOW[mode],
    '--m-hover-in': MOTION.HOVER_IN,
    '--m-hover-out': MOTION.HOVER_OUT,
    '--m-enter': MOTION.ENTER,
    '--m-ease-out': MOTION.EASE_OUT,
    '--m-ease-decay': MOTION.EASE_DECAY,
  }
}

/** `"system" | "light" | "dark"` → the appearance actually in effect. */
export function resolveMode(preference, systemIsDark) {
  if (preference === 'light' || preference === 'dark') return preference
  return systemIsDark ? 'dark' : 'light'
}

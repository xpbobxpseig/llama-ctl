# UI v3：暖石仪器（Warm Instrument）

> 状态：已落地（frontend）。
> 本文件取代 `docs/ui-redesign-v2.md`；v2 的暖灰 + 蓝色方案不再使用。
>
> 设计源头：Open Design 项目 `llama-ctl-console-v2`，产物
> `llama-cpp-console.html`，成功 run `35cf959a-00a8-4a31-b3c4-9e55f6de2d84`。
> 本轮采用它的视觉语言，并把它落到真实 Vue 组件、真实状态和 880px 最小窗口里。

## 1. 方向

不是换一套颜色，而是换一套「桌面仪器」的读法：

- **暖石纸 + 炭黑**：界面有纸的暖度，但没有米黄色的甜腻；深色模式是暖炭，而不是纯黑。
- **森林绿只负责交互**：slider、switch、checkbox、focus、链接、展开态用绿；提交按钮仍是墨色。
- **字号拉开三级**：28 状态 / 20 页标题 / 15 组标题 / 13 正文 / 12 辅助 / 11 仪器标签。
- **底部是一条仪器底座**：日志和提交条横跨整个窗口，首列与 280px 服务栏对齐。
- **一个图标系统**：16 单位网格、1.5px 描边、圆头圆角、currentColor，不再混用 11–15px 内联 SVG。

## 2. 色板

### Light

| Token | Hex | 用途 |
|---|---|---|
| `BG` | `#f6f3ee` | 画布 / 参数区 |
| `RAIL` | `#fbf9f4` | 顶栏、服务栏 |
| `CARD` | `#fcfaf6` | 输入条、日志头、提交条、对话框 |
| `FIELD` | `#f0ede6` | 输入框、选择器、chips |
| `BORDER` | `#ddd7cd` | 主分隔线 |
| `BORDER_STRONG` | `#c7c0b4` | 控件描边 / slider 轨道 |
| `BORDER_SOFT` | `#e8e3da` | 行分隔线 |
| `TXT` | `#1b1917` | 标题 / 主文本 |
| `TXT2` | `#5b564d` | 标签 / 正文 |
| `MUT` | `#6f6a61` | eyebrow / 辅助信息 |
| `ACC` | `#1f6b58` | 交互绿：slider、focus、链接、展开态 |
| `ACCH` | `#175244` | 交互绿 hover |
| `ACC_SOFT` | `#e4f1ec` | 选中 / hover 软底 |
| `PRIMARY` | `#1b1917` | 墨色提交按钮 |
| `PRIMARY_HOVER` | `#332f29` | 墨色 hover |
| `PRIMARY_ON` | `#fbf9f4` | 墨色上的文字 |
| `SWITCH` | `#1f6b58` | switch 开启 |
| `RUN` | `#2b7a4d` | RUNNING |
| `RUN_SOFT` | `#e4f2e8` | RUNNING 软底 |
| `ORG` | `#9a5f0f` | 警告 / dirty |
| `WARN_SOFT` | `#f8efe0` | 警告软底 |
| `RED` | `#b23a30` | 错误 / 停止 |
| `ERR_SOFT` | `#fbe9e6` | 错误软底 |
| `CODE` | `#f3f0ea` | 日志 / 代码井 |
| `HOVER` | `#f1ede6` | 行 hover |
| `ACTIVE` | `#e9e4dc` | pressed |
| `FOCUS` | `rgba(31,107,88,.20)` | focus 光晕 |

### Dark

| Token | Hex | 用途 |
|---|---|---|
| `BG` | `#171614` | 画布 |
| `RAIL` | `#1c1a17` | 顶栏、服务栏 |
| `CARD` | `#211f1b` | 卡片 / 日志头 / 提交条 |
| `FIELD` | `#272420` | 输入框 |
| `BORDER` | `#35312b` | 分隔线 |
| `BORDER_STRONG` | `#49433b` | 控件描边 |
| `BORDER_SOFT` | `#2b2823` | 行分隔线 |
| `TXT` | `#eae5dd` | 主文本 |
| `TXT2` | `#c0b9ae` | 标签 |
| `MUT` | `#a49e94` | 辅助 |
| `ACC` | `#6ec9a8` | 交互绿 |
| `ACCH` | `#8fdcc0` | hover |
| `ACC_SOFT` | `#1b2f28` | 软底 |
| `PRIMARY` | `#eae5dd` | 暖白提交按钮 |
| `PRIMARY_HOVER` | `#fbf9f4` | hover |
| `PRIMARY_ON` | `#171614` | 按钮文字 |
| `SWITCH` | `#2f8f73` | switch 开启 |
| `RUN` | `#5fd08d` | RUNNING |
| `RUN_SOFT` | `#183024` | 软底 |
| `ORG` | `#e0b062` | 警告 |
| `WARN_SOFT` | `#322817` | 软底 |
| `RED` | `#ed8076` | 错误 |
| `ERR_SOFT` | `#351d1a` | 软底 |
| `CODE` | `#131210` | 日志井 |
| `HOVER` | `#272420` | 行 hover |
| `ACTIVE` | `#2f2b26` | pressed |
| `FOCUS` | `rgba(110,201,168,.30)` | focus 光晕 |

**规则**：墨色只用于真正写服务的提交按钮；森林绿不画大面积背景；状态色只画状态点、dirty 徽标和错误文本。没有渐变，没有装饰性阴影；唯一 elevation 是对话框/浮层（`SHADOW_RAISED`）。

**对比度**（WCAG 2.1，对 `BG`）：Light TXT 15.84、TXT2 6.58、MUT 4.85、ACC 5.75、RUN 4.75、ORG 4.72、RED 5.36；Dark TXT 14.42、TXT2 9.29、MUT 6.80、ACC 9.11、RUN 9.38、ORG 9.09、RED 6.85。`smoke.mjs` 对每个模式做 ≥4.5 守卫。

## 3. 字体

全部为 Windows 本地字体（ADR-0001：无 `@font-face`、无远程请求）。

```css
--font-ui:      "Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI", "PingFang SC", system-ui, sans-serif;
--font-display: "Segoe UI Variable Display", "Segoe UI", "Microsoft YaHei UI", "PingFang SC", system-ui, sans-serif;
--font-mono:    "Cascadia Mono", Consolas, "SFMono-Regular", "DejaVu Sans Mono", monospace;
```

`FONT_DISPLAY` 只用于 20px 及以上的标题；正文继续使用 Text optical size。

| Token | px | 字重 | 行高 | 用途 |
|---|---:|---:|---:|---|
| `DISPLAY` | 28 | 600 | 1.15 | 服务状态 `RUNNING`、设置页标题 |
| `SECTION` | 20 | 600 | 1.30 | 页/参数标题、对话框标题 |
| `GROUP` | 15 | 600 | 1.40 | 参数组标题 |
| `BODY` | 13 | 400/500 | 1.55 | 标签、输入、按钮 |
| `SMALL` | 12 | 400 | 1.50 | 说明、日志头路径 |
| `MICRO` | 11 | 500 | 1.45 | eyebrow、计数、事实标签 |
| `MONO` | 13 | 400 | 1.50 | 数值 readout |
| `MONO_SM` | 12 | 400 | 1.65 | 日志行 |

`.t-mono` 固定 `font-variant-numeric: tabular-nums; line-height: 1.5;`。`.readout` 自己不设 `font-size`，完全继承 `t-mono`，所以数值与标签同基线。eyebrow 为 11px、字距 `.10em`、大写、`MUT`；结构性英文标签（`SERVICE`、`CONFIGURATION`、`SESSION LOG`、`SETTINGS · NSSM`）使用它，业务文案仍走 Rust/`shell-copy.js`。

## 4. 图标

新增 `frontend/src/components/Icon.vue`：

- **16 × 16 用户网格**，线宽 `1.5`（可覆写），`stroke-linecap/linejoin: round`。
- `fill: none`、`stroke: currentColor`，不依赖字体、不随字号漂移。
- 实际尺寸 14–16px；不混用 11/13/15px 的旧内联 SVG。
- 图标表：`settings / refresh / play / stop / restart / search / chevron-right / terminal / help / close / arrow-up-right / check / info / download / folder / sliders`。
- 应用标记是一个 16 单位网格上的自定义 lambda（`brand mark`），不是字体字母；`StatusDot` 仍是专门的 12px 双圆 SVG（运行呼吸 / 非运行静止）。

顶栏、服务栏、参数组、帮助「?」、日志折叠箭头、设置关闭都用这套图标。

## 5. 间距与布局

**间距阶梯**：`4 / 8 / 12 / 16 / 20 / 24 / 32`（`--sp-xs` … `--sp-xxxl`）。组件只读 token，不写新的节奏。

**固定尺寸**：

| 部件 | 尺寸 |
|---|---|
| 顶栏 | 56px；品牌列 = 服务栏宽度 |
| 服务栏 | 280px（>980）；260px（≤980） |
| 参数工具栏 | sticky；上下 12px / 左右 20px |
| 参数组头 | 48px |
| 参数行 | 48px；三轨 `18 / minmax(188,0.9fr) / 1.35fr` |
| 文本输入 / 选择器 | 32px |
| Slider | 4px 轨道 + 16px 手柄 |
| 日志头（收起） | 40px + 1px 上边框 |
| 日志体（展开） | 最大 180px；12px/1.65 mono |
| 提交条 | 56px + 1px 上边框 |
| 面板 / 控件 / chip 圆角 | 12 / 8 / 6px |
| 唯一阴影 | `SHADOW_RAISED`，仅对话框/浮层 |

**构图**：窗口 = 56px 顶栏 + 上部 `280px | 1fr` 双栏 + 全宽日志 + 全宽提交条。

- 上部：服务栏、参数滚动区各自滚动；顶栏品牌列、服务栏、提交条首列使用同一个 280/260px 基准。
- 日志和提交条不属于右栏：它们横跨窗口，提交条左边是「参数预设」输入，左边缘与 rail 对齐。
- 980px 是唯一布局断点：280 → 260，顶栏品牌列/服务栏/提交条首列一起变；不会出现三列各自为政。
- 参数行在窄窗口改为 `18 | 160 | 1.4fr`，但控件仍为 32px，不把输入压成一条缝。
- 日志收起时 `.fold` 使用 `0fr` 并去掉纵向 padding；实测高度 41px（40 + 1px border），不是 65px 的空白条。

## 6. 组件规范

### 顶栏

- 56px 高、`RAIL` 背景、1px 底边；三列：品牌 280 | 服务选择 1fr | 状态/动作 auto。
- 品牌：28px 墨色 lambda 方块 + 15px/600 标题 + 10px mono `NSSM · WINDOWS`。
- 服务选择：32px 高，196px 宽；值 13px/550；hover 出 `FIELD` 与 hairline，focus 用 `ACC`。
- 状态 tag：26px 高、11px mono、6px 圆点；RUNNING 用 run-soft，STOPPED/UNKNOWN 用 field，transition 用 warn。
- 设置按钮：32px ghost，图标 + 文本；当前页用 FIELD 背景。

### 服务栏

- 状态 eyebrow + NSSM chip；状态 28px display；detail 12px mono。
- 三个服务动作：32px 高、等宽三列；Stop 红字 + `ERR_SOFT` hover；重启仍二次确认。
- 自启：开关 + 右侧模式值；逻辑仍受 Snapshot 控制。
- facts 为纵向 label/value；label 11px eyebrow，value 12px mono。
- 启动参数 `<details>` 用 13px chevron；底部更新块 `margin-top:auto` 固定到栏底。

### 参数区

- 工具栏 sticky；eyebrow `CONFIGURATION` + 20px 标题 + 28 chip；搜索 210px（窄 190px）+ `Ctrl K` cue + 全部展开。
- 组头：48px、chevron 14px、15px 标题、右侧 `01` 计数和 hairline leader；展开时 chevron/计数变 `ACC`。
- 行：13px 名称 + 10.5px mono flag 纵向排列；? 为 18px 圆；hover 整行 `HOVER`。
- Slider：森林绿填充、16px 白心手柄；readout 无边框、右对齐、mono 13；out-of-range 用 warn-soft。
- Select：32px、220px 上限；路径行输入 + 绿色「浏览」；checkbox 选中为森林绿，标签不换行。
- 帮助 popover：卡片 12px 圆角、360px 宽、11px eyebrow + 13px 正文 + 选项值 mono。

### 日志 / 提交

- 日志头：40px、`CARD`、terminal 图标、`SESSION LOG`（≤980 隐藏）、Rust 标题、行数 chip、路径、chevron。
- 日志体：`CODE` 井、12px/1.65 mono、最新行 `TXT`，其余 `TXT2`；最大 180px，内部滚动。
- 提交条：56px 高，`CARD`；首列 280/260px 放「参数预设」+ 输入；中列保存/删除/已载入；右列 dirty tag + 还原 + 墨色应用。
- Apply 仍先打开新旧对比对话框；预设删除、服务切换、开机自启的确认路径未变。
- 所有日志、预设、工具栏的 `data-*` 钩子保留。

### 对话框 / 设置

- 对话框：12px 圆角、20px display 标题、13px 正文、32px 操作按钮、`SHADOW_RAISED`；遮罩关闭仍等于取消。
- 设置页：max-width 820、32px 外边距；28px 页标题、15px 分区、64px 字段行；右侧控件 220px，窄窗口 200px。
- 设置页整体滚动；更新区沿用同一分区节奏，更新日志/进度使用 `CODE` 井。

## 7. 改动的文件

| 文件 | 改动 |
|---|---|
| `frontend/index.html` | favicon 改为墨色 lambda 标记（data URI，无远程资源） |
| `frontend/src/theme/index.js` | 新双主题色板；TYPE 28/20/15/13/12/11；FONT_DISPLAY；SPACE 7 阶；NaiveUI 全量 overrides（slider/switch/checkbox/select/input/dialog…） |
| `frontend/src/styles/global.css` | 新 type scale、eyebrow、kbd、focus、滚动条、NaiveUI 结构样式 |
| `frontend/src/components/Icon.vue` | **新增**统一图标组件 |
| `frontend/src/components/AppShell.vue` | 56px 三列顶栏、lambda 品牌、状态 tag、对齐 280/260 基准 |
| `frontend/src/views/ConsoleView.vue` | 上部双栏 + 全宽日志/提交条 |
| `frontend/src/components/StatusCard.vue` | 28px 状态、32px 控件、纵向 facts、Icon chevron |
| `frontend/src/components/ServiceBar.vue` | 32px 服务选择、图标化刷新、窄屏收缩 |
| `frontend/src/components/ServiceControls.vue` | 32px 按钮、Icon 图标、自动启动行 |
| `frontend/src/components/ParamForm.vue` | 20px 标题、CONFIGURATION eyebrow、210px 搜索、Ctrl K cue、新间距 |
| `frontend/src/components/ParamGroup.vue` | 48px 组头、15px 标题、leader + 计数、Icon chevron |
| `frontend/src/components/ParamRow.vue` | 48px 行、三轨对齐、13px 名称 + 10.5px flag 纵向 |
| `frontend/src/components/ParamSlider.vue` | 无边框 readout、绿色 slider、16px 手柄 |
| `frontend/src/components/ParamCombo.vue` / `ParamCheck.vue` / `ParamPath.vue` | 32px 控件、绿色浏览/勾选、标签不换行 |
| `frontend/src/components/ParamHelp.vue` | Icon 帮助按钮 |
| `frontend/src/components/LogTail.vue` | 40px 日志头、全宽日志井、0fr 折叠修复、Icon |
| `frontend/src/components/PresetBar.vue` | 全宽提交条、280/260 首列、32px Apply、28px ghost 操作 |
| `frontend/src/views/SettingsView.vue` | 28px 标题、15px 分区、64px 字段行、Icon 关闭 |
| `frontend/src/components/UpdateSection.vue` / `UpdateProgress.vue` / `ReleaseNotes.vue` | 尺寸、代码井、按钮和遮罩视觉统一 |
| `frontend/src/components/ConfirmDialog.vue` / `GuardDialog.vue` | 32px 按钮，交给 Dialog override |
| `frontend/src/App.vue` | 设置按钮 Icon + 32px 视觉 |
| `frontend/smoke.mjs` | 设计断言更新为 28/20/15/13/12/11 与森林绿 token；对比度守卫保留 |
| `docs/ui-redesign-v3.md` | 本文件 |

## 8. 验收

- `cd frontend && npm run build`：exit 0。
- `cd frontend && npm run smoke`：ticket 12–17 全部通过；无 runtime/Vue warning；28 字段 / 7 组。
- Playwright 实机（Chromium，`deviceScaleFactor: 1`）：
  - 1000×860、880×720 × 浅/深共四组：`scrollWidth - innerWidth = 0`。
  - 顶栏 56；品牌列 = 服务栏 = 280 / 260；提交条 56 + 1px border。
  - 组头 48、参数行 48、搜索/选择器 32、slider 手柄 16。
  - 字号实测 28 / 20 / 15 / 13 / 11。
  - 28 个字段的 name/flag/check-label 均无 `scrollWidth`/`scrollHeight` 溢出。
  - `Ctrl+K` 聚焦搜索；输入 `ctx` 得到 1 / 28；Esc 清空。
  - 设置页可滚动（1000：804/929；880：664/913），无横向溢出。
  - 日志展开后 body 实测 126px（max 180）；收起后 41px（40 + 1px border）。
  - 重启确认框：`二次确认`、标题 20px、圆角 12px、两个 32px 按钮；取消不执行。
  - 控制台无 error/warning。

> 截图只存在于会话 scratch，不进入仓库。

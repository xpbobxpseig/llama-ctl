# 12: Vue 骨架与 NaiveUI 主题 override

**What to build:** 搭起 Vue 3 前端骨架：路由/页面结构、NaiveUI 接入、以及**完全自定义的主题 override**。用户视角：新界面看起来就是现在这个工具，只是跑在 Web 上——圆角、配色、字阶都不变。

NaiveUI 的取舍是「只要组件，不要视觉」：用它的 slider / select / modal / popover 省掉自绘组件，但主题 token 全部按现有设计语言覆写。依据见 `docs/design/naiveui-vs-current.html` 的对照——NaiveUI 默认是 3px 圆角 + 绿色主色 + 14px 字阶，与现有 Apple 风不是一回事。

**Blocked by:** 09, 11

**Status:** ready-for-agent

- [ ] Vue 3 + NaiveUI 接入，浅/深双主题
- [ ] 主题 override 复刻现有 token：圆角 12px（卡片）/ 8px（控件）
- [ ] 主色 `#0a84ff`；状态色沿用（运行 `#30d158`、警告 `#ff9500`、错误 `#ff3b30`）
- [ ] 字阶六级严格递减：18 / 15 / 13 / 13 / 12 / 11
- [ ] 字体：界面用微软雅黑 UI，数值与日志用 Cascadia Mono（回退 Consolas）
- [ ] 主题切换（跟随系统 / 浅色 / 深色）生效且偏好持久化
- [ ] 窗口几何在重启后恢复
- [ ] 无 CDN、无运行时远程加载（ADR-0001）
- [ ] 视觉验收：与 `docs/design/naiveui-vs-current.html` 左面板对照，token 逐项一致

## Resolution

### 布局

占位前端（`index.html` / `main.js` / `styles.css`）已换成 Vite + Vue 3 + NaiveUI：

| 路径 | 角色 |
|---|---|
| `frontend/index.html` | 窗口外壳；data: URI 图标，无外链 |
| `frontend/vite.config.js` | `base: './'`（相对路径，file:// 下可用）；端口与 `devUrl` 同源 |
| `frontend/src/theme/index.js` | **唯一主题源**：调色板 / 字阶 / 圆角 / 间距 / 动效 + NaiveUI override |
| `frontend/src/api/ipc.js` | 16 个 command + 信封unwrap + 进度订阅 |
| `frontend/src/api/fixture.js` | 演示数据（**标注为 demo**，仅 shell 外使用） |
| `frontend/src/api/shell-copy.js` | Rust 表暂缺的 10 条骨架文案 |
| `frontend/src/stores/snapshot.js` | Snapshot 缓存；`form` 是前端唯一持有的状态 |
| `frontend/src/stores/theme.js` | 外观 / 动效 / 语言，全部经 `save_settings` |
| `frontend/src/window/geometry.js` | `WxH+X+Y` 解析、恢复、防抖写回 |
| `frontend/src/styles/global.css` | 纯 DOM 那一半：字阶类、焦点环、入场、reduced-motion |
| `frontend/src/components/AppShell.vue` | 窗口框架 + 顶栏 service slot + 内容 slot |
| `frontend/src/views/{Console,Settings}View.vue` | 两个视图；13/15 填 slot |
| `frontend/smoke.mjs` + `smoke.entry.js` | 冒烟：构建真实 bundle 在 jsdom 跑，断言 token 与单向规则 |

### 主题 override 怎么落的

`src/theme/index.js` 导出 `naiveOverrides(mode)`（`GlobalThemeOverrides`）和 `cssVars(mode)`（自定义属性），
`App.vue` 把它们分别喂给 `n-config-provider` 的 `theme-overrides` 与 `style`。同一个模块导出两者，
所以「边框色是什么」不可能有两份答案。

关键点：
- `common.fontSize = 13px` —— 这是把 NaiveUI 的 14px 世界整体换成本项目字阶的那一处。
- `common.borderRadius = 8px` / `borderRadiusLarge = 12px` —— 控件 8、卡片 12。
- `common.primaryColor = #0a84ff` 之外，`Button.color2Hover` 等**派生**色也逐个钉死：NaiveUI 的次级按钮 hover
  是从默认绿算出来的，不钉就会闪回绿色。
- `Slider` 改成 6px 轨道 + 16px 圆柄（对应 CTkSlider），不是 NaiveUI 的细轨。
- 字体：`fontFamily` / `fontFamilyMono` 直接替换 NaiveUI 自带的 `v-sans` / `v-mono`。

token 取值逐项对照 `llama_ctl_gui.py` L425-442（调色板）、L494-504（字阶），
并与 `docs/design/naiveui-vs-current.html` 左面板交叉核对。字阶严格递减 18/15/13/13/12/11，
13 由组头与正文共用、靠**字重**区分层级（Tk 只有 normal|bold，这也是原设计的选择）。

### 主题切换与持久化

`system` / `light` / `dark` 三态；`system` 由 `matchMedia` 跟随 OS（有 change 监听）。
切换走 `save_settings`，**以 Rust 回读的新 Snapshot 为准**——不是前端假定写成功了。
语言切换同理，回来的是新文案表，所以界面不需要自己持有一份翻译（ADR-0005）。

### 窗口几何

`settings.geometry` 是 `"WxH+X+Y"`，与 Python 版 `self.geometry()` 写出的形状一致，
所以**旧版保存的窗口位置新版能恢复**。写回防抖 400ms（拖动每帧一次 resize，写文件会写坏），
且只有真的变了才发 IPC。

### 验证

- `npm run build`：2683 modules，2.1s，产物 `dist/{index.html,assets/*.js,assets/*.css}`。
- `npm run smoke`：真实 client bundle 在 jsdom 挂载，7 项断言全绿（挂载渲染 / 字阶 / 圆角主色状态色字体 /
  双调色板同构 / 几何往返 / 单向规则 / 无 console 报错）。
- `cargo build`：通过（改了 `frontendDist` 后 `tauri-build` 能解析配置）。
- 无外链：`dist/` 全量 `https?://` 扫描只剩 4 类**不可达**字面量——
  `www.w3.org/2000/svg`（SVG 命名空间，12 处）、`1998/Math/MathML`、`1999/xlink`、
  以及 Vue 运行时错误消息里的 `vuejs.org/error-reference/#runtime-${...}`。
  全是 XML 命名空间与字符串常量，**不发起任何请求**；`url()` 零处，无 `@font-face`、无 `@import`。

### 需要人看的

- **窗口没真机打开过**（本环境无交互桌面会话），与票 11 同一遗留项。构建通过 ≠ 窗口能开。
- **改了 `src-tauri/tauri.conf.json`**（这是允许的例外）：`frontendDist` 由 `../frontend` 改为 `../frontend/dist`，
  并补 `devUrl` / `beforeDevCommand` / `beforeBuildCommand`——占位前端是源码直出，Vite 项目必须吃构建产物。
  注意 tauri 的配置解析器不接受注释，注释写在了这里而不是文件里。
- **几何恢复还差三个 capability 权限**（未改 `capabilities/`，Rust 侧已封版）：
  `core:window:allow-set-size`、`core:window:allow-set-position`、`core:window:allow-close-requested`。
  *写回*已完全可用（`core:window:default` 已含 `scale-factor`/`inner-size`/`outer-position`）；
  *恢复*会被 IPC 拒绝 → 退化为按配置尺寸打开，不崩。补权限后即生效。
- **10 条骨架文案暂留在前端** `src/api/shell-copy.js`（`settings.appear`、`settings.motion`、
  `settings.note`、`appear.*`、`mb.error`、`shell.*`）。已逐 key 核对 `core/src/i18n.rs` 与
  `commands/src/copy.rs` 确实没有；搬进 Rust 是逐条搬一行、然后删这里。
- 字体依赖系统自带（微软雅黑 UI / Cascadia Mono，回退 Consolas）——ADR-0001 不允许远程字体，
  所以非中文 Windows 上会回退到 `system-ui`，这是有意的取舍。

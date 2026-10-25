# UI v2：从「设置面板」到「服务仪器」

> **已被 `docs/ui-redesign-v3.md` 取代。** v3 使用暖石 + 炭黑 + 森林绿、
> 28/20/15/13/12/11 字号层级和全宽仪器底座；本文件的蓝色交互方案不再生效。
>
> 状态：历史记录（frontend v2）。本文记录 v2 的设计依据、交互变化与验收口径。
> 旧方案 `docs/ui-redesign-proposal.md` 描述的是 CustomTkinter 时代；v2 取代它，v3 再取代 v2。

## 一、目标

当前重构后的界面仍然像「把一组卡片纵向堆起来」：状态、参数、预设、日志彼此平级，
主操作不突出，窄窗口下标签和按钮开始互相挤压。这次不再修补旧稿，而是重新定义：

- **一个窗口，三层信息**：服务状态在左，参数编辑在中，日志/提交在底部。
- **墨色提交，蓝色交互，三色状态**：任何时刻只有一个实心主按钮。
- **发丝层级**：靠边框、留白、字重和灰阶分层，不用卡片阴影堆出层次。
- **窄窗口优先**：880×720 是底线；标签、控件、按钮在该宽度下不换行、不溢出。

参考方向：当前一代开发者工具（OpenAI Codex、Linear）的暖中性、紧凑排印、
等宽数字与克制的状态色；不复制任何具体产品的布局或品牌资产。
本机 Open Design MCP 的第二轮原型（`llama-cpp-console.html`）给出了同向的参考：
暖中性、左服务栏、底部日志/提交条、唯一实心主按钮。落地时保留更紧凑的 13px
桌面密度与「墨色提交 + 蓝色交互」配色，并采纳了它的顶栏状态 pill 与 Ctrl/⌘+K 搜索。

## 二、布局

```
┌────────────────────────────────────────────────────────────┐
│ 顶栏 52px：品牌 · 服务选择 · RUNNING pill · 演示 · 设置    │
├──────────────┬─────────────────────────────────────────────┤
│ 服务栏 300px │ 参数工作区                                  │
│              │  ┌ 吸顶工具条：标题 / 数量 / 搜索 / 展开全部 │
│ 状态 + 控制  │  ├ 7 个可折叠分组（前两组默认展开）          │
│ 事实 + 参数  │  ├ 日志抽屉（默认折叠，展开 ≤220px）        │
│ 更新摘要     │  └ 吸底提交条：预设 / 未应用 / 还原 / 应用   │
└──────────────┴─────────────────────────────────────────────┘
```

- 参数区是**唯一滚动容器**；服务状态和提交动作不随表单滚走。
- 日志抽屉在参数区和提交条之间，折叠时只占 38px；展开不改变窗口结构，只压缩参数区。
- 设置页是独立的全宽页面：标题 + 分组 + 发丝行，不再使用嵌套卡片。
- 在 <980px 时服务栏收窄到 268px；880px 下无横向滚动。

## 三、关键交互变化

| 变化 | 原因 |
|---|---|
| 参数搜索（按中文名、英文名、flag 过滤） | 7 组 28 项时，滚动找参数是最大摩擦；搜索命中时自动展开全部，清空后恢复原展开状态 |
| 标签拆成「名称 + 等宽 flag」 | `模型文件 (-m/--model)` 这类长标签不再折成两行；flag 可复制、可搜索，视觉权重降低 |
| 组头显示 `03/04` 计数 | 让「这组有多少项」可扫读，不靠展开试 |
| 未应用更改只在提交条出现 | 由 Rust 的 `facts.dirty` 驱动；本地编辑不会误亮 |
| 提交条左侧预设、右侧动作 | 预设与提交是两个语义组；窄窗口时动作组整体换行右对齐，不会出现「应用更改单独掉到左边」 |
| 日志标题只保留 `日志尾随 server.err` | 折叠/展开由 chevron 和 `aria-expanded` 表达，长括号文案不再挤掉路径 |
| 顶栏 RUNNING pill | 状态在服务选择旁可一眼确认；rail 仍保留完整状态与探活 |
| 服务栏底部显示更新摘要 | 启动检查的结果在主界面可见；「设置 →」直达更新区 |
| 停止按钮红字、重启/应用确认按钮墨色 | 危险动作靠文字和橙色提示图标表达；唯一实心主按钮仍是「应用更改」 |
| 对话框确认统一为墨色 | 与提交动作同一层级；橙色只留在提示图标和状态里 |
| Ctrl/⌘+K 聚焦参数搜索 | 搜索是唯一的全局筛选；快捷键不引入命令面板或第二套焦点模型 |

## 四、令牌

### 浅色

| Token | 值 | 用途 |
|---|---|---|
| `bg` | `#f5f4ef` | 画布 |
| `rail` | `#f0efe9` | 服务栏 |
| `card` | `#ffffff` | 提交条 / 浮层 |
| `field` | `#f4f3ee` | 输入、读数 chip |
| `border` / `border-soft` | `#e4e2da` / `#edebe5` | 发丝分隔 |
| `ink` / `ink-2` / `muted` | `#16150f` / `#4f4e48` / `#6d6b63` | 三级文字 |
| `primary` / `primary-on` | `#17160f` / `#fbfaf6` | 提交按钮 |
| `accent` | `#2f5fd0` | 焦点、链接、展开态 |
| `run` / `warn` / `err` | `#1c7a4c` / `#955f0f` / `#bb3e34` | 状态 |

### 深色

`bg #0c0c0b` · `rail #111110` · `card #161615` · `field #1d1d1b` ·
`border #2a2a27` · `ink #f3f1eb` · `muted #8d8a81` · `primary #f3f1eb` ·
`accent #93b2ff` · `run #5fd08d` · `warn #e3ad58` · `err #f07d72`。

所有正文/状态色在画布上的对比度 ≥ 4.5:1；`smoke.mjs` 里有逐 token 的
WCAG 检查，改色会直接失败。

### 排印与几何

- 字号：18 / 15 / 13 / 13 / 12 / 11（GROUP 与 BODY 同为 13，靠字重区分）。
- 字体：`Segoe UI Variable Text` → `Microsoft YaHei UI` → system；
  数字/flag/日志：`Cascadia Mono` → `Consolas`。全部本地，无 `@font-face`。
- 圆角：面板 12、控件 8、chip 6、状态 pill 999。
- 间距：4 / 8 / 12 / 16 / 24 / 32；所有 gap 都取这六级。
- 动效：120ms 进、600ms 衰减、200ms 入场；`?` 仍是 300/200/800ms，
  300ms 阈值不受动效开关影响。

## 五、保留的约束

- **Rust 是唯一真源**：dirty、apply 的 written、更新检查、预设写入都没有在
  前端重算；所有必填的二次确认、取消即不写入、自动备份语义原样保留。
- **测试钩子**：`[data-group]`、`[data-field]`、`[data-action]`、
  `[data-preset-bar]`、`[data-dirty-hint]`、`[data-log-open]`、
  `[data-update-*]`、`header .actions`、`.status svg.dot` 等保持不变。
- **无新依赖**：没有图标库、CSS 框架、字体或远程资源。
- **无障碍**：焦点环、`aria-expanded`、`aria-live`、`aria-label`、
  `role=log`、`role=switch` 语义保留；动效关闭只把时长归零，不隐藏任何控件。

## 六、验证

| 检查 | 结果 |
|---|---|
| `npm run build` | exit 0 |
| `npm run smoke` | 全部 ticket 12–17 检查通过（含 28 字段、双主题、应用/预设/更新、动效） |
| 1000×860 浅色/深色 | 无横向滚动；标签不换行；提交条单行 |
| 880×720 浅色/设置 | 无横向滚动；服务栏 268px；控件可达 |
| 展开日志 / 高级组 | 滚动容器正确裁切，日志抽屉不覆盖提交条 |
| 重启 / 应用确认框 | 墨色确认按钮；橙色提示图标；取消不写入 |

## 七、涉及文件

- `frontend/src/theme/index.js`（令牌 + NaiveUI overrides + Card）
- `frontend/src/styles/global.css`
- `frontend/src/App.vue`、`components/AppShell.vue`
- `frontend/src/views/ConsoleView.vue`、`views/SettingsView.vue`
- `components/ServiceBar.vue`、`StatusCard.vue`、`ServiceControls.vue`
- `components/ParamForm.vue`、`ParamGroup.vue`、`ParamRow.vue`、`ParamSlider.vue`、
  `ParamCombo.vue`、`ParamCheck.vue`、`ParamPath.vue`、`ParamHelp.vue`
- `components/LogTail.vue`、`PresetBar.vue`、`UpdateSection.vue`、
  `ConfirmDialog.vue`、`GuardDialog.vue`、`ReleaseNotes.vue`
- 新增 `components/RailUpdate.vue`
- `frontend/smoke.mjs`：设计断言更新为 v2 令牌，并新增 WCAG 对比度守卫
- `frontend/src/api/shell-copy.js`：新增 rail / 搜索 / 日志清空等前端回退文案


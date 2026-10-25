# v6 · 精密仪器（现行实现）

日期：2026-10-24 · 实现：`frontend/src/design/design.css`（v5 结构与 DOM 钩子不变，视觉层整体替换）

## 为什么换掉 v5

v5（衬线字 + 渐变壁纸 + 玻璃模糊 + 噪点 + 全灰无强调色）是典型的
「AI 生成静奢风」：字体不是桌面工具该有的脸，壁纸让文本浮在不确定的底
上，没有交互色导致一切可点与不可点长一个样。用户反馈「AI 味太重」。

## v6 的四条系统规则

1. **墨色提交，森林绿交互。** 写服务的按钮用 `--primary`（浅色近黑 / 深色暖白）；
   `--acc`（#1f6b58 / #6ec9a8）只属于焦点环、导航选中条、开关、链接、「已改」
   圆点与「已载入」标记，永远不出第二个主按钮。
2. **状态色不做装饰。** run / warn / err 只画状态点、告警行、错误行与破坏性悬停。
3. **深度是发丝线。** 面板靠 1px 边框与面差分层（rail #fbf9f4 / 画布 #f6f3ee / 卡面
   #fcfaf6；深色同构反转）。投影只给浮层：弹窗、菜单、动作条。
4. **动效说令牌。** 一切入场读 `--m-enter`，一切驻留读 `--m-hover-in`，衰减读
   `--m-hover-out`；动效开关（motion/index.js）把时长归零，功能一项不少。

## 要点

- **字体**：Segoe UI Variable（Display 光学尺寸只给 ≥15px 标题）+ Microsoft
  YaHei UI（中文）+ 随包 Cascadia Code 子集（数值/路径/日志，`llama-mono`）。
  v5 的 Noto Serif SC 子集（223 KB）已删除，不再随包。
- **颜色令牌用 `@property` 注册**（`<color>` / `inherits: true`）。不注册的话，
  WebView2 里依赖 `var()` 的过渡属性在主题切换后可能滞留旧主题颜色；注册后
  令牌变化正确触发重算与过渡。
- **`color-scheme: light / dark`** 随 data-theme 切换：原生 select 弹层、滚动条、
  输入光标跟随主题。
- **图标**：全部内联 SVG（1.5px 描边、圆端点、统一 20 viewBox），v5 的文字符号
  （⋯ ✕ ⤢ − +）已清除。
- **入场动效**：视图切换 `d5-view-in`（200ms 上浮淡入）、弹层 `d5-pop`（缩放
  0.97→1）、动作条 `d5-rise`（上浮 8px）、菜单 140ms。全部受动效总开关约束。
- **对比度**：文字角色沿用 `src/theme/index.js` 的 AA 校验值（该文件仍是令牌
  的权威来源，design.css 与其同值）。

## 截图

`docs/ui-redesign/v6-{dark,light}-params.png`、`v6-light-settings.png`、
`v6-dark-apply-dialog.png`。

## 第二轮修订（同日，用户实测反馈）

- **按钮整体缩一号并文字居中**：圆形主操作与幽灵钮 34→30，文字钮 28→26，
  主按钮 30→28，图标钮 28→26，步进 20→18，分段筛选 30→28；文字类按钮统一
  `inline-flex` 居中。
- **分组标题层级修正**：11px 眉标比 13px 行名小是层级倒挂——改为与正文同号
  （13px）但 700 字重 + 0.10em 字距 + text2 色，层级靠字重与字距立起来。
- **侧栏纵向间距**：导航项之间 3px、标题下 18px、底部组与工具区各 +10/+12px，
  侧栏内边距 24/12/16。
- **云母材质**：`tauri.conf.json` 开 `transparent` + `windowEffects: ["mica",
  "acrylic"]`（Win11 Mica，Win10 回退 acrylic）；`.d5.mica`（仅 Tauri 壳内加）
  把侧栏/主区换成半透明染色层（侧栏 0.50/0.55 透得最多，主区 0.82/0.84 保
  正文对比度），`html.mica-host` 透出 body 底。浏览器演示无此材质，保持不透明。
- **深色下拉弹层可读**：`<html>` 的 `color-scheme` 随主题由 JS 同步（原生弹层
  跟根元素走），并显式给 `option` 上 `--card` 底 + `--text` 字，双保险。

## 第三轮修订（同日，用户实测反馈）

- **自绘下拉（Dd.vue）替换原生 select**：原生弹出层的圆角 / 间距 / 悬停 / 勾选
  都不可控，是「丑」的根源。新组件 = 触发钮（`.selbtn`，行内值胶囊；`bare` 变体
  嵌在维护页「当前」行正文里）+ 弹出层（`.dd-pop`：卡面 + 发丝线 + 12px 圆角 +
  分层投影 + 140ms 入场，30px 选项行、悬停高亮、选中项打交互绿勾、超 320px 滚动）。
  键盘可达：↑↓ 移动、Enter/Space 确认、Esc 关闭、Home/End 跳端；同一时间只开一个；
  点外部 / 滚轮收起。选项 `title` 保留 Rust 参数详解。参数页 10 个枚举、设置页
  语言/外观、维护页构建渠道全部换用。
- **启停按钮图形加大**：viewBox 20 里方形从 8×8 加到 9.2×9.2、三角从 8 宽加到
  9.2 宽（渲染约 46% 覆盖），图标统一 16px（导航 / 圆钮 / 幽灵钮），列表图标 15px。
- **数值居中**：`.n`（值 + 单位）与编辑态 `.inline` 从右对齐改居中；分段筛选按钮
  也统一 inline-flex 居中。

## 第四轮修订（同日，用户实测反馈：字体规则重梳理 + 字体接口）

**字级规则**（写入 design.css 头注释，全应用只允许这些尺寸 / 字重）：

| 级 | 角色 | 规格 |
|---|---|---|
| L1 | 服务名 / 弹窗标题 | 16 与 15 / 600 / display |
| L2 | 分组标题 `.section` | **14 / 600 / display / 全文字色** |
| L3 | 行主名 / 按钮 / 选项 / 导航 | 13 / 500 |
| L4 | 数据值（mono tabular） | 13 / 400 |
| L5 | 辅助（lsub / 状态条 / 日志） | 12 / 400 |
| L6 | 眉标（侧栏标题 / 时间戳 / 计数） | 11 / 500 mono |

二级在尺寸、字重、色深三个维度都不低于三级；权重只有 400/500/600 三档
（废掉 700 与 450）；等宽字只给数据不画标题。本轮具体改动：`.section`
从 13px mono 700 灰 → 14px sans 600 全文字色；`.lname` 14/600 → 13/500；
数值 450 → 400；分段筛选 12.5 → 12；对比行旧值 400 / 新值 500。

**字体接口（`design/font.js`）**——运行时修改字体样式的唯一入口：

- `setScale('compact' | 'normal' | 'large')`：0.9 / 1 / 1.15 三档，走 CSS
  `zoom`，布局随字一起缩、不裁切；下拉弹层的 fixed 定位已做 zoom 换算。
- `setUIFamily(name)` / `setMonoFamily(name)`：自定义族**插到栈首**，
  中文字形仍落回 Segoe UI / Microsoft YaHei UI，不出豆腐块；空串恢复默认。
- `reset()` 三项归位。偏好落 localStorage（`llama-ctl.font`），`main.js`
  挂载前生效；同时暴露 `window.llamaFont` 供控制台 / 自动化直调。
- 设置页新增「字体」区：缩放下拉 + 恢复默认 + 两个字体族输入框。

## 第五轮修订（同日：下拉错乱 + 更新不可见的修复）

- **下拉「点开后界面错乱」**：弹层原在行内渲染，`position: fixed` 的包含块被
  视图入场动画残留的 transform 劫持（实测 `.view` 卡在
  `matrix(1,0,0,1,0,5)`），坐标随滚动漂移、被内容区裁切。修复：弹层
  `Teleport` 到 `.d5` 根部的 `.pop-layer`（`display: contents`，继承令牌又
  脱离一切动画/滚动祖先）；视图入场动画 fill 改 `backwards`、终态
  `translate3d(0,0,0)`，不再残留 transform。贴近右缘时弹层自动左收。
- **更新「点了没反应」**：确认弹窗一关，进度与失败原因无处可看。维护页新增
  `.installbox` 安装现场（进度逐行、失败行 err 色、自动贴底）；确认弹窗里的
  备份目录预览改为与 Rust 同形（`<安装目录>\backup\<tag>`，之前硬编码了
  错误的 `F:\llama_ctl\backup`）。Rust 侧（commands.rs / real.rs）同批修复：
  全部命令移出主线程 + HTTP 硬超时，消除卡死。
- **下载必败的两处 HTTP 参数**（同日晚间实测揪出）：ureq 3 的 `read_to_vec`
  默认 10 MiB 响应体上限（`with_config().limit()` 抬到 2 GiB）；以及
  `timeout_recv_body` 是**总时长预算**而非停滞检测——60 s 会把所有大包下载
  掐死在一分钟处，改为 30 分钟。经 `RealDeps::http_get` 真实路径下载 24 MB
  官方资产验证通过（16.9 s）。

## 应用图标（定稿：用户设计的锌色字标，同日）

- **设计来自用户**（SVG 定稿）：锌色圆角砖 #18181B + #27272A 发丝框，两道
  抽象括号（灰 #A1A1AA / 亮 #F4F4F5）暗示耳与面部，玫瑰渐变双加号节点
  （#F43F5E→#FB7185）点出 C++。配色比例与界面一致：深色中性面为主，
  强调色极小面积。
- **实现**：`scripts/make_icon.py` 为该设计的栅格半边（8x 超采样 → LANCZOS），
  产出 `src-tauri/icons/llama_icon.ico`（256/128/64/48/32/24/16，PNG 压缩）、
  根目录副本、`docs/design/app-icon.svg`（母版）、`app-icon-preview.png`
  （深浅双底预览）；index.html favicon 为同源 SVG（base64）。≤32px 档
  描边加粗（14→24）保证 16px 可读，≥48px 与原稿一致。
- **一个技术修正**：SVG 的 objectBoundingBox 渐变在零面积 `<line>` 上未
  定义（浏览器可能不渲染），母版与 favicon 改用 userSpaceOnUse，渐变轴
  映射到双加号簇整体（102,136 → 130,160）——视觉意图不变。
- 构建：`build.rs` 已声明图标 `rerun-if-changed`，换图标重跑 `build.ps1` 即
  生效。历次废弃方案（动物剪影、字母草稿）见 `docs/design/icon-candidates/`。


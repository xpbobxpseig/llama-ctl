# 图标替换与适配方案（基于 OD 图标库）

> **状态：已实施（2026-10-10）。** 口径按确认结果执行：**bold 字重 + 策略 B + 6 个死资源一并替换**。
> 字体**保持现状**，未在本次范围内。
>
> 实施结果与验收见本文 **§八「实施记录」**。所有图标名称、字重、许可、几何数据
> 均取自 OD 图标库实测与真实包体，非推测；验证脚本与渲染对照见文末「证据」。

---

## 一、OD 图标库是什么（实测确认）

| 项 | 实测值 |
|---|---|
| 库 | **Phosphor Icons**（OD `ui-ux-pro-max` 技能的 icon 域数据源） |
| 包 | `@phosphor-icons/core` v2.1.1（`@phosphor-icons/react` v2.1.10 为 React 封装） |
| 规模 | **1512 个图标** × **6 个字重**（thin / light / regular / bold / fill / duotone）= 9072 个 SVG |
| OD 精选子集 | 105 条（`icons.csv`），其中 100 条经校验 |
| **许可** | **MIT**，Copyright (c) 2023 Phosphor Icons（见 `PHOSPHOR-LICENSE.txt`） |
| 几何 | 统一 `viewBox="0 0 256 256"`，**填充路径**（非 stroke），`fill="currentColor"` |
| 取用方式 | 包内直出 SVG：`assets/regular/<name>.svg`、`assets/bold/<name>-bold.svg` |

**关键结论（决定本方案可行）**：该库以**原始 SVG 资源**分发且为 MIT，
因此**无需引入任何 npm/Vue/React 运行时**，可直接取 SVG 光栅化后接入现有
`assets/icons/*.png` 管线。当前项目已是「双帧 PNG + `icon.py` 加载」结构，
适配成本低。

### OD 官方选型规则（原文摘录，本方案的取舍依据）

> *Prefer the most semantically precise Phosphor icon, even if it is outside this
> curated subset. Use Heroicons only as a consistent fallback. Keep one visual
> family per surface.*

即：允许选用精选子集之外的 Phosphor 图标；同一界面只用一个视觉家族。

---

## 二、一个必须先说明的适配约束（实测）

现有自绘 glyph 与 Phosphor 的**笔画重量不在一个档位**。实测 14px / 18px 下
实际渲染的墨迹覆盖率：

| 槽位 | 14px 当前 | 14px Phosphor regular | 14px Phosphor bold | 结论 |
|---|---|---|---|---|
| chevron/caret | 4.7% | 3.1% | 5.2% | 当前 ≈ bold |
| question | 16.1% | 13.4% | 16.3% | 当前 ≈ bold |
| trash | 16.5% | 15.3% | 17.4% | 当前 ≈ bold |
| dot-stop | 16.7% | 16.7% | 18.8% | 当前 ≈ regular/bold 之间 |

聚合（21 个组合）：**当前 / regular = 1.50×，当前 / bold = 1.18×**。

**结论**：若要保持现有图标「在 13–18px 下依然清晰」的观感，
**应选 `bold` 字重**；`regular` 会比现在明显偏细（chrome 图标细 1.1–1.5 倍）。
OD 自身示例多用 `regular`，但那些示例的尺寸是 20–24px；
本项目渲染尺寸是 **13 / 14 / 18px**，低于 `regular` 的设计意图区间。

> 这是一处**实测覆盖文档默认值**的判断，请重点确认。

---

## 三、现有图标清单与候选对应关系

现状：磁盘上 14 个 glyph 资源，界面**实际只渲染 8 个**；
6 个是死资源（`arrow-right`、`chevron-up`、`close`、`play`、`restart`、`stop`）。

### 3.1 当前实际渲染的 8 个（改造重点）

| # | 现有资源 | 用途（源码位置） | 渲染尺寸 | 建议候选（Phosphor） | 字重 | 对应理由 |
|---|---|---|---|---|---|---|
| 1 | `chevron-down` | 折叠组头·展开（`llama_ctl_gui.py:1163,1230` 经 `ic.chevron`） | 13px | **`caret-down`** | bold | OD 精选 105 内，语义即「下拉展开」；`caret` 是 Phosphor 的箭头家族，与自身 `caret-up/right` 同族，收起/展开可成对 |
| 2 | `chevron-right` | 折叠组头·收起（同上） | 13px | **`caret-right`** | bold | 与 #1 同族配对；保证同一控件两态形状一致 |
| 3 | `question` | 参数行问号帮助（`:1245`） | 14px | **`question`** 或 `question-mark` | bold | OD 精选内的 `info` 亦可，但本控件语义是「这是什么参数」而非「通知」，`question` 更精确；**注意尺寸**：现有 `question` 是圆环包问号，Phosphor `question` 本身即圆环，几何同构 |
| 4 | `trash` | 预设删除按钮（`:1116`） | 18px | **`trash`**（OD 精选内） | bold | 语义完全一致；OD 精选条目 `Best For: Delete action destructive` |
| 5 | `dot-run` | 状态·运行中（`_set_dot`，14px） | 14px | **`record`** 或 `pulse` | bold | 见 §3.3 专门讨论（该槽位无直接等价物） |
| 6 | `dot-stop` | 状态·已停止 | 14px | **`circle`** 或 `stop-circle` | bold | 同上 |
| 7 | `dot-error` | 状态·探活失败 | 14px | **`warning-circle`** | bold | OD 精选内，`tags: alert, caution, danger, errors, round`；语义即「圆形警示」 |
| 8 | `dot-dirty` | 状态·过渡 / 未应用 | 14px | **`circle-dashed`** 或 `circle-notch` | bold | 两者都表达「未完成/进行中」；`circle-notch` 在 OD 精选内，`circle-dashed` 在完整库内 |

### 3.2 现存死资源（6 个，**已决策：全部替换**，见 §七）

这 6 个资源已生成但界面从未引用。**最终决定：全部替换为对应 Phosphor 版本**
（保持资源名不变），以避免「一半自绘、一半 Phosphor」的混族。
下表保留当时的两种备选及理由：

| 资源 | 是否有保留价值 | 建议候选 | 说明 |
|---|---|---|---|
| `play` | 有 | `play` | 若日后给「启动」按钮加图标（现为纯文字） |
| `stop` | 有 | `stop` | 同上，「停止」按钮 |
| `restart` | 有 | **`arrow-clockwise`** | OD 精选内，`tags` 含 `*updated*, directional`；比 `restart` 更标准 |
| `close` | 有 | **`x`** | OD 精选内 |
| `arrow-right` | 有 | `arrow-right` | OD 精选内 |
| `chevron-up` | 低 | `caret-up` | 当前 UI 无向上折叠场景 |

> **建议**：6 个全部替换为对应 Phosphor 版本（保持资源名不变，只换造型来源），
> 以避免「一半自绘、一半 Phosphor」的混族；若确认短期不会用到，也可**直接删除**
> 以减少打包体积。**（已定：替换，不删除——见 §七）**

### 3.3 状态点槽位：Phosphor 无直接等价物（**已决策：选 B**，见 §七）

现有状态点是**为语义定制的形状**：实心核 + 38% 透明度外环
（`dot-run`）、方核 + 方环（`dot-stop`）、实心圆 + 抠空感叹号（`dot-error`）、
斜线环（`dot-dirty`）。Phosphor **没有**「实心核 + 半透明光环」这种构造。

实测候选（14px 真实渲染，见 `status-dot-candidates.png`）：

| 状态 | Phosphor 候选 | 几何（实测） | 适配评价 |
|---|---|---|---|
| 运行中 | `record` (bold) | 三层同心环（外环 104 / 中 88 / 内 72 半径） | **形状偏复杂**，14px 下三层环会糊；内层不再是实心核 |
| 运行中 | `pulse` (bold) | 心电折线 | 语义好但**形状与其它三个状态点完全不同族**，一行里不协调 |
| 已停止 | `circle` (bold) | 单圆环 | 干净，但与「运行中」的实心感对比不足 |
| 已停止 | `fill/circle-fill` | **实心圆**（单子路径） | 实心，与 `record` 的实心核接近 |
| 探活失败 | `warning-circle` (bold) | 圆环 + 感叹号 | **推荐**：语义与形状都合适，且与现有「圆 + 感叹号」同构 |
| 过渡 | `circle-dashed` (bold) | 虚线圆环 | 语义准确（未完成），OD 完整库内 |
| 过渡 | `circle-notch` (bold) | 缺口圆环 | OD 精选内，更简洁 |

**三个候选策略 —— 最终选定 (B)**：

- **(A)** 4 个状态点**全部改用 Phosphor bold**：`record` / `circle` /
  `warning-circle` / `circle-dashed`。优点：真正「同一个视觉家族」；
  缺点：失去「实心核 + 光环」的层次，且 `record` 的三层环在 14px 偏细。
- **(B)（✅ 已采用）** 只替换 `dot-error` → `warning-circle`、`dot-dirty` →
  `circle-dashed`（这两个形状本就与 Phosphor 同构），
  `dot-run` / `dot-stop` **保留自绘**（因为它们是纯几何形状，不属于任何
  图标家族，不存在「家族冲突」）。优点：视觉风险最低。
- **(C)** 4 个状态点都不动，只替换 1–4 号功能图标。

> 补充（已落实）：状态点在 §八 中单独说明为**状态指示符（status indicator）**，
> 而非 icon——符合 OD 的 `Contextual Semantics` 规则（按用途而非字形归类）。

### 3.4 未被现有图标覆盖、但 OD 有标准解的位置（可选增强）

以下控件当前**纯文字、无图标**。本方案**不建议**在本次一并添加
（会扩大改动面），仅列出 OD 对应候选供你判断：

| 控件 | 现状 | OD 候选 | 字重 |
|---|---|---|---|
| 启动 / 停止 / 重启 按钮 | 纯文字 | `play` / `stop` / `arrow-clockwise` | bold |
| 设置 按钮 | 纯文字 | `gear` | bold |
| 还原 按钮 | 纯文字 | `arrow-counter-clockwise` | bold |
| 应用更改 按钮 | 纯文字（primary） | `check` | bold |
| 日志折叠条 | 纯文字 | `caret-down` / `caret-up` | bold |
| 官方更新 · 立即检查 | 纯文字 | `arrow-clockwise` | bold |

---

## 四、适配方式（技术路径，**已按此实施**，见 §八）

### 4.1 为什么改造成本低

现有管线：`make_icons.py`（自绘 → 双帧 PNG）→ `assets/icons/glyph_<name>.png`
→ `icon.py`（按主题裁帧 / `tinted()` 运行时着色）→ GUI。

接入 Phosphor 只需**替换 `make_icons.py` 里的形状来源**：
由「自绘几何」改为「读取 Phosphor SVG 路径 → 光栅化」。

### 4.2 需要处理的 5 个技术细节

| # | 细节 | 实测情况 | 处理方式 |
|---|---|---|---|
| 1 | **尺寸口径不同** | Phosphor `viewBox 0 0 256 256`；现有资产 72px 帧（= 24 网格 × 3） | 光栅化时缩放到 72px 帧，保持现有 `FRAME=72` 不变 |
| 2 | **笔画重量不同** | Phosphor 用填充路径表达带；regular 的圆角半径为 8 单位、bold 为 12 单位 | 用 `bold` 以匹配现有重量（见 §二） |
| 3 | **文件命名规则按字重变化** | `regular` **不带**后缀（`regular/caret-down.svg`）；其余 5 个字重**都带**后缀（`bold/caret-down-bold.svg`）。实测：regular 目录 1512 个文件全部无后缀 | 取资源时按字重决定是否拼 `-<weight>` 后缀（`regular` 是例外）；已实测确认 |
| 4 | **填充色是 `currentColor`** | 全部 SVG 用 `fill="currentColor"` | 光栅化时替换为目标主题色，保持 `tinted()` 能力 |
| 5 | **安全区 / 视觉重心** | 现有资产内边距：`question` 6/6、`trash` 7/7、`dot-run` 9/9（72px 帧）；Phosphor 自身留白不同 | 需统一到同一安全区，否则同排图标看起来大小不一 |

### 4.3 许可与归属（MIT）

- 允许商用、修改、再分发。
- **义务**：保留版权与许可声明。建议随仓库加 `THIRD-PARTY-NOTICES`，
  并保留 `PHOSPHOR-LICENSE.txt`。
- 打包进 exe 时同样需要保留声明（PyInstaller 单文件内嵌）。

---

## 五、建议的执行顺序（**已按此执行**，见 §八）

1. 确定 §二 的字重选择（**bold**，或接受更细的 **regular**）。
2. 确定 §3.3 状态点策略（**A / B / C**）。
3. 确定 §3.2 死资源处理（**替换** / **删除**）。
4. 按 §四 改造 `make_icons.py` 的形状来源，其余管线（`icon.py`、
   双帧结构、`tinted()`、GUI 调用点、测试）**全部不动**。
5. 回归：现有 **261 项测试全部复跑**。其中两个测试文件直接约束本次改动，需重点看：
   - `tests/test_icons_assets.py` —— **守 UI glyph**（读 `make_icons.GLYPHS`）：
     双帧 144×72 结构、每个 glyph 双帧都有墨迹、浅深两帧色值不同、
     `chevron`/`question`/`trash` 两帧必须不同、`ic.set_appearance(resolved)` 接入点仍在。
   - `tests/test_icon.py` —— **守应用 icon**（读 `make_icon`），与本次 glyph 替换无关，
     但如果顺带调整了 `make_icons.py` 的公共常量（`GLYPHS` / `OUT_DIR` / `ROOT`）会连带影响，
     故一并复跑。

> 因为只换「形状来源」，`assets/icons/*.png` 的文件名、双帧格式、
> `icon.py` API 都不变，所以 **GUI 源码无需改动**——
> 这也是本方案相对「直接换图标库」的最大成本优势。

---

## 六、证据（可自行复核）

| 文件 | 内容 |
|---|---|
| `docs/design/icon-mapping/mapping-evidence.png` | **12 个槽位的三方对照**：当前自绘 / Phosphor regular / Phosphor bold，含 14px、18px 真尺寸与 4× 放大 |
| `docs/design/icon-mapping/status-dot-candidates.png` | 状态点候选 14px 真尺寸 + 6× 放大 |
| `docs/design/icon-mapping/mapping-evidence.html` | 上表可交互源文件（自包含，含内联 SVG） |
| `docs/design/icon-mapping/side-by-side.html` | 早期侧栏对照 |
| `docs/design/icon-mapping/PHOSPHOR-LICENSE.txt` | MIT 许可原文（出自包体 `LICENSE`） |

**核验过的库事实**（可复现）：
- OD 目录 1512 个名字 ↔ 真实包内 1512 个文件，本方案引用的 **34 个候选名全部命中**
  （既在 OD 目录内，也在 `regular` 与 `bold` 两种字重下存在）。
- MIT 许可见 `@phosphor-icons/core` v2.1.1 的 `LICENSE` 与 npm 元数据（`license = 'MIT'`）。
- 笔画重量对比来自 14/18px 实渲染墨迹覆盖率（21 个组合聚合）。

---

## 七、确认结果（4 项已定）

| # | 待定项 | 确认结论 |
|---|---|---|
| 1 | 字重 | **bold**（按 §二 实测：regular 在 13–18px 会明显偏细） |
| 2 | 状态点 | **策略 B** —— 只换 `dot-error` → `warning-circle`、`dot-dirty` → `circle-dashed`；`dot-run` / `dot-stop` 保留自绘 |
| 3 | 6 个死资源 | **替换为 Phosphor 版本**（保持资源名不变，避免混族） |
| 4 | 范围 | **不含** §3.4 —— 本次不给纯文字按钮新增图标，不扩大改动面 |

---

## 八、实施记录（已完成）

### 8.1 改了什么

| 文件 | 改动 | 性质 |
|---|---|---|
| `assets/phosphor/bold/*.svg`（12 个） | vendored Phosphor bold 原始 SVG | **新增**，构建期资源 |
| `assets/phosphor/LICENSE.txt` | MIT 许可原文（随源资源） | **新增** |
| `svgpath.py` | 无依赖 SVG path 解析 + **非零环绕**扫描线光栅化器 | **新增**，构建期工具 |
| `make_icons.py` | 形状来源改为「读 Phosphor SVG → 光栅化」；保留 2 个自绘状态点 | **重写**（v3） |
| `assets/icons/glyph_*.png`（14 个） | 用 v3 重新生成 | **重新生成** |
| `THIRD-PARTY-NOTICES.txt` | Phosphor MIT 归属声明 | **新增**（许可义务） |
| `llama_ctl.spec` | `datas` 增加 `THIRD-PARTY-NOTICES.txt` | 小改 |

**未改动**（这是本方案的核心成本优势）：`icon.py` 全部 API、`assets/icons/` 的文件名与
72×144 双帧格式、`llama_ctl_gui.py` 的每一处调用点、字体令牌。

### 8.2 实施中修正的三处判断（与初稿方案的差异）

1. **取消逐图标归一化。** 初稿计划把每个图标按 bbox 归一到统一比例
   （曾用 `TARGET_INK = 0.72`）。实测发现 **Phosphor bold 的原生光学尺寸本
   就与旧自绘图标吻合**：

   | 槽位 | 旧自绘 longest | Phosphor 原生 | 差异 |
   |---|---|---|---|
   | `question` | 83.3% | 84.4% | +1.1 |
   | `trash` | 80.6% | 85.9% | +5.3 |
   | `arrow-right` | 76.4% | 78.1% | +1.7 |
   | `restart` | 86.1% | 84.4% | −1.7 |
   | `dot-error` | 83.3% | 84.4% | +1.1 |

   若强行统一到 72%，反而会把 `question`/`restart`/`dot-error` **缩小 8–14%**。
   故最终**照搬库的原生 viewBox 比例**，不做归一化。
   实机核对：14px 下新旧墨迹覆盖率 run 1.24×、stop 1.23×、error 0.91×、dirty 0.82×，
   四个点均**可辨且等大**（旧设计本身四个点外径为 52–60px 不等，现已统一为 62px）。

2. **自绘状态点对齐到 Phosphor 圆形的外径（84.4%）**，而不是沿用旧的 72%。
   因为四个状态点**同排渲染**（`_set_dot`），两个来自 Phosphor 的圆 + 两个自绘
   必须等大。实测四者外径现均为 **62px / 72px = 86%**，视觉等大。

3. **光栅化器补齐 `Q`/`T` 并改为「未知命令即报错」。** 自查发现
   `svgpath.py` 原只实现 M/L/H/V/C/S/A/Z，**漏了二次贝塞尔 `Q`/`T`**。
   当前 12 个 vendored 图标恰好不用 Q/T，所以**没有暴露**；但词法器对未实现的
   命令会掉进「隐式重复」分支、静默沿用上一条命令，日后换一个用 Q/T 的 Phosphor
   图标就会产出**看似正常但错误**的图形。已修：实现 Q/T（含 `T` 的控制点反射
   语义），并让未知命令、参数不足一律抛 `ValueError`。此改动经核对为
   **输出中性**：14 个资源 SHA256 全部未变。自检脚本已加入 Q/T 与非法命令的
   回归断言，防止复发。

### 8.3 验收结果

| 检查 | 结果 |
|---|---|
| 14 个资源均为 144×72 双帧、双帧各有墨迹、浅深两帧色值不同 | ✅ |
| 4 个状态点外径一致（同排等大） | ✅ 均为 62px |
| 浅/深两帧分别为对应主题语义色（如 `trash` `#c2261c` / `#ff6b61`） | ✅ 14/14 |
| `icon.py` 实机路径：`glyph()` 两主题取帧正确、`chevron()` 两态不同、`tinted()` 只换色不改形 | ✅ ALL PASS |
| 浅/深主题真实窗口截图 14 个图标逐一比对（`before-after-{light,dark}.png`） | ✅ |
| 全套测试 | ✅ **261 passed** |
| 打包：`assets/phosphor/` 与 `svgpath.py` 均为构建期，不入包 | ✅ 仅需 `assets/icons/*.png` |

> 说明：`assets/icons/*.png` 的**文件名与双帧格式未变**，所以 `llama_ctl.spec`
> 里原有的 `('assets/icons/*.png', 'assets/icons')` 无需改动。

### 8.4 复现方式

```powershell
.\.venv\Scripts\python.exe svgpath.py          # 光栅化器自检（挖孔/圆弧/填充）
.\.venv\Scripts\python.exe make_icons.py preview   # 重新生成 14 个资源 + 预览图
.\.venv\Scripts\python.exe -m pytest -q        # 261 项
```

### 8.5 许可合规

Phosphor 为 MIT：允许商用/修改/再分发，**义务是保留版权与许可声明**。
已落两处：`assets/phosphor/LICENSE.txt`（随源资源）与仓库根 `THIRD-PARTY-NOTICES.txt`
（并已加入 PyInstaller `datas`，使声明随分发件同附）。

### 8.6 展开指示的观感变化（**已确认：维持现状**）

其余 13 个图标都是**同形状换源**（朝向与留白一致），只有**展开指示**的
«笔画粗细特性»变了：

| | 旧 | 新 |
|---|---|---|
| 造型 | **描边**式细 chevron（两道细笔画） | **填充**式厚 caret（V 形实心楔带，中心上方仍镂空） |
| 13px 墨迹 | 32–34% | 37–39%（+4 个百分点，视觉更「重」） |

（已放大核对：`caret-down` 的 V 形中心上方仍是空的，**不是实心三角**，仍读作 chevron；
差别只在「细笔画 → 厚实心带」。）

原因是 **Phosphor 的 `caret-*` 家族全部是这种填充楔带**，库里没有描边式细 chevron：
查证 1530 条目录，`chevron*` 仅 `shield-chevron` / `tag-chevron`（与折叠语义无关），
`caret-*` 共 22 条，均为填充式。

**已确认结论（用户裁定）：维持现状** —— 采用 `caret-down` / `caret-right`，
不为折叠指示破例保留自绘。理由是「与其余图标同一视觉家族」优先于
「比原来重一点」的观感差异。

> 决策时提供的备选（**未采用**）：沿用旧的自绘细 chevron，即把
> `chevron-down`/`chevron-right` 与两个状态点一样列入「保留自绘」——
> 代价是折叠指示与其余图标不同族。

> 已验证的两个「不可行」替代，避免你走弯路：
> - `caret-line-*`：实测是「V + 下划线」两个子路径（`M39.51,80.49 … Z M208,180 H48 … Z`），
>   加了横线，与折叠语义冲突。
> - `caret-double-*`：实测**更重**而非更细（13px 墨迹 58.6% vs `caret-down` 的 37.3%）。

**结论：本次不做进一步改动**，`caret-down` / `caret-right` 即为最终选择。

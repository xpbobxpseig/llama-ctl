# 字体与图标统一规范（v2）

> 实施状态：**已落地**。本文记录改动依据、实现位置与验收结果。
> 视觉规范原稿（含全部图标 SVG 与字样样张）：`docs/design/font-icon-spec.html`、
> `docs/design/app-icon-concepts.html`。
> 所有数字来自对现有程序的实测，非估计值。

---

## 一、为什么要改（实测诊断）

### 1.1 字体：三个角色共用一个样式，层级消失

原代码只有 4 个令牌：

| 令牌 | 原值 | 被谁用 |
|---|---|---|
| `F_TITLE` | YaHei UI 18 bold | 窗口标题 |
| `F_BODY` | YaHei UI 13 | 参数标签、按钮、输入框 |
| `F_SMALL` | YaHei UI 12 | 辅助说明 |
| `F_GROUP` | YaHei UI 12 bold | **卡片标题 + 折叠组头 + 日志开关**（三个角色！） |

实测的三个具体缺陷：

1. **卡片标题 / 折叠组头 / 日志开关共用 `F_GROUP(12 bold)`** —— 「启动参数」既是
   卡片标题也是组头样式，层级完全分不出来。
2. **数值读数与正文行盒错位**：数值用 `Consolas 12`（行高 19px），同一行的文本输入用
   `YaHei 13`（行高 23px），**差 4px**，同一行的控件基线不齐。
3. **字阶只有 12 / 13 / 18 三档**，12 与 13 几乎不可分辨，中间没有可用层级。

字体家族实测（本机 Tk 解析）：

| 家族 | 可用 | 备注 |
|---|---|---|
| Microsoft YaHei UI | ✅ | 中文界面首选 |
| Segoe UI Variable Text | ✅ | 拉丁文字更精细（备用） |
| Cascadia Mono | ✅ | 等宽首选（Win11 自带） |
| Consolas | ✅ | 等宽回退 |

> 重要限制：**Tk 只接受 `normal` / `bold` 两种字重**（传 `semibold` / `600` / `500`
> 一律抛 `TclError`）。因此层级差异只能靠**字号 + 字重**表达，不能依赖中间字重。
> 这正是规范里 600 字重需落到 Tk 时降为 `bold` 的原因。

### 1.2 图标：14 个资产里 10 个是死代码，状态点根本不是图标

实测 GUI 对图标体系的全部引用只有 4 处：

```
ic.glyph("trash", 18)      ic.chevron(...)  (2 处)      ic.glyph("question", 14)
```

结论：

| 事实 | 影响 |
|---|---|
| **10 / 14 个 glyph 从未被引用**（arrow-right、chevron-up、close、dot-run/stop/error/dirty、play、restart、stop） | 白占打包体积；且 `play`/`stop`/`restart` 明明表达了启停语义，界面却只用文字按钮 |
| **状态点是字体字符 `\u25CF`**（`CTkLabel(text="●")`），不是图标资产 | 尺寸由 Microsoft YaHei UI 的字形决定：13px 字号下实测**墨迹 13×23px**、advance 11px；与 24 单位图标网格无关，换字体就变形 |
| 不同家族的 U+25CF advance 差异巨大 | YaHei UI 11px / Segoe UI 10px / Segoe UI Symbol 15px / Noto Sans SC **17px** —— 换字体就错位 |

这就是「不统一」的根源：**状态点走字体体系，其余图标走图标体系，两套并行**。

### 1.3 应用图标：过时、难辨认、不体现用途

对旧图标（`>_` 终端提示符 + 渐变蓝底 + 右上角绿点）的实测：

| 问题 | 实测证据 |
|---|---|
| **过时** | 平板是 `#4aa6ff → #055ad4` 的强渐变，**亮度跨度 2.39:1**；现代平板色差通常在 1.0–1.2:1。强渐变是 2010 年代拟物化特征 |
| **难辨认** | 渐变导致白色标记的对比度**随位置变化**：亮端仅 **2.56:1**（低于 AA 4.5），暗端 6.14:1。同一个标记一边清一边糊 |
| **不体现用途** | `>_` 的语义只是「终端」，任何命令行工具都能用，看不出 llama.cpp / 本地模型服务 |
| 绿点在 16px 糊掉 | 右上角绿点实测直径仅 **3.84px**（占图标宽 24%），在 16px 下读作色块而非「服务在跑」 |

---

## 二、字体统一（已实施）

### 2.1 新字阶：6 个语义层级 + 2 个字宽层级

定义在 `llama_ctl_gui.py` 的字体令牌段：

| 令牌 | 字体 / 字号 / 字重 | 用途 | 解决什么 |
|---|---|---|---|
| `F_DISPLAY` | YaHei UI 18 bold | 窗口标题 | （原 `F_TITLE` 的别名保留） |
| `F_SECTION` | YaHei UI 15 bold | **卡片标题** | 与组头脱钩 |
| `F_GROUP` | YaHei UI 13 bold | **折叠组头** | 与卡片标题脱钩 |
| `F_BODY` | YaHei UI 13 | 参数标签 / 按钮 / 输入框 / **日志开关** | 日志开关脱离 bold |
| `F_SMALL` | YaHei UI 12 | 辅助说明 | — |
| `F_MICRO` | YaHei UI 11 | 最小层级 | 新增第 6 档 |
| `F_MONO` | **Cascadia Mono 13** | 数值读数 | 与正文同字号 → 行盒对齐 |
| `F_MONO_SM` | Cascadia Mono 11 | 日志行 | 等宽、紧凑 |

**关键改动**：

- 三处碰撞的角色分开：卡片标题 15 / 组头 13 bold / 日志开关 13 regular。
- `F_MONO` 从 `Consolas 12` 改为 `Cascadia Mono 13`（与 `F_BODY` 同字号），
  行高差从 **4px 降到 1px**，同一行的数值与输入框基线对齐。
- 家族常量化为 `_UI_FAMILY` / `_MONO_FAMILY`，杜绝散落的裸字面量。

### 2.2 字阶单调性

```
18 > 15 > 13 = 13 > 12 > 11
```
由 `tests/test_font_tokens.py::test_micro_is_smallest_ui_step` 守护。

---

## 三、图标统一（已实施）

> **后续更新（2026-10-10）：图标造型来源已整体改为 OD 图标库。**
> 3.1/3.2 记录的「24 单位网格 + `Pen` 类自绘」已被替换为
> **Phosphor Icons bold** 光栅化（12 个功能图标 + 2 个自绘状态点），
> 详见 `docs/design/icon-replacement-plan.md` §八。以下保留为历史记录。
> 输出的 **72×144 双帧 PNG** 格式、`icon.py` API、主题语义色**均未变**。

### 3.1 网格规范（`make_icons.py`，v2 历史记录）

- **24 单位网格**，笔画宽 **2.5 单位**，**圆头端点** + 圆角连接
- 最小内边距 2 单位；填充形状外角半径 1.5 单位
- 单色 glyph；输出 **72×144 双帧 PNG**（左帧浅色主题色 / 右帧深色主题色）
- 绘制走同一个 `Pen` 类，不再有各图标自定的现场参数
- **现状**：`Pen` 自绘已废弃；仅 `dot-run` / `dot-stop` 两个状态点保留自绘
  （它们是纯几何形状，不属于任何图标家族），其余图标由 Phosphor bold SVG 光栅化

### 3.2 关键修复（v2 历史记录）

| 修复 | 说明 |
|---|---|
| **状态点改为真正的 glyph** | 形状不再随字号漂移（原为字体字符 `\u25CF`） |
| 四个点的**形状本身携带语义** | 14px 下两两比较，差异 alpha 像素 121–152，全部可区分 |
| 图标语义色对齐可访问性 | light 的 MUT `#86868b`→`#5f5f66`、RUN `#30d158`→`#0f7b3d`、ORG `#ff9500`→`#9a5b00`、RED `#ff3b30`→`#c2261c`（原值对比度均低于 4.5） |
| **现状补充** | `dot-error` → Phosphor `warning-circle`、`dot-dirty` → `circle-dashed`（形状本就同构）；`dot-run` 实心核 + 光环、`dot-stop` 方核 + 方环仍为自绘 |

### 3.3 运行时着色（`icon.py`）

新增 `tinted(name, size, color)`：取左帧的**形状与 alpha**，整色替换。
状态点的呼吸/闪烁动效按此换色，**形状随状态变、颜色随动效变**。

- 颜色量化到 5 位/通道后作缓存键 → 动效逐帧换色不会让缓存无限增长
- 缓存上限 64，超出即整体清空（动效帧复用率极高，抖动可忽略）

---

## 四、应用图标重做（已实施）

### 4.1 新设计：羊驼 + 健康脉冲

| 维度 | 旧 | 新 |
|---|---|---|
| 平板 | `#4aa6ff → #055ad4` 渐变 | **`#0b5cb0` 纯平** |
| 标记 | `>_` 终端提示符 | **羊驼剪影**（llama.cpp 的字面指涉） |
| 状态表达 | 右上角 3.84px 绿点 | **剪影内抠出的健康脉冲线 + 眼** |
| 标记对比度 | 2.56 ~ 6.14（随位置变化） | **恒定 6.62:1** |
| 渐变亮度跨度 | 2.39:1 | **1.0:1（纯平）** |

### 4.2 小尺寸分级（实测驱动的取舍）

实测发现：内层细节（眼 + 脉冲线）在 **< 48px 会被降采样糊掉**
（32px 时仅 11 个可辨像素，16px 时归零）。因此 `render()` 按尺寸分级：

| 尺寸 | 画什么 | 理由 |
|---|---|---|
| ≥ 48px | 完整细节（羊驼 + 眼 + 脉冲线） | 细节清晰可辨 |
| < 48px | **仅羊驼剪影** | 保住唯一可辨特征：16px 下仍有 4 行双耳分离 |

> 剪影可拆性已量化为断言：`test_silhouette_ears_survive_at_small_size`
> 要求 16 / 24 / 32px 各有 ≥2 行出现两个独立白色段（双耳分离）。

### 4.3 ICO 结构

7 档（16/24/32/48/64/128/256），32bpp，PNG 编码，
**256 档排首位**（PyInstaller 嵌入依赖此顺序）。总 31.4 KB。

---

## 五、验收结果

### 5.1 测试

```
261 passed
```

新增 `tests/test_font_tokens.py`（14 项）守护字体契约；
`tests/test_icon.py` 的 4 项旧断言（守护已废弃的绿点设计）改写为守护新契约并**加强了覆盖**：
新增「纯平品牌蓝」「内层细节按尺寸分级」「16px 双耳可分离」。

### 5.2 运行时核验（真实启动程序，非静态检查）

| 检查 | 结果 |
|---|---|
| 状态点是图片资产而非文字 | `text=''` + `image=set` ✅ |
| 四个状态形状互不相同 | run/stop/error 三张图互不相同 ✅ |
| 6 个界面令牌全部解析为 `Microsoft YaHei UI`（无替换） | ✅ |
| 等宽令牌解析为 `Cascadia Mono`，行高差 1px | ✅ |
| 界面中出现 6 种不同字号组合（层级真实存在） | 18/15/13/13b/13mono/12 ✅ |
| 14 个 glyph 资产可加载 | ✅ |

新字阶在真实控件树里的分布：

```
YaHei 18 bold   x1    窗口标题
YaHei 15 bold   x2    参数预设 / 启动参数      <- 卡片标题
YaHei 13 bold   x7    7 个折叠组头             <- 组头（原与卡片同级）
YaHei 13        x37   标签 / 按钮 / 输入框
Cascadia Mono13 x11   11 个数值读数            <- 与正文同行盒
YaHei 12        x39   辅助说明
```

### 5.3 视觉对照

`docs/design/preview/`：

| 文件 | 内容 |
|---|---|
| `main-window-before-after.png` | 主窗改版前/后并排 |
| `app-icon-sizes.png` | 新应用图标 7 档真尺寸 |
| `app-icon-16-24-32-zoom.png` | 16/24/32px 8 倍放大（核对小尺寸可辨性） |
| `status-dots.png` / `status-dots-shape.png` | 四个状态点的彩色与纯形状对照 |
| `glyphs-light.png` / `glyphs-dark.png` | 14 个图标 × 双主题 × 14/18/24px |
| `ui-after-light.png` / `ui-after-dark.png` / `ui-after-settings.png` | 改版后实际界面 |

---

## 六、改动清单

| 文件 | 改动 |
|---|---|
| `llama_ctl_gui.py` | 新增字体令牌段（8 个令牌 + 2 个家族常量）；卡片标题/组头/日志开关/数值/日志改用对应令牌；状态点改用 `ic.tinted()` + 新增 `_set_dot()` |
| `make_icons.py` | v2：统一 Pen、新 glyph 几何、状态点改为形状资产【**v3 已重写**：造型来源改为 Phosphor bold SVG 光栅化，见下行】 |
| `svgpath.py` | **新增（v3）**：无依赖 SVG path 解析 + 非零环绕光栅化器（构建期工具） |
| `assets/phosphor/` | **新增（v3）**：vendored Phosphor bold SVG ×12 + MIT 许可 |
| `THIRD-PARTY-NOTICES.txt` | **新增（v3）**：Phosphor MIT 归属声明（并纳入打包 `datas`） |
| `assets/icons/glyph_*.png` | **v3 重新生成**：12 个 Phosphor bold + 2 个自绘状态点；文件名与双帧格式不变 |
| `icon.py` | 新增 `tinted()` 运行时着色 + 量化色缓存 |
| `make_icon.py` | 重写：纯平平板 + 羊驼剪影 + 内层细节按尺寸分级 |
| `tests/test_font_tokens.py` | 新增（14 项） |
| `tests/test_icon.py` | 4 项旧断言改写为新契约 |
| `docs/design/font-icon-spec.html` | 视觉规范（OD 产出） |
| `docs/design/app-icon-concepts.html` | 3 个图标方案 + 推荐（OD 产出） |

**未改动**：`params.py`、`nssm_adapter.py`、`updater.py`、`installer.py`、
`presets.py`、`settings.py` 的业务逻辑；无新增依赖。

> **v3 增补（2026-10-10）**：图标造型来源改为 OD 图标库（Phosphor Icons bold），
> 完整对应关系、适配理由与验收见 `docs/design/icon-replacement-plan.md`。
> 本次**未改动**字体令牌、`icon.py` API、`llama_ctl_gui.py` 调用点。

# llama.cpp Service Console (llama_ctl)

[中文](#中文说明) | [English](#english)

---

<a id="中文说明"></a>
## 中文说明

通用 Windows GUI，直接接管由 **NSSM** 管理的**任意** llama.cpp 服务（默认 `QwenLLM`，顶部可切换）。模型无关：Qwen / Llama / DeepSeek / GLM 等任意 GGUF 模型均可。

### 功能

- 数值参数用**步进数值框**、枚举参数用**自绘下拉**（键盘 ↑↓ / Enter / Esc），每项与每个选项都带初学者友好的中文详解（悬停可见）
- 直接读写 NSSM `AppParameters`（修掉 `-c` 与 `--ctx-size` 冲突）
- 启停 / 重启 / 开机自启切换、`/healthz` 探活、`server.err` 日志尾随
- 写回 / 重启均二次确认，先展示新旧参数对比
- 「未应用更改」用**语义等价**判定：历史遗留 / 手写 / 其他工具生成的等价参数（短名、乱序、缺省默认值）不会被误报为改动
- 参数预设（本地保存 / 加载 / 删除 / 自动备份），跨服务复用
- **模型市场**：GGUF 模型的 发现 → 下载 → 适配评估 → 实测 → 一键启用 闭环（魔搭 ModelScope 默认 / HuggingFace 双源可切换，详见下文「模型市场」）
- 官方 llama.cpp 更新：检查 / 下载 / 备份 / 替换 / 回滚，全程需确认
- 启动时后台清理官方更新的陈旧下载与备份（各保留最近 3 个），无确认、不打扰
- 动效与主题：原生「精密仪器」风浅 / 深双主题（Segoe UI Variable + 单一森林绿交互色 + 发丝线分层，见 `docs/ui-redesign-v6.md`）、按钮驻留渐隐、视图 / 弹层入场动效、动效总开关（关闭后所有动画直跳终态）
- 日志页轮询**自适应降占用**：紧跟档 1.5s，静默后退到 3s / 5s 上限，新行立刻回紧跟档（长挂日志页的 IPC 与读盘降到约三分之一）
- 界面骨架文案中英双语（参数详解保持中文）

### 环境要求

- **Windows**（依赖系统 `nssm.exe`、`sc`、`powershell`）
- 已安装 [NSSM](https://nssm.cc/) 并已把 llama.cpp 注册为服务
- 从源码构建需要 Rust ≥ 1.85（`src-tauri\Cargo.toml` 的 `rust-version`）、Node.js 与 npm，以及 `cargo install tauri-cli`（2.x）

### 安装与使用

**方式一（推荐）：下载发布版安装包**

1. 到 [Releases](https://github.com/xpbobxpseig/llama-ctl/releases) 下载 NSIS 安装包（`.exe`）
2. 双击运行。安装后无需 Python、无需 Rust 环境。

**方式二：从源码构建并运行**

桌面端是 **Tauri 2 + Vue 3** 应用（`src-tauri\` + `frontend\`），构建入口是根目录的 `build.ps1`：

```
cd frontend
npm install
cd ..
cd src-tauri
cargo tauri dev        # 开发模式：自动起 Vite dev server（devUrl http://localhost:5173）
cd ..
.\build.ps1            # 打包：根目录产出 llama-ctl.exe + NSIS 安装包
```

> 需要先 `cargo install tauri-cli --version "^2"`。本机已验证 `cargo tauri --version` 为 2.12.3；`build.ps1` 会负责前端构建、Rust 打包和根目录复制。

### 更新日志

- **v0.2.0（当前）**：新增**模型市场**视图——双源 GGUF 发现（热门榜 / 关键词搜索 / 量级筛选，魔搭默认、记住上次选择）、自研流式下载引擎（Range 断点续传 + `.part` 原子转正 + SHA256 校验、单任务队列、暂停 / 继续 / 取消、跨重启恢复、磁盘空间预检）、四档硬件适配等级（DXGI 枚举 + 物理内存检测，每档附一行依据，注明未计 KV 增长）、`llama-bench` 一键实测（pp512 / tg128 成绩存档，停服 → 测 → 按原状态恢复）、一键启用（回填 `--model` / `--mmproj` 走既有 Apply，AppParameters 唯一真源不破）、已下载管理（实测 / 启用 / 打开目录 / 删除，删除命中当前模型强警告）。设置页新增「市场」节（HF / 魔搭令牌、下载根目录）。顶栏「打开安装目录」接通（此前禁用）。规格见 `docs/spec/model-marketplace.md`，决策见 `docs/adr/0004-self-hosted-gguf-downloader.md`。
- **v0.1.0（拉马管家）**：桌面端从 CustomTkinter 整体重写为 **Tauri 2 + Vue 3**，落地 v6「精密仪器」设计系统（见 `docs/ui-redesign-v6.md`）；官方 llama.cpp 更新下载支持断点续传（Range）+ 重试退避 + ZIP 逐条 CRC 校验后才转正；界面骨架文案中英双语。已发布资源：[NSIS 安装包 + 绿色版 exe](https://github.com/xpbobxpseig/llama-ctl/releases/tag/v0.1.0)，SHA256 见 release 说明。

### 环境变量（可选）

程序默认使用作者本机的路径；在其他机器上部署时用环境变量覆盖，无需改代码：

| 变量 | 作用 | 默认值 |
|------|------|--------|
| `LLAMA_CTL_NSSM_EXE` | `nssm.exe` 绝对路径 | `F:\llama.cpp\nssm\nssm-2.24\win64\nssm.exe` |
| `LLAMA_CTL_SERVICE` | 默认服务名（下拉初始选中项） | `QwenLLM` |
| `LLAMA_CTL_LLAMA_DIR` | llama.cpp 安装目录（更新替换目标回退） | `F:\llama.cpp` |
| `LLAMA_CTL_ERR_LOG` | 日志尾随回退路径 | `F:\llama.cpp\server.err` |
| `LLAMA_CTL_PRESETS` | 预设文件 | `F:\llama_ctl\presets.json` |
| `LLAMA_CTL_SETTINGS` | 设置文件 | `F:\llama_ctl\settings.json` |
| `LLAMA_CTL_DOWNLOAD_DIR` | 官方资产下载缓存 | `F:\llama_ctl\downloads` |
| `LLAMA_CTL_BACKUP_DIR` | 旧文件备份根目录 | `F:\llama_ctl\backup` |

> 多数路径在运行时优先按当前服务 NSSM `AppDirectory` 推导，环境变量只作为推导失败时的回退。

### 模型市场

侧栏底部「市场」视图，把 GGUF 模型的获取闭环搬进管家里（发现 → 下载 → 适配评估 → 实测 → 一键启用）：

- **发现**：热门榜（按下载量前 50，只收录 GGUF）+ 关键词搜索 + 「规模」下拉（全部 / ≥1B / ≥7B / ≥30B，默认 ≥1B 筛掉小模型）。双源可切换：魔搭 ModelScope（默认，国内 CDN 快 8.8×）/ HuggingFace，记住上次选择；HF gated 仓库标注「需授权」。
- **详情**：按文件名把文件归组为量化档（主文件 / 分片组 / mmproj 投影），每档展示总体积与**四档适配等级**（流畅 = 全进显存 / 可行 = 大部分进显存（附估计 offload 比例）/ 勉强 = 主要靠内存 / 不建议），每级附一行依据（按权重估算，未计上下文对应的 KV 增长）。硬件检测走 DXGI 枚举 + 物理内存，无子进程。
- **下载**：行内直接下单；自研流式引擎（独立于服务锁，40GB 下载期间参数页照常可用）：Range 断点续传、`.part` 原子转正、SHA256 校验（无校验和的仓库降级体积校验并明示）、失败指数退避重试、入队前磁盘空间预检（不足直接拒绝并明示缺口）、单任务队列、暂停 / 继续 / 取消、任务列表持久化（重启后从断点拉起）、失败原因就地红字显示；任务行实时显示速度与**预计剩余时间**。
- **已下载**：扫描下载根目录（两层深，兼容子目录与平铺布局），区头按设备分行显示显卡 / 内存，并显示下载根所在卷的剩余空间；每行含 体积 / 适配等级 / 实测成绩；操作：实测 / 启用 / 打开目录 / 删除（删除命中当前服务模型时强警告）。
- **实测**：服务在跑时确认后 停服 → `llama-bench -o json` → 按原状态恢复，成绩（pp512 / tg128）存档展示，同一模型不同量化档谁快一目了然。
- **一键启用**：把模型路径（含 `--mmproj`）回填到参数表单并走既有 Apply——与手填路径完全同构，AppParameters 唯一真源不破；服务在跑时询问「立即重启」；**下载完成的任务行内直接「启用」**（匹配到已下载条目时，行内确认后生效），不用滚去已下载区。
- **设置页「市场」节**：HuggingFace / 魔搭令牌（手填）、下载根目录（默认 `F:\AI_Model`）。

> 设计与实测依据：`docs/spec/model-marketplace.md`；下载引擎选型决策：`docs/adr/0004-self-hosted-gguf-downloader.md`。

### 控件说明

| 类型 | 呈现 | 字段示例 |
|------|------|----------|
| 数值 | 步进数值框（悬停出 ± 步进，可直接键入） | GPU 层数、上下文长度、并发槽、批大小、温度、min-p、线程 |
| 枚举 | 自绘下拉（键盘 ↑↓ / Enter / Esc / Home / End；选项悬停看详解） | 投机解码、KV cache 类型、Flash Attention、监听地址 |
| 开关 | 双态开关（关 = 凹面发丝框，开 = 森林绿实心） | 禁用 mmap / 锁定内存 / 禁用 KV 卸载 / MoE 走 CPU |
| 路径 | 等宽输入框（悬停看全值） | 模型文件、视觉投影 |
| 文本 | 等宽输入框 | 别名、随机种子、端口 |
| 分组 | 14/600 分组标题分节 | 模型与视觉 / 加速 / 上下文与显存 / 并发与吞吐 / 采样 / 网络 / 高级（7 组） |

行名悬停显示对应命令行 flag，取值悬停显示完整值；每个字段与每个选项的详解都来自 Rust 侧的同源文案（与 smoke 契约锁定）。状态呼吸圆点在服务 RUNNING 期间脉动，用户 30s 无交互时自动静止。

### 设置

侧栏「设置」页分四节：**界面**（界面语言（参数详解保持中文）、外观（跟随系统 / 浅色 / 深色）、动效开关）、**字体**（五档界面缩放步条 + UI / 等宽字体族选择）、**更新**（官方 llama.cpp 更新）、**模型市场**（HF / 魔搭令牌、下载根目录）。动效关闭后所有动画瞬时直跳终态，功能不缺失。偏好保存于 `settings.json`（市场令牌与下载根目录也落在这里，随设置持久化）。

### 官方更新（llama.cpp）

设置页「官方更新」区可自动同步 [`ggml-org/llama.cpp`](https://github.com/ggml-org/llama.cpp) 官方最新构建：

- **启动自动检查**（默认开）：后台查询官方 releases，发现新构建时弹窗显示更新日志并提示是否更新；绝不在无确认的情况下下载或安装。
- **二进制版本**：`win-cuda-13.4-x64`（默认）/ `win-cuda-12.4-x64` / `win-cpu-x64` / `win-vulkan-x64`，自动匹配对应官方 zip 资产。（`win-cuda-13.3-x64` 已随官方停发而下线；旧配置里残留的该值会自动回退到默认版本。）
- **立即更新**：二次确认（含备份目录）→ 停止服务 → 下载 zip（已缓存则复用）→ 旧文件备份到 `backup\{tag}\{时间戳}\` → 解压替换 llama.cpp 目录下文件 → 重启服务并确认 RUNNING。
- 全过程日志实时输出；任何一步失败会弹错误框且不会半途替换二进制（逐文件原子替换）。
- 替换目标优先按当前服务 NSSM `AppDirectory` 推导，回退 `LLAMA_CTL_LLAMA_DIR`。
- **自动清理**：每次启动后台清理陈旧下载与备份目录，各保留最近 3 个。只删子目录、绝不动普通文件；失败静默跳过。

### 参数预设

侧栏「预设」页管理，跨服务复用：

- **保存**：分组标题行「保存为预设」→ 弹窗输入名字 → 当前表单值写入 `presets.json`
- **载入**：列表每行「载入」→ 预设值作为表单缓冲带回（不直接写回服务，需再点「应用更改」）；当前载入的预设带标记
- **删除**：列表行「删除」→ 弹窗二次确认
- **自动备份**：表单有未应用更改时切换预设或服务，弹三选（另存并切换 / 放弃 / 取消）；「另存」把当前表单存为「自动备份 月-日 时:分:秒」

### 修复 / 通用化处理

- 原 NSSM 参数含冲突：`-c 4096 --ctx-size 131072`（`-c` 是 `--ctx-size` 别名）。读取弹红色告警并保留最后一项；写回统一为单一 `--ctx-size`。
- 服务名通用：通过 `powershell Get-CimInstance` 列出本机所有 NSSM 服务，顶部下拉切换。
- 滑块型字段若原参数缺失，自动回填 `default`，不输出越界值。
- 负数值参数（如随机种子 `-1`）正确解析为值而非选项 flag（pytest 覆盖）。
- 引号内反斜杠路径按 Windows 引号规则保留字面量（pytest 覆盖）。

### 编码注意

NSSM 输出为 UTF-16LE（`sc` 为本地代码页 GBK）。工具按字节特征自动解码。

### 未应用更改的判定

「未应用更改」提示与「还原」按钮的可用性由 `params.semantically_equal` 判定：两侧各自解析为字段值后比较，因此**别名**（`-ngl` vs `--n-gpu-layers`）、**顺序**、**滑块默认值缺省**、**引号与转义写法**差异都不算改动；数值真差异、复选开关增删、未知参数增删仍会被正确检出。

「应用更改」按钮本身仍按**文本**比较决定是否提示「无变化」：写回是规范化服务参数的动作。

### 构建（exe 输出到根目录）

前置：Node/npm、Rust，以及 `cargo install tauri-cli --version "^2"`。

```powershell
.\build.ps1
```

脚本会：

1. 在 `src-tauri` 运行 `cargo tauri build --ci`；`beforeBuildCommand` 自动构建 `frontend/dist`。
2. 校验新的 `src-tauri\target\release\llama-ctl.exe` 和 NSIS 安装包。
3. 复制到项目根目录并校验非空：
   - `llama-ctl.exe` — 便携版应用
   - `llama-ctl_<version>_x64-setup.exe` — NSIS 安装包（推荐分发）
4. 打印文件名、大小、时间和绝对路径。

Tauri 的中间产物仍在 `src-tauri\target\release`；根目录这两个 exe 是交付入口。构建前请关闭正在运行的 `llama-ctl.exe`，否则 Windows 会锁定待替换的二进制。

开发模式用 `cargo tauri dev`：它会先跑 `beforeDevCommand`（`npm run dev`）起 Vite（默认 `http://localhost:5173`，即 `devUrl`）。

> 本机已验证：`cargo tauri --version` = 2.12.3，`.\build.ps1` 成功产出上述两个根目录文件。

### 测试

```
python -m pytest -q
```

136 个用例，覆盖参数解析、语义等价、i18n、预设读写、NSSM 事实读取（含 0 spawn 断言）、更新安装序列与回滚。Rust 侧另有 `cargo test`（`src-tauri\`）。

### 安全

- 写回 / 重启均弹二次确认，先展示新旧参数对比；不会静默改动服务
- 官方更新：发现新版本只提示 + 展示更新日志；「立即更新」前二次确认，旧二进制先备份再替换；替换 / 重启失败自动从备份回滚并尽力重启服务
- 重启或官方更新进行中关闭窗口会弹确认；强制退出时安装线程为非守护线程，当前替换 / 回滚步骤仍会执行完成
- 开机自启切换弹二次确认，取消即不写入
- 表单有未应用更改时切换服务 / 预设 / 语言 / 外观会先弹确认并支持自动备份
- 工具不持有任何密钥 / token；`api-key` 不在本工具管理范围

### 许可

MIT，见 [LICENSE](LICENSE)。

---

<a id="english"></a>
## English

A general-purpose Windows GUI that directly drives **any** llama.cpp service managed by **NSSM** (defaults to `QwenLLM`, switchable from the top bar). Model-agnostic: works with any GGUF model — Qwen, Llama, DeepSeek, GLM, and more.

### Features

- **Stepped numeric fields** and a **custom dropdown** for enumerated ones (keyboard ↑↓ / Enter / Esc), every field and option carrying a beginner-friendly Chinese guide (hover to read)
- Reads and writes NSSM `AppParameters` directly (fixes the `-c` / `--ctx-size` conflict)
- Start / stop / restart / auto-start toggle, `/healthz` liveness probe, `server.err` log tail
- Write-back and restart both require a second confirmation, after showing an old-vs-new parameter diff
- "Unapplied changes" uses **semantic equivalence**: equivalent parameters produced by legacy setups, hand-editing, or other tools (short names, reordering, omitted defaults) are not falsely flagged as changes
- Parameter presets (local save / load / delete / auto-backup), reusable across services
- **Model market**: a discover → download → fitness → benchmark → one-click-enable loop for GGUF models (ModelScope by default / HuggingFace switchable — see "Model market" below)
- Official llama.cpp updates: check / download / back up / replace / roll back, with confirmation at every step
- Background cleanup of stale update downloads and backups on startup (keeps the latest 3 of each), silent and non-blocking
- Motion and theme: a native "precision instrument" light / dark theme (Segoe UI Variable, a single forest-green interaction hue, hairline layering — see `docs/ui-redesign-v6.md`), button hover fades, view / dialog entrance motion, and a global motion switch (off = every animation jumps to its end state)
- Adaptive log-page polling to keep the footprint low: 1.5s while active, backing off to 3s / 5s when idle, instantly back to 1.5s on new lines (roughly a third of the idle IPC and file reads)
- Bilingual UI chrome in Chinese and English (parameter guides stay Chinese)

### Requirements

- **Windows** (depends on the system `nssm.exe`, `sc`, and `powershell`)
- [NSSM](https://nssm.cc/) installed, with llama.cpp already registered as a service
- Building from source needs Rust ≥ 1.85 (`rust-version` in `src-tauri\Cargo.toml`), Node.js and npm, plus `cargo install tauri-cli` (2.x)

### Install & Use

**Option 1 (recommended): download the released installer**

1. Grab the NSIS installer (`.exe`) from [Releases](https://github.com/xpbobxpseig/llama-ctl/releases)
2. Double-click it. Once installed, no Python or Rust environment is required.

**Option 2: build and run from source**

The desktop app is **Tauri 2 + Vue 3** (`src-tauri\` + `frontend\`); the build entry point is `build.ps1` at the repository root:

```
cd frontend
npm install
cd ..
cd src-tauri
cargo tauri dev        # dev mode: starts the Vite dev server (devUrl http://localhost:5173)
cd ..
.\build.ps1            # package: writes llama-ctl.exe + NSIS installer to the repository root
```

> Requires `cargo install tauri-cli --version "^2"`. On this machine `cargo tauri --version` is 2.12.3; `build.ps1` handles the frontend build, Rust packaging and root copy.

### Changelog

- **v0.2.0 (current)**: new **Model market** view — dual-source GGUF discovery (trending / keyword search / size filter, ModelScope by default with last choice remembered), a self-built streaming download engine (Range resume + `.part` atomic promotion + SHA256 verification, single-task queue, pause / resume / cancel, resume across restarts, disk-space precheck), four-tier hardware fitness rating (DXGI enumeration + physical memory detection, one-line rationale per tier, KV growth noted as not included), one-click `llama-bench` benchmarking (pp512 / tg128 archived; stop service → bench → restore), one-click enable (fills `--model` / `--mmproj` into the form and goes through the existing Apply — AppParameters stays the single source of truth), downloaded-model management (benchmark / enable / open folder / delete, strong warning when deleting the model in use). The Settings page gains a "Market" section (HF / ModelScope tokens, download root). The top-bar "Open install folder" button is wired up (it was permanently disabled before). Spec: `docs/spec/model-marketplace.md`; decision record: `docs/adr/0004-self-hosted-gguf-downloader.md`.
- **v0.1.0**: the desktop app was rewritten from CustomTkinter to **Tauri 2 + Vue 3**, landing the v6 "precision instrument" design system (see `docs/ui-redesign-v6.md`); official llama.cpp downloads now resume interrupted transfers (Range) with retry/backoff and per-entry ZIP CRC validation before promotion; UI chrome is bilingual. Released assets: the [NSIS installer + portable exe](https://github.com/xpbobxpseig/llama-ctl/releases/tag/v0.1.0); SHA256 checksums are in the release notes.

### Environment variables (optional)

The program defaults to the author's local paths. To deploy on another machine, override them via environment variables — no code changes needed:

| Variable | Purpose | Default |
|----------|---------|---------|
| `LLAMA_CTL_NSSM_EXE` | Absolute path to `nssm.exe` | `F:\llama.cpp\nssm\nssm-2.24\win64\nssm.exe` |
| `LLAMA_CTL_SERVICE` | Default service name (initial dropdown selection) | `QwenLLM` |
| `LLAMA_CTL_LLAMA_DIR` | llama.cpp install dir (update replace-target fallback) | `F:\llama.cpp` |
| `LLAMA_CTL_ERR_LOG` | Log-tail fallback path | `F:\llama.cpp\server.err` |
| `LLAMA_CTL_PRESETS` | Presets file | `F:\llama_ctl\presets.json` |
| `LLAMA_CTL_SETTINGS` | Settings file | `F:\llama_ctl\settings.json` |
| `LLAMA_CTL_DOWNLOAD_DIR` | Official-asset download cache | `F:\llama_ctl\downloads` |
| `LLAMA_CTL_BACKUP_DIR` | Old-file backup root | `F:\llama_ctl\backup` |

> Most paths are derived from the current service's NSSM `AppDirectory` at runtime; the environment variables are only a fallback when that derivation fails.

### Model market

The "Market" view at the bottom of the sidebar brings the GGUF acquisition loop into the console (discover → download → fitness → benchmark → enable):

- **Discover**: a trending list (top 50 by downloads, GGUF only) + keyword search + a "Size" dropdown (All / ≥1B / ≥7B / ≥30B; ≥1B by default filters out tiny models). Two switchable sources: ModelScope (default, 8.8× faster CDN in China) / HuggingFace, with the last choice remembered; HF gated repos are badged "Gated".
- **Detail**: files are grouped into quant tiers by filename (main file / shard group / mmproj projector); each tier shows its total size and a **four-tier fitness rating** (Great = fully in VRAM / OK = mostly in VRAM (with an estimated offload ratio) / Slow = mostly system RAM / No = not recommended), each with a one-line rationale (weight-based estimate, KV growth not included). Hardware detection uses DXGI enumeration + physical memory, no subprocesses.
- **Download**: order inline from the tier row; a self-built streaming engine (fully isolated from the service lock — the params page stays usable during a 40 GB download): Range resume, `.part` atomic promotion, SHA256 verification (repos without checksums degrade to size checks, stated explicitly), exponential-backoff retries, a disk-space precheck at enqueue time (insufficient space is rejected up front with the exact gap), a single-task queue, pause / resume / cancel, a persisted task list (resumes from the breakpoint after a restart), inline red failure reasons, and live speed with an **estimated time remaining** on each task row.
- **Downloaded**: scans the download root (two levels deep, both subdirectory and flat layouts); the section head lists GPUs / RAM one device per row plus the free space on the download volume; each row with size / fitness / benchmark scores; actions: benchmark / enable / open folder / delete (deleting the model currently in use raises a strong warning).
- **Benchmark**: with the service running, confirm first, then stop service → `llama-bench -o json` → restore the original state; scores (pp512 / tg128) are archived so you can compare quant tiers of the same model at a glance.
- **One-click enable**: fills the model path (including `--mmproj`) into the parameter form and goes through the existing Apply — identical to typing the path by hand, keeping AppParameters the single source of truth; asks "restart now" when the service is running; **completed task rows offer "Enable" inline** (when a downloaded entry matches, confirmed inline) — no scrolling to the Downloaded section.
- **Settings "Market" section**: HuggingFace / ModelScope tokens (manual entry), download root (default `F:\AI_Model`).

> Design and measured facts: `docs/spec/model-marketplace.md`; download-engine decision: `docs/adr/0004-self-hosted-gguf-downloader.md`.

### Widgets

| Kind | Renderer | Example fields |
|------|----------|----------------|
| Numeric | Stepped value box (hover reveals ± steppers; type directly) | GPU layers, context size, parallel slots, batch size, temperature, min-p, threads |
| Enum | Custom dropdown (keyboard ↑↓ / Enter / Esc / Home / End; hover an option for its guide) | Speculative decoding, KV cache type, Flash Attention, listen address |
| Switch | Two-state toggle (off = inset hairline, on = solid forest green) | Disable mmap / lock memory / disable KV offload / MoE on CPU |
| Path | Monospace input (hover for the full value) | Model file, vision projector |
| Text | Monospace input | Alias, random seed, port |
| Group | 14/600 section headings | Model & Vision / Acceleration / Context & VRAM / Concurrency / Sampling / Network / Advanced (7 groups) |

Hovering a row name shows the command-line flag; hovering a value shows the full text. Every field's and every option's guide comes from the same source text as the Rust side (locked by the smoke contract). The breathing status dot pulses while the service is RUNNING and freezes after 30s without interaction.

### Settings

The "Settings" page in the sidebar has four sections: **Interface** (UI language (parameter guides stay Chinese), appearance (follow system / light / dark), the motion switch), **Fonts** (a 5-stop UI-scale stepper + UI / monospace family pickers), **Updates** (official llama.cpp updates), and **Model market** (HF / ModelScope tokens, download root). With motion off, all animations jump straight to their end state without losing any functionality. Preferences are stored in `settings.json` (market tokens and the download root persist there too).

### Official updates (llama.cpp)

The Settings page's "Official updates" section syncs the latest builds from [`ggml-org/llama.cpp`](https://github.com/ggml-org/llama.cpp):

- **Auto-check on startup** (on by default): queries official releases in the background; when a new build appears it shows the changelog and asks whether to update. It never downloads or installs without confirmation.
- **Build variant**: `win-cuda-13.4-x64` (default) / `win-cuda-12.4-x64` / `win-cpu-x64` / `win-vulkan-x64`, matched to the corresponding official zip asset. (`win-cuda-13.3-x64` was retired once upstream stopped publishing it; a stale value in an old config falls back to the default automatically.)
- **Update now**: second confirmation (including the backup directory) → stop service → download zip (reused if cached) → back up old files to `backup\{tag}\{timestamp}\` → unzip over the llama.cpp directory → restart the service and confirm RUNNING.
- Full progress is logged live; any failure pops an error dialog and never leaves binaries half-replaced (atomic per-file replace).
- The replace target is derived from the current service's NSSM `AppDirectory`, falling back to `LLAMA_CTL_LLAMA_DIR`.
- **Auto-cleanup**: stale download and backup directories are purged in the background on startup, keeping the latest 3 of each. Only subdirectories are removed, never plain files; failures are skipped silently.

### Presets

Managed on the "Presets" page in the sidebar, reusable across services:

- **Save**: the "Save as preset" button in the section heading → type a name in the dialog → the form's values are written to `presets.json`.
- **Load**: "Load" on any list row → the preset's values land in the form buffer (they are **not** written back to the service; click "Apply changes" for that). The currently loaded preset is marked.
- **Delete**: "Delete" on a list row → a confirmation dialog.
- **Auto-backup**: switching preset or service with unapplied changes offers three choices (back up & switch / discard / cancel); "back up" saves the current form as "Auto backup MM-DD HH:MM:SS".

### Fixes / generalization

- A conflicting original NSSM parameter set (`-c 4096 --ctx-size 131072`, `-c` being an alias of `--ctx-size`) raises a red warning and keeps the last value; write-back normalizes it to a single `--ctx-size`.
- Generic service names: all local NSSM services are listed via `powershell Get-CimInstance` and switchable from the top bar.
- Slider fields missing from the original parameters are backfilled with their `default`; out-of-range values are never emitted.
- Negative numeric parameters (e.g. random seed `-1`) parse as values rather than option flags (covered by pytest).
- Backslash paths inside quotes keep their literal form per Windows quoting rules (covered by pytest).

### Encoding note

NSSM emits UTF-16LE (while `sc` uses the local code page, GBK). The tool auto-detects the encoding from byte characteristics.

### How "unapplied changes" is decided

The "unapplied changes" hint and the "Revert" button's availability are decided by `params.semantically_equal`: both sides are parsed into field values and then compared, so **aliases** (`-ngl` vs `--n-gpu-layers`), **ordering**, **omitted slider defaults**, and **quoting / escaping style** are not treated as changes. Genuine numeric differences, added or removed checkboxes, and added or removed unknown parameters are still detected.

The "Apply changes" button itself still compares **textually** when deciding whether to warn "no change", because writing back normalizes the service parameters.

### Build (exe output in the repository root)

Prerequisites: Node/npm, Rust, and `cargo install tauri-cli --version "^2"`.

```powershell
.\build.ps1
```

The script:

1. Runs `cargo tauri build --ci` in `src-tauri`; `beforeBuildCommand` builds `frontend/dist` automatically.
2. Verifies the new `src-tauri\target\release\llama-ctl.exe` and NSIS setup.
3. Copies both to the repository root and checks they are non-empty:
   - `llama-ctl.exe` — portable app
   - `llama-ctl_<version>_x64-setup.exe` — NSIS installer (recommended for distribution)
4. Prints name, size, timestamp and absolute paths.

Tauri intermediates stay under `src-tauri\target\release`; the two root exes are the supported deliverables. Close any running `llama-ctl.exe` before building, otherwise Windows locks the binary being replaced.

For development, `cargo tauri dev` runs `beforeDevCommand` (`npm run dev`) and starts Vite (`http://localhost:5173`, the configured `devUrl`).

> Verified on this machine: `cargo tauri --version` is 2.12.3, and `.\build.ps1` produced both root deliverables.

### Test

```
python -m pytest -q
```

136 test cases covering parameter parsing, semantic equivalence, i18n, preset read/write, NSSM fact reads (including a zero-spawn assertion), the update-install sequence and rollback. The Rust side has its own `cargo test` (in `src-tauri\`).

### Security

- Write-back and restart both require a second confirmation and show an old-vs-new diff first; the service is never modified silently.
- Official updates: a new version only raises a prompt plus the changelog; "Update now" asks for a second confirmation, and old binaries are backed up before replacement. A failed replace / restart rolls back from the backup and best-effort restarts the service.
- Closing the window during a restart or official update asks for confirmation; if you force-quit, the install thread is non-daemon so the current replace / rollback step still completes.
- Toggling auto-start also asks for a second confirmation; cancelling writes nothing.
- Switching service / preset / language / appearance with unapplied form changes asks for confirmation and offers an auto-backup.
- The tool holds no secrets or tokens; `api-key` is out of scope.

### License

MIT, see [LICENSE](LICENSE).

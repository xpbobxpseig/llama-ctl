# llama.cpp Service Console (llama_ctl)

[中文](#中文说明) | [English](#english)

---

<a id="中文说明"></a>
## 中文说明

通用 Windows GUI，直接接管由 **NSSM** 管理的**任意** llama.cpp 服务（默认 `QwenLLM`，顶部可切换）。模型无关：Qwen / Llama / DeepSeek / GLM 等任意 GGUF 模型均可。

### 功能

- 数值参数用**滑块**、枚举参数用**下拉**，每项带「?」按钮给出初学者友好的中文解释
- 直接读写 NSSM `AppParameters`（修掉 `-c` 与 `--ctx-size` 冲突）
- 启停 / 重启 / 开机自启切换、`/healthz` 探活、`server.err` 日志尾随
- 写回 / 重启均二次确认，先展示新旧参数对比
- 「未应用更改」用**语义等价**判定：历史遗留 / 手写 / 其他工具生成的等价参数（短名、乱序、缺省默认值）不会被误报为改动
- 参数预设（本地保存 / 加载 / 删除 / 自动备份），跨服务复用
- 官方 llama.cpp 更新：检查 / 下载 / 备份 / 替换 / 回滚，全程需确认
- 启动时后台清理官方更新的陈旧下载与备份（各保留最近 3 个），无确认、不打扰
- 动效与主题：Apple 风浅 / 深双主题、状态呼吸圆点（30s 无交互自动静止）、按钮驻留高亮 + 0.8s 指数渐隐、`?` 提示框淡入渐隐、可折叠参数分组、动效总开关
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

桌面端是 **Tauri 2 + Vue 3** 应用（`src-tauri\` + `frontend\`），构建入口是 `cargo tauri`：

```
cd frontend
npm install
npm run build          # 产出 frontend\dist，即 tauri.conf.json 的 frontendDist

cd ..\src-tauri
cargo tauri dev        # 开发模式：自动起 Vite dev server（devUrl http://localhost:5173）
cargo tauri build      # 打包：产出 NSIS 安装包（bundle.targets = ["nsis"]）
```

> 需要先 `cargo install tauri-cli --version "^2"`；本机尚未安装（`cargo tauri --version` 报 no such command），因此上述命令本节未实际跑通验证。

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

### 控件说明

| 类型 | 呈现 | 字段示例 |
|------|------|----------|
| 滑块 | `CTkSlider` + 实时数值 | GPU 层数、上下文长度、并发槽、批大小、温度、min-p、线程 |
| 下拉 | `CTkOptionMenu`（预设名为可编辑 `CTkComboBox`） | 投机解码、KV cache 类型、Flash Attention、监听地址 |
| 复选 | `CTkCheckBox` | 禁用 mmap / 锁定内存 / 禁用 KV 卸载 / MoE 走 CPU |
| 文件 | `CTkEntry` + 浏览按钮 | 模型文件、视觉投影 |
| 文本 | `CTkEntry` | 别名、随机种子、端口 |
| 分组 | 可折叠面板 | 模型与视觉 / 加速 / 上下文与显存 / 并发与吞吐 / 采样 / 网络 / 高级（7 组，默认展开前两组） |

每个参数右侧有「?」按钮，点开看该参数对**性能 / 效果**的影响与适用场景；下拉项切换时会显示当前选项的解释。悬停「?」约 300ms 后提示框 200ms 淡入（快速扫过不触发）；移开后 0.8s 指数渐隐消失（离得越远越快），渐隐途中移回立即恢复；同一时刻只显示一个提示。按钮 hover 100ms 平滑到高亮并驻留，移出 0.8s 指数渐隐回常态。状态呼吸圆点在服务 RUNNING 期间脉动，用户 30s 无交互时自动静止。参数区 7 个分组可折叠，默认展开前两组，展开状态在切换语言 / 主题后保留。

### 设置

顶部「设置」按钮打开设置页，含界面语言（参数详解保持中文）、外观（跟随系统 / 浅色 / 深色）、动效开关，以及官方更新区。动效关闭后所有动画瞬时直跳终态，功能不缺失。偏好保存于 `settings.json`（默认 `motion_enabled: true`）。

### 官方更新（llama.cpp）

设置页「官方更新」区可自动同步 [`ggml-org/llama.cpp`](https://github.com/ggml-org/llama.cpp) 官方最新构建：

- **启动自动检查**（默认开）：后台查询官方 releases，发现新构建时弹窗显示更新日志并提示是否更新；绝不在无确认的情况下下载或安装。
- **二进制版本**：`win-cuda-13.4-x64`（默认）/ `win-cuda-12.4-x64` / `win-cpu-x64` / `win-vulkan-x64`，自动匹配对应官方 zip 资产。（`win-cuda-13.3-x64` 已随官方停发而下线；旧配置里残留的该值会自动回退到默认版本。）
- **立即更新**：二次确认（含备份目录）→ 停止服务 → 下载 zip（已缓存则复用）→ 旧文件备份到 `backup\{tag}\{时间戳}\` → 解压替换 llama.cpp 目录下文件 → 重启服务并确认 RUNNING。
- 全过程日志实时输出；任何一步失败会弹错误框且不会半途替换二进制（逐文件原子替换）。
- 替换目标优先按当前服务 NSSM `AppDirectory` 推导，回退 `LLAMA_CTL_LLAMA_DIR`。
- **自动清理**：每次启动后台清理陈旧下载与备份目录，各保留最近 3 个。只删子目录、绝不动普通文件；失败静默跳过。

### 参数预设

把当前整套参数存为命名预设，跨服务复用。预设名是可编辑下拉框（输入与选择合一）：

- **保存**：输入新名字 → 回车或失焦，表单值写入 `presets.json`；名字已存在则不动作（避免误覆盖）
- **载入**：下拉选已有预设 → **即选即载**入表单（不直接写回服务，需再点「应用更改」）
- **应用同步**：写回成功后，若下拉框当前是已存在的预设名，表单值同步覆盖该预设
- **删除**：选中预设 → 点右侧垃圾桶图标（二次确认）
- **自动备份**：表单有未应用更改时切换预设或服务，先弹确认；确认后自动存为「自动备份 月-日 时:分:秒」

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

### 构建

```
cd frontend && npm install && npm run build
cd ..\src-tauri && cargo tauri build
```

`cargo tauri build` 会先跑 `beforeBuildCommand`（`npm run build`）再编译 Rust，并按 `src-tauri\tauri.conf.json` 的 `bundle.targets = ["nsis"]` 产出 NSIS 安装包（简体中文 + 英文语言选择，`installMode: both`）。产物落在 `src-tauri\target\release\bundle\nsis\`。

开发模式用 `cargo tauri dev`：它会先跑 `beforeDevCommand`（`npm run dev`）起 Vite（默认 `http://localhost:5173`，即 `devUrl`）。

先决条件：`cargo install tauri-cli --version "^2"`。

> **本机构建状态**：`cargo tauri` 未安装（`cargo tauri --version` 报 no such command），所以上述构建命令**尚未在本机实际跑通**，产物路径是按 `tauri.conf.json` 推导的、未经实测。本机 `src-tauri\target\` 下目前只有 debug 产物，没有 NSIS 包。

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

- **Sliders** for numeric parameters and **dropdowns** for enumerated ones, each with a `?` button giving a beginner-friendly Chinese explanation
- Reads and writes NSSM `AppParameters` directly (fixes the `-c` / `--ctx-size` conflict)
- Start / stop / restart / auto-start toggle, `/healthz` liveness probe, `server.err` log tail
- Write-back and restart both require a second confirmation, after showing an old-vs-new parameter diff
- "Unapplied changes" uses **semantic equivalence**: equivalent parameters produced by legacy setups, hand-editing, or other tools (short names, reordering, omitted defaults) are not falsely flagged as changes
- Parameter presets (local save / load / delete / auto-backup), reusable across services
- Official llama.cpp updates: check / download / back up / replace / roll back, with confirmation at every step
- Background cleanup of stale update downloads and backups on startup (keeps the latest 3 of each), silent and non-blocking
- Motion and theme: Apple-style light / dark themes, breathing status dot (freezes after 30s idle), button hover highlight with 0.8s exponential fade, `?` tooltip fade-in / fade-out, collapsible parameter groups, global motion switch
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

The desktop app is **Tauri 2 + Vue 3** (`src-tauri\` + `frontend\`); the build entry point is `cargo tauri`:

```
cd frontend
npm install
npm run build          # emits frontend\dist, i.e. frontendDist in tauri.conf.json

cd ..\src-tauri
cargo tauri dev        # dev mode: starts the Vite dev server (devUrl http://localhost:5173)
cargo tauri build      # package: emits an NSIS installer (bundle.targets = ["nsis"])
```

> Requires `cargo install tauri-cli --version "^2"` first; it is not installed on this machine (`cargo tauri --version` reports "no such command"), so the commands above have not actually been run and verified here.

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

### Widgets

| Kind | Renderer | Example fields |
|------|----------|----------------|
| Slider | `CTkSlider` + live value | GPU layers, context size, parallel slots, batch size, temperature, min-p, threads |
| Dropdown | `CTkOptionMenu` (preset name is an editable `CTkComboBox`) | Speculative decoding, KV cache type, Flash Attention, listen address |
| Checkbox | `CTkCheckBox` | Disable mmap / lock memory / disable KV offload / MoE on CPU |
| File | `CTkEntry` + browse button | Model file, vision projector |
| Text | `CTkEntry` | Alias, random seed, port |
| Group | Collapsible panel | Model & Vision / Acceleration / Context & VRAM / Concurrency / Sampling / Network / Advanced (7 groups, first two expanded by default) |

Every parameter has a `?` button explaining its impact on **performance / quality** and when to use it; switching a dropdown option shows the explanation for the current choice. Hovering `?` for ~300ms fades the tooltip in over 200ms (a quick pass does not trigger it); moving away fades it out over 0.8s exponentially (faster the further away), and moving back during the fade restores it immediately. Only one tooltip shows at a time. Buttons ease to their highlight in 100ms and hold it, fading back over 0.8s after the pointer leaves. The breathing status dot pulses while the service is RUNNING and freezes after 30s without interaction. The 7 parameter groups collapse independently; expansion state survives language / theme changes.

### Settings

The top-bar "Settings" button opens a page with UI language (parameter guides stay Chinese), appearance (follow system / light / dark), the motion switch, and the official-update section. With motion off, all animations jump straight to their end state without losing any functionality. Preferences are stored in `settings.json` (default `motion_enabled: true`).

### Official updates (llama.cpp)

The Settings page's "Official updates" section syncs the latest builds from [`ggml-org/llama.cpp`](https://github.com/ggml-org/llama.cpp):

- **Auto-check on startup** (on by default): queries official releases in the background; when a new build appears it shows the changelog and asks whether to update. It never downloads or installs without confirmation.
- **Build variant**: `win-cuda-13.4-x64` (default) / `win-cuda-12.4-x64` / `win-cpu-x64` / `win-vulkan-x64`, matched to the corresponding official zip asset. (`win-cuda-13.3-x64` was retired once upstream stopped publishing it; a stale value in an old config falls back to the default automatically.)
- **Update now**: second confirmation (including the backup directory) → stop service → download zip (reused if cached) → back up old files to `backup\{tag}\{timestamp}\` → unzip over the llama.cpp directory → restart the service and confirm RUNNING.
- Full progress is logged live; any failure pops an error dialog and never leaves binaries half-replaced (atomic per-file replace).
- The replace target is derived from the current service's NSSM `AppDirectory`, falling back to `LLAMA_CTL_LLAMA_DIR`.
- **Auto-cleanup**: stale download and backup directories are purged in the background on startup, keeping the latest 3 of each. Only subdirectories are removed, never plain files; failures are skipped silently.

### Presets

Save the current parameter set as a named preset and reuse it across services. The preset name is an editable dropdown (input and selection in one):

- **Save**: type a new name → press Enter or blur; the form's values are written to `presets.json`. An existing name is a no-op (avoids accidental overwrite).
- **Load**: pick an existing preset → values load into the form immediately (they are **not** written back to the service; click "Apply changes" for that).
- **Apply sync**: after a successful write-back, if the dropdown currently holds an existing preset name, the form values overwrite that preset.
- **Delete**: select a preset → click the trash icon on the right (second confirmation).
- **Auto-backup**: switching preset or service with unapplied changes asks for confirmation first, then saves the current form as "Auto backup MM-DD HH:MM:SS".

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

### Build

```
cd frontend && npm install && npm run build
cd ..\src-tauri && cargo tauri build
```

`cargo tauri build` runs `beforeBuildCommand` (`npm run build`) first, then compiles Rust, and emits an NSIS installer per `bundle.targets = ["nsis"]` in `src-tauri\tauri.conf.json` (Simplified Chinese + English language selector, `installMode: both`). Output lands in `src-tauri\target\release\bundle\nsis\`.

For development, `cargo tauri dev` runs `beforeDevCommand` (`npm run dev`) and starts Vite (`http://localhost:5173`, the configured `devUrl`).

Prerequisite: `cargo install tauri-cli --version "^2"`.

> **Status on this machine**: `cargo tauri` is not installed (`cargo tauri --version` reports "no such command"), so these build commands have **not actually been run here**; the output path is derived from `tauri.conf.json` and is unverified. `src-tauri\target\` currently holds only debug artifacts — there is no NSIS bundle.

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

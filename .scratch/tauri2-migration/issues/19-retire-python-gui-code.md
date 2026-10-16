# 19: 退役 Python 侧已废弃代码

**What to build:** 删除 Python 版中已被取代的部分：手写动画引擎、手写 SVG 光栅化器、图标生成脚本，以及它们的测试。同时停掉 PyInstaller 构建产物相关说明，README 指向新的构建方式。用户视角：仓库里不再有两套并存的 GUI 实现，不会改错地方。

删除而非迁移是本次重写最大的单项收益（GUI 侧基础设施约 1351 行 + 相关测试 993 行）。但必须等 Tauri 版功能齐备才能删——这一票排在所有前端票之后。

**Blocked by:** 13, 14, 15, 16, 17, 18

**Status:** ready-for-agent

- [ ] 删除手写动画引擎（326 行）与其测试（444 行）—— 已由 CSS 过渡取代
- [ ] 删除手写 SVG 路径光栅化器（335 行）—— 已由内联 SVG 取代
- [ ] 删除图标生成脚本（442 行）与其测试（239 + 146 行）—— 已由静态 SVG 资源取代
- [ ] 删除首帧渲染与字体令牌测试（61 + 103 行）—— 被测对象已不存在
- [ ] 保留领域层 Python 代码与测试直到 Tauri 版发布验证完成（本票不删领域层）
- [ ] README 更新：构建方式、环境要求、分发形态按 Tauri 版重写
- [ ] 构建脚本更新：NSIS 构建入口取代 PyInstaller 入口
- [ ] 删除后 `pytest` 与 `cargo test` 均通过（剩余 Python 测试仍覆盖领域层）
- [ ] 确认无残留的 CDN 引用或远程加载（ADR-0001 的最后一道检查）

## Resolution

安全提交 `71c2da7` 已确认存在且覆盖全部待删文件（原为未跟踪，删除不可恢复）。以下 9 个文件已用 `git rm` 删除并暂存（未提交）：

| 文件 | 行数(@71c2da7) |
|------|---------------|
| `motion.py` | 275 |
| `svgpath.py` | 299 |
| `icon.py` | 100 |
| `make_icon.py` | 177 |
| `make_icons.py` | 193 |
| `tests/test_motion.py` | 333 |
| `tests/test_font_tokens.py` | 74 |
| `tests/test_icon.py` | 193 |
| `tests/test_icons_assets.py` | 109 |

### pytest 结果（诚实报告：未通过）

- 删除前基线：`273 passed`
- 删除后：**收集阶段即中断**，`2 errors during collection`，**0 个用例执行**
  - `tests/test_first_paint.py` → `llama_ctl_gui.py:34: ModuleNotFoundError: No module named 'motion'`
  - `tests/test_preset_safety.py` → 同上

根因：`llama_ctl_gui.py` L34 `from motion import ...`、L39 `import icon as ic` 仍依赖被删模块。这两个测试文件用假 self 调 `ControlGUI` 的未绑定方法，因此 import 链路必经 `llama_ctl_gui`。

**这是本票删除动作直接造成的，不是预先存在的失败。** 验证方式：把 `motion.py` / `icon.py` 从 `71c2da7` 还原回工作区后 `pytest -q` 即恢复为 `158 passed`；再次删除后立即回到收集错误。

未修复原因：修复只有两条路，都超出本票授权范围——
1. 改 `llama_ctl_gui.py`（拆掉 motion/icon 依赖）——该文件是用户**未提交**的改动，明确禁止触碰；
2. 删 `tests/test_first_paint.py` / `tests/test_preset_safety.py`——不在授权删除清单内。

`tests/test_first_paint.py` 是跟踪文件，`tests/test_preset_safety.py` 是用户未跟踪的新文件。**需主 agent 决定**：给本票追加授权删这两个文件，或另开票处理 `llama_ctl_gui.py` 的 GUI 依赖剥离。

排除这两个文件后领域层测试全绿：

```
pytest -q --ignore=tests/test_first_paint.py --ignore=tests/test_preset_safety.py
→ 136 passed
```

（136 = test_installer 16 + test_nssm_facts 6 + test_params 39 + test_presets 12 + test_strings 10 + test_updater 42 + test_user_data_dir 11。注：README 旧写的「157 个用例」本就与实际数 273 不符，已按实测改为 136。）

删除的用例数：273 − 136 = 137（含上述 2 个收集错误文件的 22 个：first_paint 6 + preset_safety 16）。

### README.md

中英两版同步改写：

- 环境要求：删「无需 Python」，改为 Rust ≥ 1.85（`src-tauri\Cargo.toml` 的 `rust-version`）+ Node/npm + `cargo install tauri-cli` (2.x)
- 安装与使用：方式一改为下载 NSIS 安装包；方式二改为 `frontend` 下 `npm install && npm run build`，`src-tauri` 下 `cargo tauri build` / `cargo tauri dev`
- 构建：删除 `pwsh -File build.ps1` 与 `python -m PyInstaller llama_ctl.spec`，改为 Tauri 命令；`bundle.targets = ["nsis"]`、产物 `src-tauri\target\release\bundle\nsis\`、devUrl `http://localhost:5173`
- 测试：157 → 136，去掉「动效引擎」「首帧渲染」，补 Rust 侧 `cargo test`

**未验证处已显式标注**：`cargo tauri` 本机未安装（`cargo tauri --version` → `no such command`），故构建命令**未实跑**；产物路径按 `tauri.conf.json` 推导，标为未经实测；`src-tauri\target\` 现只有 debug 产物、无 NSIS 包。不编造「窗口打开」等未验证断言。

### build.ps1

原脚本不按名引用被删文件，但整支是 PyInstaller 流程（`llama_ctl.spec`），已按「注明被取代」处理：替换为一段说明 + `exit 1`，指向 README 的 `cargo tauri build`，不留旧流程误跑的可能。已做 PowerShell 语法检查（无解析错误）。

### 残留检查

- 无 CDN / 远程加载残留：`frontend\index.html` 的图标是 `data:image/svg+xml` 内联；`tauri.conf.json` 的 CSP 为 `default-src 'self'`，只允许 `asset:` / `ipc:` / `data:`；frontend 源码里唯一的 `http://` 是用户可见文案，非资源加载。

### 未提交

按约束未 commit。9 个删除已 `git rm` 暂存；用户未提交的改动（installer.py、params.py、updater.py、llama_ctl_gui.py、llama_ctl.spec、llama_icon.ico、strings.py、src-tauri/*、tests/test_*.py 等）全部原样保留，未 stage / commit / revert / 重格式化。

# 00: 把 settings.json / presets.json 迁到用户目录

**What to build:** 在 Python 侧就把工具偏好的存放位置从程序侧固定路径迁到 Windows 用户目录（`%APPDATA%\llama-ctl\` 或等价位置），并让旧路径上的既有文件在首次启动时自动迁移过去。用户视角：升级到新版本后预设与偏好还在，不需要手动拷贝。

这是 ADR-0002 的必需配套（NSIS 覆盖安装会清掉安装目录下的用户数据），但先在 Python 侧完成有两个额外好处：Python 版与 Rust 版从此共用同一位置，用户可以在两版之间来回切换而不丢预设；老用户的数据迁移路径在 Rust 化之前就被真实验证过一次，而不是埋进 Rust 票里第一次才跑。

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [x] 偏好与预设的存放位置改为用户目录，路径不再依赖程序安装位置
- [x] 首次启动时若用户目录无文件、旧路径有文件，自动迁移过去并保留旧文件（不删除）
- [x] 迁移后旧路径文件不再被读取；两处同时存在时以用户目录为准
- [x] 环境变量覆盖仍然生效（`LLAMA_CTL_SETTINGS` / `LLAMA_CTL_PRESETS`），优先级不变
- [x] 原子写（临时文件 + rename）行为不变
- [x] 文件损坏时逐项回退默认值的行为不变
- [x] 现有预设相关测试全部通过（`test_presets.py` / `test_preset_safety.py`），并新增覆盖迁移路径与环境变量优先级的用例
- [x] 判定「用户目录」的逻辑不写死某一套 Windows API，便于 Rust 侧照搬

## Resolution

**路径约定（Rust 侧照搬，勿改）：**

```
%APPDATA%\llama-ctl\settings.json
%APPDATA%\llama-ctl\presets.json
```

即：取环境变量 `APPDATA`，拼子目录 `llama-ctl`（常量 `USER_DATA_DIRNAME = "llama-ctl"`），
再拼文件名（`SETTINGS_BASENAME` / `PRESETS_BASENAME`）。`APPDATA` 缺失时退回
`%USERPROFILE%\AppData\Roaming\llama-ctl`。**只用环境变量判定，不调用任何 Windows
API**（Rust 侧 `std::env::var("APPDATA")` 即可等价实现）。

**函数名（两个模块各一份，同名同义）：**

| 模块 | 函数 | 作用 |
| --- | --- | --- |
| `settings.py` / `presets.py` | `user_data_dir()` | 返回 `%APPDATA%\llama-ctl` |
| `settings.py` | `resolve_settings_file()` | 返回 settings.json 最终路径 |
| `presets.py` | `resolve_presets_file()` | 返回 presets.json 最终路径 |
| 同上（各模块私有） | `_migrate_legacy_file(legacy, target)` | 迁移单个文件 |

模块导入时各自算一次，结果仍是模块级常量 `SETTINGS_FILE` / `PRESETS_FILE`（调用方无感）。

**优先级（与 07 的「环境变量覆盖优先级与 Python 版一致」对齐）：**

1. `LLAMA_CTL_SETTINGS` / `LLAMA_CTL_PRESETS` 有值 → 直接用它，**完全不走用户目录，也不做迁移**；
2. 否则 → 用户目录路径。

**迁移规则（首次启动，在 resolve 时执行）：**

- 条件：用户目录文件**不存在** 且 旧路径文件是普通文件；
- 动作：`shutil.copy2(legacy, target)`（父目录 `makedirs(exist_ok=True)`）；
- **旧文件不删除**；
- 两处同时存在 → 不动任何文件，读写的都是用户目录那份（旧文件此后不再被读取）；
- 迁移失败（目录不可建等）一律静默，不得让首次启动报错。

旧路径（仅作迁移来源，常量名 `LEGACY_SETTINGS_FILE` / `LEGACY_PRESETS_FILE`）：
`F:\llama_ctl\settings.json`、`F:\llama_ctl\presets.json`。

**未改动的行为**：原子写（`.tmp` + `os.replace`）、损坏时逐项回退默认值、写入失败返回
`(False, err)` 而不抛异常 —— 均保持原样。

# 07: presets 与 settings 的 Rust 持久化

**What to build:** 把预设与偏好的持久化移植到 Rust，读的位置与 00 在 Python 侧定下的用户目录一致。用户视角：预设跨服务复用，偏好在重启后保留，文件损坏时不会清空全部设置。

**Blocked by:** 01, 00

**Status:** ready-for-agent

- [x] 存放位置与 00 定下的用户目录一致，Python 版与 Rust 版共用同一位置
- [x] 写入是原子写（临时文件 + rename）
- [x] 文件损坏时逐项回退默认值，而不是整体丢弃
- [x] 写入失败返回错误而非 panic（目录只读时用户能看到提示）
- [x] Preset 保存时同名已存在为 no-op，不误覆盖
- [x] Preset 载入只填表单、不写服务
- [x] 环境变量覆盖优先级与 Python 版一致
- [x] 迁移现有测试：`test_presets.py` 128 行 + `test_preset_safety.py` 247 行

## Resolution

模块：`src-tauri/core/src/persist.rs`（`pub mod persist`），测试：`tests/ticket07_persist.rs`（23 例，全过；`cargo test` 全 crate 119 例通过）。
所有文件访问都经 `&impl Deps`，测试用 `FakeDeps`，不碰真实磁盘。

**照搬的路径约定（与 00 完全一致，未改）：**

```
%APPDATA%\llama-ctl\settings.json
%APPDATA%\llama-ctl\presets.json
```

`std::env::var("APPDATA")` → 拼 `USER_DATA_DIRNAME = "llama-ctl"` → 拼文件名
（`SETTINGS_BASENAME` / `PRESETS_BASENAME`）；`APPDATA` 缺失时退回
`%USERPROFILE%\AppData\Roaming\llama-ctl`。**未调用任何 Windows API**。

**优先级（与 Python 一致）：** `LLAMA_CTL_SETTINGS` / `LLAMA_CTL_PRESETS` 有值 →
直接用它，完全不走用户目录；否则 → 用户目录。空字符串按「未设置」处理
（对应 Python `os.environ.get()` 的假值）。

**与 Python 版相同：** 原子写（`<file>.tmp` + `rename_file`，失败时删除 tmp）；
损坏/缺文件逐项回退默认值而非整体丢弃；写入失败返回 `AppError`
（`StorageFailed`，携带可显示原因）而非 panic；同名预设保存为 no-op。

**与 Python 版的差异：**

1. **路径解析改为显式传参**：`Env { appdata, userprofile, settings_override,
   presets_override }` 由调用方传入（生产环境用 `Env::from_process()`）。Python 在
   import 时把路径算成模块级常量 `SETTINGS_FILE` / `PRESETS_FILE`；Rust 侧没有
   模块级可变状态，且进程环境变量是全局的（并行 `cargo test` 下互相干扰），
   故不做模块级缓存——每次调用都现算（纯函数，开销可忽略）。
2. **不实现 00 的 `_migrate_legacy_file`（旧路径迁移）**：迁移是 Python 侧首次启动
   的一次性动作，00 已完成并已在真实用户上跑过；Rust 侧只需读写同一位置。若
   日后确需（Rust 侧首次启动且用户目录为空），另行开票，勿在此处补。
3. **JSON 用自带的极简解析器**（`serde_json` 只是 dev-dependency；
   `presets.json` 是用户可手改的任意 name→values 映射，本就没有固定结构）。
   递归深度上限 64 防恶意文件爆栈。输出与 Python 一致：缩进 2、`ensure_ascii=false`。
   若将来需要更多 JSON 能力，把 `serde_json` 提为正式依赖并删掉该段即可。
4. **设置项是强类型 struct** `Settings`，而非 Python 的 `dict` + `DEFAULTS`：
   类型不符的键回退默认（与 Python 语义等价），但字段不会再凭空增减。
   `services` 里非字符串的元素被丢弃（Python 原样保留任意列表）。
5. **预设值统一为字符串** `BTreeMap<String, String>`（Python 的 values 字典值可能是
   任意 JSON 类型）；非字符串的值在读入时被跳过。与 GUI `_collect()` 的产出一致。
6. **返回值形态**：Python 是 `(ok, err)` 元组，Rust 是 `Result<(), AppError>`
   （`save_preset` / `delete_preset` 返回 `Result<bool, AppError>`，`false` = no-op
   且未落盘）。
7. **Preset 载入拆成两步**：`load_preset_values()` 只返回要填进表单的值（纯读文件），
   写服务由调用方决定——使「载入只填表单、不写服务」这条判据可被单测直接钉住
   （断言零 spawn、零写入）。
8. **未迁移** `test_preset_safety.py` 里依赖 Tk 控件与 `ControlGUI` 方法的那部分
   （取消切服务、下拉回滚、已销毁控件不抛异常等）——那是 08 之后 GUI 层的活，
   不属于持久化。

**未发现的 `Deps` 缺口**：`read_file` / `write_file` / `rename_file` /
`remove_file` / `create_dir_all` 已足够；唯一缺的是「文件是否存在 / 是否是普通文件」
的探针（`os.path.exists` / `os.path.isfile`），但本模块靠 `read_file` 的
`Err(FileRead)` 即可等价判定（Python 侧也只用返回值区分），故未需要新增。
（00 的迁移逻辑若要移植才需要该探针，见差异 2。）

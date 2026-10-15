# 11: tauri command 层与 Snapshot IPC

**What to build:** 把全部领域能力暴露为 tauri command，并定义 Snapshot 的 IPC 契约：Rust 持真源，前端按需拉取全量快照，单向、无状态竞争。用户视角：界面上看到的永远与真实服务状态一致，不会出现「界面显示已应用但服务没变」这类不一致。

单向是刻意的选择。现有 Python 版是前后端双份状态双向同步，「未应用更改」只能靠语义等价比较来打补丁；单向快照让这类一致性 bug 结构性消失。

**Blocked by:** 03, 04, 07, 10

**Status:** ready-for-agent

- [x] 每个领域操作有一个 command：读快照、应用更改、还原、启停、重启、切自启、预设增删载、更新检查与安装
- [x] Snapshot 包含前端渲染一屏所需的全部状态，前端不需要二次拉取
- [x] 命令返回结构化错误，前端能直接展示
- [x] 长时间操作（更新、重启）的进度能持续推送给前端
- [x] 前端不持有权威状态，只在编辑期暂存表单值
- [x] command 层可测：注入 `Deps` 假实现后能跑完整调用
- [x] IPC 边界的类型在两端一致（Rust serde 形状 = 前端消费形状）

## Resolution

### 布局

三个 crate，领域层（票 01-10）一个字节未改：

| 路径 | 角色 |
|---|---|
| `src-tauri/core/` | 领域层（已封版，本票未动 `src/`） |
| `src-tauri/commands/` | **新** `llama-ctl-commands`：Snapshot 契约 + 全部领域操作 + Field 表 + IPC 信封 |
| `src-tauri/` | **新** `llama-ctl`：tauri 外壳（build.rs / lib.rs / main.rs / commands.rs / tauri.conf.json） |
| `frontend/` | 占位前端（票 12 用 Vue 3 替换） |

`commands` 不依赖 tauri，只依赖 `core`：领域操作签名为 `fn(&impl Deps, &mut App, …)`，
因此 `FakeDeps` 能驱动整层，tauri 只是最外面的一层适配器。

### Snapshot 形状

一次拉取带齐一屏所需（`src-tauri/commands/src/snapshot.rs`）：

```rust
Snapshot {
    services,               // 已知 NSSM 服务，默认服务在前
    selected,               // 当前服务名，"" 表示未知
    facts: Option<FactsView>,   // app_dir / app_params / start / dirty
    status: Status,         // sc query 状态字 + 探活结论
    values,                 // 由 AppParameters 解析出的权威表单值
    extras, warnings,       // 未识别 token 与解析告警
    preset_loaded,          // 表单当前对应的预设名（"" = 无）
    presets, settings,      // 预设名列表 / 偏好
    channels,               // 四条构建线 (id, 展示名)
    strings, lang,          // 整张文案表 + "zh"/"en"
}
```

`Serialize` only：前端消费快照、从不回传，这正是「单向」的含义。
`dirty` 是**语义**判定（`!semantically_equal(form, app_params)`）；Apply 的「无变化」
判定是**文本**判定 —— CONTEXT.md 定下的两组判定，混用会得到「提示永不消失」或
「提示永不出现」。

### command 列表（16 个）

`get_snapshot` / `refresh_services` / `switch_service` / `apply_changes` / `revert` /
`service_action` / `set_start_mode` / `restart` / `load_preset` / `save_preset` /
`delete_preset` / `save_settings` / `check_update` / `install_update` /
`prune_update_dirs` / `is_dirty`

全部返回同一个信封，前端只有一处需要知道失败长什么样：

```json
{"ok": true,  "data":  { … }}
{"ok": false, "error": {"kind": "NoSuchService", "message": "…"}}
```

`kind` 是 `AppErrorKind` 的 PascalCase 变体名（可 switch），`message` 已翻译、直接渲染。

### 进度推送

`restart` 与 `install_update` 是 async command，跑在 `spawn_blocking` 上，逐行发事件：
`llama-ctl://restart-progress`、`llama-ctl://update-progress`。两者同时把行收进返回值的
`log` 字段，所以事后也能渲染整份 transcript。

### 与 Python 的**有意差异**

1. **Apply 不再内部重启。** Python 写回成功就 `do_restart()`，60 秒等待期间按钮是灰的、
   模态已经关掉 —— 用户分不清「在跑」和「卡住」。改为返回 `needs_restart`，由前端去调
   会流式输出的 `restart`。
2. **未知服务是拒绝，不是空表单。** `switch_service` 读不存在的注册表键会得到空参数，看
   起来像「这个服务没配参数」，下一步 Apply 就会把真服务的参数清掉。先查一次再拒绝。
3. **Auto backup 只在真有未应用更改时落地。** 表单与服务语义等价则什么都不写（Python
   无条件覆盖）。
4. **载入预设不再无条件覆盖同名预设。** 由 `preset_loaded` 把关：表单不是从该预设来的
   （启动自动选中 / 刚切过服务 / 预设刚删）就一个字都不写，避免静默破坏用户数据。
5. **Install 必须先 check。** `install_update` 安装的是上一次 `check_update` 找到的
   release，且校验变体未变 —— 用户看到的更新日志与装上的是同一个版本。
6. **`upd.install.confirm` 进了 log 首行。** Python 只在确认框里显示备份路径；进日志后
   整份 transcript 能独立读。
7. **Revert 先失效事实缓存。** Python 的 `load_params()` 直接读，缓存里是旧值就恢复不掉；
   这里先 `invalidate`，答案必定是系统当前的值。
8. **测试不断言中文措辞。** `i18n` 的语言是进程全局（`static LANG`，一个进程服务一个 UI），
   `cargo test` 又是并行线程 —— 断言日志文案会让用例互相依赖，实测约 1/3 概率随机失败。
   进度类断言改为「每一步都有一行」「`sc stop` / `sc start` 确实被调用」，
   切语言用例结尾把语言复位为 zh。连跑 8 次全绿。

### `Deps` 缺口（沿用既有记录，未补）

- **没有 sleep** —— `restart` 轮询注入时钟，带 64 次上限（与票 06/10 同一预算）。
- **没有环境变量** —— `Env` / `InstallEnv` 注入。
- **没有 `is_dir`** —— 更新目标由 `core::install::target_dir` 推导。
- **`http_get` 无 Content-Length** —— 下载进度只有「已收完」一行，没有百分比。

### 测试

- `src-tauri/core`：**194 例通过**（11 个 suite），全绿，本票未改动一行。
- `src-tauri/commands`：**44 例通过**（42 集成 + 2 单元），0 warning。
  新增 `tests/ticket11_commands.rs`，全部经 `&impl Deps` 跑真实调用；`Sc` 是本票新写的
  第二个 `Deps` 实现（包装 `FakeDeps`，让 `sc query/stop/start` 的答案随时间变化），
  与票 10 的 `ScriptedSc` 同形状。

### ADR-0001 落点

- `tauri.conf.json` 的 CSP：`default-src 'self'`，`connect-src` 只放行 IPC 与 asset 协议，
  `frame-src`/`object-src`/`base-uri` 全关。前端无任何外链（grep 确认无 http(s)://）。
- asset protocol 已开启；scope 刻意留空（由代码侧按需 min），不开放全盘。
- `build.rs` 嵌入 `requireAdministrator` manifest（ADR-0001 的整体提权）。
- 官方更新的 zip 下载走 Rust 侧，渲染进程不碰远端内容。

### 未能验证

- **窗口未真机打开过**（本环境无交互桌面会话）。`cargo build` 通过、`tauri.conf.json`
  能被 `tauri-build` 解析、占位前端无外链 —— 但「窗口能打开、样式生效」要到票 12 或
  本机构建时才能实测（票 09 的验收项）。
- `install_update` 的**真实网络路径**未跑（更新测试用已缓存的 zip + 脚本化的发布页）。
- NSIS 打包（ADR-0002，票 18）未验证；`bundle.targets` 已设为 `["nsis"]`，图标路径已就位。

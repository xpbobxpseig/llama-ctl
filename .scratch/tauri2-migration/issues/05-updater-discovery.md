# 05: updater — 版本发现、构建线与资产选择

**What to build:** 移植官方更新的「前半段」：查询 `ggml-org/llama.cpp` 的最新发布、按选定的 Build variant 匹配资产、解析已安装版本号与发布标签中的构建号。用户视角：设置页能显示「当前版本 b5527，最新 b5560」，并能知道将要下载哪个资产。

这一半是纯逻辑（HTML 解析、正则、字符串解析），不碰文件系统，因此与 06（下载与替换）分开，可以独立验收。

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] 四条构建线可用：`win-cuda-13.4-x64`（默认）/ `win-cuda-12.4-x64` / `win-cpu-x64` / `win-vulkan-x64`
- [ ] 已停发的构建线从旧配置读到时自动回退到默认线（如 `win-cuda-13.3-x64`）
- [ ] 从官方 releases 页面解析出最新发布与其资产链接
- [ ] 按构建线正确匹配资产名
- [ ] 已安装版本号从 `llama-server.exe` 读取；读不到时返回「未知」而非报错
- [ ] 发布标签中的构建号解析正确
- [ ] 网络失败返回可展示的错误，不 panic
- [ ] 迁移现有更新测试中的版本发现部分（`test_updater.py` 879 行的前半）

## Resolution

实现：`src-tauri/core/src/updater.rs`（`pub mod updater;` 已加进 `src/lib.rs`），
测试：`src-tauri/core/tests/ticket05_updater.rs`（16 个用例，`cargo test` 全绿）。

公开 API：`Variant`（`Cuda134`/`Cuda124`/`Cpu`/`Vulkan` + `ALL`/`DEFAULT`/`id()`/`label()`/`from_id()`）、
`channels()`、`resolve_variant(Option<&str>)`、`RETIRED_CHANNELS`、`DEFAULT_CHANNEL`、
`parse_build(&str)`、`parse_version_output(&str)`、`get_installed_build(&impl Deps, &Path)`、
`page_links(&str)`、`select_assets(&str, &[Asset], Variant)`、`find_latest_release(&impl Deps, Variant)`，
以及 `Asset` / `Release` 两个 `Serialize` 结构（前端直接渲染）。所有网络经 `d.http_get()`，
子进程经 `d.spawn()`，无第二条外部通道。

与 Python `updater.py` 的**有意差异**：

1. **变体是枚举而非字符串字典。** Python 的 `CHANNELS` 是 `dict`，退役变体靠「从表里删掉
   key、由 `_upd_channel()` 回退」表达。Rust 用 `Variant` 枚举承载，退役 id 不在枚举里，
   退役清单显式列为 `RETIRED_CHANNELS`（仅文档/断言用途）：回退不是「查不到就默认」，
   而是类型上不可能表示退役变体。行为等价，`_upd_channel()` 的回退语义落在
   `resolve_variant()`。
2. **错误类型统一为 `AppError{UpdateFailed}`，不再有 `UpdateError`。** Python 的
   `UpdateError` 是 updater 私有异常；这里走 crate 级 `AppError`，前端可按 `kind` 分支。
   消息文本沿用 Python 原文（含「GitHub Releases 页面中未找到匹配资产（channel: …）」）。
3. **网络失败不再被包一层。** Python 的 `http_text()` 把 `HTTPError`/`URLError` 改写成
   「GitHub Releases 页面 HTTP %s」/「网络错误：%s」；Rust 直接把 `DepsError.message`
   原样透出——改写是 `Deps` 实现方（ticket 06 的真实 HTTP 客户端）的职责，本模块不二次加工。
4. **`get_installed_build` 少了 `os.path.isfile` 预检。** `Deps` 没有「文件是否存在」探针，
   只有 `spawn`；缺失的 exe 在真实实现里就是 `SpawnFailed`，与 Python 预检后的 `None`
   同果。**因此 Python 的「文件不存在 → 0 次子进程」在 Rust 里变成 1 次失败的 spawn**；
   另外 Python 合并 stdout+stderr，而 `Deps::spawn` 只返回一段字节流（ticket 02 的解码
   问题）——真实实现必须自行合并 stderr，否则 `llama-server` 把版本行写 stderr 时会永远
   解析为「未知」。
5. **HTML 解析为手写扫描器，非 `HTMLParser`。** 无第三方依赖（未新增 Cargo 依赖）。
   覆盖：引号/无引号属性值、实体（`&amp;` 等，含数字实体）、HTML 注释、重复 `href`
   取最后一个（`dict(attrs)` 语义）。未覆盖：`<script>`/`<style>` 内的裸 `<`、
   CDATA、畸形嵌套——GitHub 自己的页面不产生这些，够用即止。
6. **URL 处理用前缀匹配替代 `regex fullmatch`。** `url_path()` 取 path 并丢弃 `?`/`#`
   之后的内容，`select_assets` 用整名相等比较；Python 的 `[^/?#]+` 约束改为「剩余段内
   不含 `/`」的显式检查，语义相同。
7. **`build` 字段为 `u32` 而非 `Optional[int]`。** `find_latest_release` 只在
   `parse_build()` 成功时才返回 `Release`，故 `build` 必然有值（Python 里同为 int，
   只是类型上不保证）；`get_installed_build` 仍是 `Option<u32>`，「未知」= `None`，
   对应 UI 的 `upd.status.unknown`（`strings.py:119`）。
8. **未实现下载/解压/备份/回滚**（`download`、`is_valid_zip`、`collect_conflicts`、
   `extract_*`、`backup_*`、`prune_*`）——按 ticket 划分归 06。

未改动 `src/deps.rs` / `src/fake.rs`。`Deps` 缺失的能力（未补，仅记录）：
`Deps::spawn` 不区分 stdout/stderr（见第 4 条）；没有「文件是否存在」探针；
`http_get` 没有 header/timeout/状态码（真实实现需在自身内部固定 User-Agent 与超时，
本模块无法指定）。

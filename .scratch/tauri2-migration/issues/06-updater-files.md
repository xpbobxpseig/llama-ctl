# 06: updater — 下载、zip 校验、原子替换与陈旧目录清理

**What to build:** 移植官方更新的「后半段」：带重试与退避的下载、缓存 zip 的有效性校验、逐文件原子替换、备份与还原、以及陈旧下载与备份目录的清理。用户视角：更新过程要么完整完成，要么完整回到原样，绝不留下半替换的二进制。

**Blocked by:** 01, 05

**Status:** ready-for-agent

- [x] 下载带重试与指数退避，进度可回调
- [x] 已缓存的 zip 复用前先校验有效性 —— 坏缓存不得被当成有效资产（这是 `dc45c77` 修掉的 bug，不能回归）
- [x] 解压前识别冲突文件，逐文件原子替换
- [x] 备份到带时间戳的目录；还原能从备份精确恢复
- [x] 启动时后台清理陈旧下载与备份目录，各保留最近 3 个
- [x] 清理只删子目录，绝不动普通文件；失败静默跳过
- [x] 迁移现有更新测试中的文件操作部分（`test_updater.py` 879 行的后半）

## Resolution

实现：`src-tauri/core/src/update_files.rs`（`pub mod update_files;` 已加进 `src/lib.rs`），
测试：`src-tauri/core/tests/ticket06_update_files.rs`（30 个用例，`cargo test` 全 crate
151 例通过，9 个 suite，0 warning）。

公开 API：`download_asset(&impl Deps, url, dest, &DownloadOptions, Option<&mut dyn FnMut(u64)>)`、
`is_valid_zip(&impl Deps, &Path)` / `is_valid_zip_bytes(&[u8])`、`zip_top_files`、
`collect_conflicts`、`extract_one` / `extract_top_level`（后者返回已写入的文件名，供
ticket 10 精确 Rollback）、`backup_dir` / `timestamp`、`backup_files`、`restore_files`、
`remove_files`、`prune_old_subdirs` / `prune_nested_subdirs` / `cleanup_stale_dirs`，
以及常量 `PRUNE_KEEP` / `PART_SUFFIX` / `NEW_SUFFIX` / `OLD_SUFFIX` / `NO_RETRY` 与
结构体 `DownloadOptions` / `DownloadOutcome`。所有 IO 经 `&impl Deps`，无第二条外部通道。

与 Python `updater.py` 的**有意差异**：

1. **新增 Cargo 依赖 `zip` 9.0.3**（`default-features = false, features = ["deflate"]`）。
   Python 有 stdlib `zipfile`；Rust std 没有。`is_valid_zip` 必须**逐条目读取并核对
   CRC** 才能发现实测的「长度对、中央目录好、92.65% 字节被清零」故障，这是 std 无法
   替代的能力。`deflate` 是官方 zip 唯一的压缩方式，其余 codec（bzip2/zstd/lzma/time）
   一律关闭。
2. **下载不再断点续传。** Python 发 `Range: bytes=<n>-` 从 `.part` 续传；`Deps::http_get`
   没有 header、状态码与 Content-Length，续传无从实现。重试改为整份重取；已完整落盘的
   `.part` 会先被校验并直接转正（0 次网络请求），未完成的 `.part` 丢弃重来。**代价：
   抖动后要重下整个 400 MB 资产**，而不是只补剩余字节。
3. **进度回调只有 `done`，没有 `total`。** 同上：拿不到 Content-Length，百分比会是编造的。
   GUI 的 `upd.downloading`（`{n}（{p}%）`）改由调用方按已收字节呈现，或待 seam 扩展。
4. **退避不 sleep。** `Deps` 没有 sleep，测试也绝不能睡；`wait_backoff` 改为轮询注入时钟
   `now_millis()`，并有 `MAX_BACKOFF_POLLS` 上限（冻结的测试时钟不会挂死）。真实实现的
   时钟会前进，语义与 `time.sleep(min(backoff*attempt, 8))` 一致（1.5s / 3s / 4.5s…）。
5. **清理「清空」而非「删除」目录。** Python 用 `shutil.rmtree` 整棵删掉；`Deps` 只有
   `remove_file`，没有 `remove_dir`。`remove_dir_tree` 递归清空目录内的一切，**目录项本身
   会残留**（已用 `ponytail:` 注释标注上限：直到 seam 增加 `remove_dir_all`，届时该函数
   尾部变成一行）。`prune_old_subdirs` / `prune_nested_subdirs` 的返回语义（被清理的目录名）
   与「只处理子目录、`keep<=0` 不动、根不存在返回空」等安全边界与 Python 完全一致；
   `cleanup_stale_dirs` 额外保证永不失败——清理问题不能阻断启动。
6. **排序键用目录名里的数字段代替 mtime。** Python 按 `st_mtime` 排序；`DirEntry` 只有
   `path` 与 `is_dir`，没有 mtime。`name_key` 取文件名中的首个数字串（`20240101_120000`
   与 `b11213` 都按数值正确排序），并列时再按全名降序保证结果稳定可测。
7. **「文件是否存在」用 `read_file` 而非 `list_dir`。** `Deps` 没有 `is_file` 探针；
   `FakeDeps` 的目录清单与文件内容是两张独立的表（`with_dir` 不产生 `with_file`），
   用 `list_dir` 判存在会与真实实现不一致。`backup_files` / `restore_files` 反正要读
   内容，`collect_conflicts` / `remove_files` 则用一次读失败代替存在性探针。
8. **错误统一为 `AppError{UpdateFailed}`，OSError 不再单独存在。** Python 的
   `backup_files` / `restore_files` / `remove_files` 抛 `OSError` 并聚合消息；这里沿用
   「聚合、不因单个文件失败而停止」的语义，但错误类型与 ticket 05 一致。失败的写会带上
   文件名前缀（`"{name}: {message}"`），便于逐文件定位。
9. **`extract_top_level` 返回已写入文件名。** Python 返回 `None`，由 `installer.install`
   自己维护 `replaced` 清单；这里直接返回，让 ticket 10 少一处手工记账。
10. **时间戳用注入时钟自行换算。** `strftime("%Y%m%d_%H%M%S")` 改为 `now_millis()` 经
    Hinnant civil-from-days 换算成 UTC `YYYYmmdd_HHMMSS`（std 无日历，不值得为此加依赖）。
    Python 用本地时间，Rust 用 UTC——**同一时刻两个版本生成的备份目录名可能不同**，
    但形状一致、仍按名有序。

**`Deps` 缺口（未补，仅记录；未改动 `src/deps.rs` / `src/fake.rs`）**：

- **没有 `remove_dir` / `remove_dir_all`** —— 直接后果见第 5 条（清理只能清空目录）。
- **`http_get` 无 header / 状态码 / Content-Length** —— 直接后果见第 2、3 条（无续传、
  无百分比进度）。
- **没有「文件是否存在 / 是否是普通文件」探针** —— 与 ticket 05、07 已记录的同一缺口，
  本票用 `read_file` 绕开（第 7 条）。
- **没有 sleep** —— 退避改为轮询注入时钟（第 4 条）。

未迁移：`test_updater.py` 中依赖 `urlopen` 流式读取与 `Range` 行为的用例
（`test_download_retries_and_resumes_after_mid_transfer_cut`、
`test_download_resume_restarts_from_zero_when_server_ignores_range`、
`test_download_keeps_partial_file_across_attempts`）——这些断言的是 seam 无法表达的
HTTP 细节，其 Rust 对应物是「重试后成功」（已覆盖）与「`.part` 转正」（已覆盖）。

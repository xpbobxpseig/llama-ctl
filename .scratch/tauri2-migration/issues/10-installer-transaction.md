# 10: installer — 官方更新事务与失败回滚

**What to build:** 把官方更新的安装事务移植到 Rust：下载 → 停服 → 备份 → 逐文件替换 → 重启，任一步失败精确 Rollback 已替换文件，收尾尽力重启服务。用户视角：点「立即更新」后能看到逐步进展，失败了工具会把文件恢复到原样并尽力把服务拉起来，绝不静默留下停摆的服务或半替换的二进制。

这是领域层里唯一有真实依赖的模块（依赖 updater、服务控制、文案），所以排在最后。

**Blocked by:** 04, 05, 06, 08

**Status:** ready-for-agent

- [x] 完整序列：下载（已缓存则复用）→ 停止服务 → 备份旧文件到带时间戳目录 → 逐文件原子替换 → 重启并确认 RUNNING
- [x] 备份失败即中止，且未替换任何文件
- [x] 替换过程记录已替换清单，任一步失败精确 Rollback 已替换文件
- [x] 失败收尾尽力重启服务，绝不静默留下停摆服务
- [x] 进度日志逐行输出，可被前端实时消费
- [x] 替换目标优先按服务的安装目录推导，推导失败时回退环境变量
- [x] 用注入的假依赖在无网络、无服务的环境下跑完整条失败/回滚路径
- [x] 迁移现有安装事务测试（`test_installer.py` 357 行）
- [x] 注意术语区分：Rollback 是这里的失败路径，不是用户主动的 Revert

## Resolution

实现：`src-tauri/core/src/install.rs`（`pub mod install;` 已加进 `src/lib.rs`），
测试：`src-tauri/core/tests/ticket10_install.rs`（19 个用例，`cargo test` 全 crate
**194 例通过，11 个 suite，0 warning**）。

公开 API：`install(&impl Deps, &Release, service, &InstallPaths, &mut dyn FnMut(&str))
-> AppResult<InstallResult>`（唯一的入口，对应 Python 的 `install(...)`）、
`target_dir(&impl Deps, &FactsCache, service, &InstallEnv) -> PathBuf`、
`InstallPaths { target, backup_dir, download_dir }`、`InstallEnv { llama_dir }`、
`InstallResult { replaced, added, downloaded, build }`，以及常量 `STOPPED_STATE` /
`SERVER_EXE` / `REFRESH_SENTINEL` / `DEFAULT_LLAMA_DIR` / `LLAMA_DIR_ENV` /
`STOP_POLLS` / `RUNNING_POLLS` / `RESTART_POLLS`。Rollback 本身（`rollback`）是私有的：
它是本模块的失败路径，不是可调用的操作。

与 Python `installer.py` 的**有意差异**：

1. **下载提到停服之前。** Python 先下载再停服（`install()` 第 1 步就是下载），
   本票沿用该顺序 —— 清单条目里写的「停止服务 → 下载」与 Python 实现不符，按
   Python 实现为准。好处是网络故障不会白白停一次服务。
2. **Python 的 `RealDeps` 这一层消失了。** Python 用一个对象聚合 updater/nssm 的
   函数指针以便测试替换；Rust 侧所有副作用本来就只经 `Deps`，下载/校验/备份/还原/
   解压由 ticket 05、06 的函数直接提供，服务控制由 ticket 04 提供，所以入口参数只
   剩 `&impl Deps` —— 少一个抽象层，没有损失可测性。
3. **目录参数收敛为 `InstallPaths`。** `target` / `bak` / `download_dir` 三个字符串
   在 Python 里是三个位置参数（易错位）；这里合成一个具名结构体。备份目录仍由调用方
   用 `update_files::backup_dir` 推导后传入，形状不变。
4. **不 sleep，改为轮询注入时钟。** `Deps` 没有 sleep（ticket 06 已记录），
   `wait_poll` 以 `now_millis()` 轮询 0.5 s 并带 `MAX_SPINS_PER_POLL` 上限（与 ticket 06
   的退避同一预算），冻结的测试时钟不会挂死。轮询次数与 Python 一致：停服 40 次、
   主 RUNNING 等待 120 次、收尾恢复 40 次（收尾刻意短于主等待，不再叠加成 2 分钟静默）。
5. **`sc_action` 用 `Err` 表示失败，不是 `(False, msg)`。** `Deps::spawn` 没有退出码
   （ticket 04 已记录），`sc stop` 对已停止服务返回的 1062 无法与真正被拒区分；
   改为「动作失败后再查一次状态」，由状态决定成败。启动命令本身抛异常的路径
   （Python `test_start_raising_rolls_back_and_restarts` 覆盖的回归）在这里天然就是
   同一条 `Err` 分支。
6. **下载进度只有一行「100%」。** `Deps::http_get` 没有 Content-Length（ticket 06
   第 3 条），拿不到百分比；`upd.downloading` 的 `{p}` 填 100，表示「已收完」。
   与 Python 的 0/25/50/75/100 五档不同。
7. **坏缓存的处理交给 `download_asset`。** Python 在 `install` 里手写「存在但无效 →
   删除重下 → 仍无效则中止」并自己清理 `dest` / `dest.part`；票 06 的
   `download_asset` 已内建这套逻辑（含 `.part` 转正与 CRC 校验），所以 `install` 里
   不再重复。`upd.cache.bad` / `upd.cache.still.bad` 这两条文案因此不再被本模块引用。
8. **两个中止原因改为只进 `Err`，不写日志行。** Python 对「空 conflicts」和「停服失败」
   既 `sink` 又 `raise`；这里沿用 Python 的 *文案* 作为 `AppError::message`，但不再
   重复写一行 —— 前端已经会把 `Err` 显示出来（`upd.err`），同一条消息出现两次是噪音。
   其余失败（备份失败、替换失败、启动失败、未达 RUNNING）保持「先写日志再返回」。
9. **`replaced` / `added` 由返回值带回。** Python 的 `install` 返回 `None`，
   `replaced`/`added` 只在函数内用于回滚；这里一并返回，调用方（ticket 11 的命令层）
   可以直接汇报「替换了哪些文件」，无需另记账。`extract_top_level` 的返回值
   （ticket 06 第 9 条）最终没被本模块使用：需要「先覆盖已有、再装新增」的顺序，
   故仍逐文件调用 `extract_one`，但**不需要手工记账**——顺序由 `collect_conflicts`
   与 `zip_top_files` 推出。
10. **替换目标的判定用 `read_file` 而非 `is_dir`。** `Deps` 没有「是否是目录」探针
    （ticket 06 已记录的同一缺口），Python 的 `os.path.isdir(AppDirectory)` 改为
    读 `<AppDirectory>/llama-server.exe`：这既是「目录真的存在」的证据，也是本次更新
    真正的前提，而且经 seam 双向可判（`list_dir` 在假实现里对不存在的目录也返回
    `Ok(空)`，无法用于回退分支）。已用 `ponytail:` 注释标注上限。
11. **「环境变量回退」改为注入。** `Deps` 读不到环境变量（ticket 04、07 已记录），
    所以 `LLAMA_CTL_LLAMA_DIR` 经 `InstallEnv` 传入（`InstallEnv::from_process()` 读真
    进程环境），与 `persist::Env` 同一形状。默认值 `F:\llama.cpp` 与 GUI 的
    `LLAMA_DIR` 一致。
12. **收尾恢复不再吞异常。** Python 的 `_try_restart_service` 用 `except Exception: pass`
    兜底；这里 `sc_action` / `wait_for` 都不 panic，异常无处可来，故不写那层
    `catch`——「尽力而为」由「只在 STOPPED 时启动、结果不检查」表达，语义相同。

**`Deps` 缺口（未补，仅记录；未改动 `src/deps.rs` / `src/fake.rs`）**：

- **没有 sleep** —— 直接后果见第 4 条（等待改为轮询注入时钟）。
- **没有「是否是目录 / 文件是否存在」探针** —— 与 ticket 05、06、07 已记录的同一
  缺口，本票用 `read_file` 绕开（第 10 条）。
- **`spawn` 没有退出码** —— 与 ticket 04 已记录的同一缺口，本票用「动作后再查状态」
  绕开（第 5 条）。
- **`http_get` 无 Content-Length / 状态码 / header** —— 与 ticket 06 已记录的同一
  缺口，本票只影响进度文案（第 6 条）。

未迁移：`test_installer.py` 里断言 `os.remove` 调用次数与 `time.sleep` 次数的用例
（`test_bad_cache_deleted_and_redownloaded`、`test_download_failure_cleans_partials`、
`test_try_restart_service_gives_up_quickly`）—— 这些断言的是 Python 特有的实现细节
（`.part` 清理时机、sleep 计数），其 Rust 对应物分别是「坏缓存不复用」（ticket 06
已覆盖）、「下载失败不留残留」（ticket 06 已覆盖）与「收尾轮询上限 40」（本票常量
`RESTART_POLLS` 已表达）。

# 04: nssm_adapter — 服务事实读取、缓存与服务控制

**What to build:** 把服务层移植到 Rust：读取 Service 的 Fact（安装目录、`AppParameters`、开机自启模式、运行状态、健康探测结果），按服务名缓存并在写回成功后失效；以及启停服务、切换开机自启、枚举本机所有 NSSM 服务、探活。用户视角：切换服务时响应是即时的（注册表直读，不 spawn 子进程），且工具不会读到刚写失败的状态。

**Blocked by:** 01, 02

**Status:** ready-for-agent

- [x] 静态事实走注册表直读，`facts()` 调用 spawn 子进程次数为 0（现有硬指标，测试需断言）
- [x] 事实按服务名缓存；第二次读取不再访问注册表
- [x] 写回**成功后**才失效缓存；写回失败时保留缓存
- [x] 注册表不可读（非 NSSM 服务 / 权限不足）时回退到 `nssm get`
- [x] Start DWORD 映射：2=auto / 3=manual / 4=disabled，未知值与无值回退 manual
- [x] 枚举本机所有 NSSM 服务；枚举走 `powershell` 时显式带 `CREATE_NO_WINDOW`（不闪黑框）
- [x] 启停服务走 `sc`，行为与现有实现一致
- [x] `/healthz` 探活能区分真正就绪与 START_PENDING
- [x] 所有子进程输出的解码走 02 产出的解码函数
- [x] 迁移现有服务事实测试的全部用例（`test_nssm_facts.py` 145 行），含 0 spawn 断言

## Resolution

**模块**：`src-tauri/core/src/service.rs`；测试 `tests/ticket04_service.rs`（24 个）。

**状态**：done。

**与 Python `nssm_adapter.py` 的差异（均有意为之）：**

1. **缓存是显式传入的 `FactsCache`，不是模块级全局。** `cargo test` 在单进程内并行跑用例，全局缓存会让一个用例脚本化的注册表泄漏进另一个。附带好处是不再需要 Python 那套「测试之间 `invalidate()`」的仪式。
2. **写回成功后才失效，失败时保留缓存** —— 与 Python 一致，这是有意的：服务没变，旧事实仍然为真，重读等于对一个没改动的服务撒谎。
3. **`Deps::spawn` 没有退出码**，所以 `nssm get` 无法像 Python 那样判 `rc == 0`；spawn 成功即视为有答案。
4. **`Deps` 无法表达 `CREATE_NO_WINDOW`。** Python 给每个命令都传它以防闪黑框；真实现必须无条件加，本模块无法表达，已在文件头注明。
5. **`Deps` 没有环境访问**，故 `LLAMA_CTL_NSSM_EXE` / `LLAMA_CTL_SERVICE` 未被读取。服务名始终是参数，影响有限；真实现需自行接入。
6. **健康探测把通配 host（`""` / `0.0.0.0` / `::`）改写为 `127.0.0.1`**，因为 Windows 拒绝连 `http://0.0.0.0:port`。`port == 0` 视为「未配置端口」，从不探测。
7. **`query_status` 把「非 RUNNING 就不探测」写死**：`sc` 在 `llama-server` 监听之前就说 RUNNING，这正是探活要抓的假「就绪」。`START_PENDING` 永不报就绪。
8. **`parse_state` 按「STATE … : 数字 词」的形状匹配而非固定语言**，因为 `sc` 输出的本地化版本保持同一形状。

**0-spawn 断言**：`facts_come_from_the_registry_with_zero_spawns` 与 `the_compat_accessors_hit_the_cache_and_spawn_nothing` 明确断言 `spawn_count() == 0`。测试用 `registry_reads()` 单独统计注册表读取次数，而不是数 `calls()` 总数——后者会把子进程调用混进来，使「有没有重读」变得无法判断。

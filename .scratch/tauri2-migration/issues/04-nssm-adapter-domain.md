# 04: nssm_adapter — 服务事实读取、缓存与服务控制

**What to build:** 把服务层移植到 Rust：读取 Service 的 Fact（安装目录、`AppParameters`、开机自启模式、运行状态、健康探测结果），按服务名缓存并在写回成功后失效；以及启停服务、切换开机自启、枚举本机所有 NSSM 服务、探活。用户视角：切换服务时响应是即时的（注册表直读，不 spawn 子进程），且工具不会读到刚写失败的状态。

**Blocked by:** 01, 02

**Status:** ready-for-agent

- [ ] 静态事实走注册表直读，`facts()` 调用 spawn 子进程次数为 0（现有硬指标，测试需断言）
- [ ] 事实按服务名缓存；第二次读取不再访问注册表
- [ ] 写回**成功后**才失效缓存；写回失败时保留缓存
- [ ] 注册表不可读（非 NSSM 服务 / 权限不足）时回退到 `nssm get`
- [ ] Start DWORD 映射：2=auto / 3=manual / 4=disabled，未知值与无值回退 manual
- [ ] 枚举本机所有 NSSM 服务；枚举走 `powershell` 时显式带 `CREATE_NO_WINDOW`（不闪黑框）
- [ ] 启停服务走 `sc`，行为与现有实现一致
- [ ] `/healthz` 探活能区分真正就绪与 START_PENDING
- [ ] 所有子进程输出的解码走 02 产出的解码函数
- [ ] 迁移现有服务事实测试的全部用例（`test_nssm_facts.py` 145 行），含 0 spawn 断言

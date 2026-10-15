# 18: NSIS 打包、管理员提权 manifest 与 CSP 收紧

**What to build:** 产出可分发的安装包：NSIS 安装包、进程带 `requireAdministrator` manifest、前端资源全部随包分发、CSP 收紧。用户视角：下载安装包装上就能用，且升级到新版本后预设与偏好还在（依赖 00 完成的用户目录迁移）。

ADR-0001 与 ADR-0002 在本票落地。两条硬约束要作为验收项逐条查：无外链、无远端加载。

**Blocked by:** 12

**Status:** ready-for-agent

- [ ] NSIS 安装包可产出并安装，体积落在 4–8 MB
- [ ] 进程 manifest 为 `requireAdministrator`，启动时一次 UAC
- [ ] CSP 收紧：`default-src 'self'`，图片仅 `data:` 与本地资源，`connect-src` 只放行 IPC 与探活
- [ ] 全量检查无外链：无 CDN、无字体外链、无运行时远程拉取（ADR-0001）
- [ ] asset protocol 显式限定 scope，不放开全盘
- [ ] 官方更新的 zip 下载走 Rust 侧，不由前端 fetch（ADR-0001）
- [ ] 覆盖安装新版本后，用户目录中的预设与偏好仍完整（ADR-0002 的验收点）
- [ ] 卸载不残留用户数据以外的文件；卸载行为可预期

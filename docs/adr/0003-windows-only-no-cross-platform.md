# 放弃跨平台：明确 Windows-only，绑定 nssm / sc / powershell

换到 Tauri 让**前端代码**具备跨平台渲染能力，但本工具的领域层硬依赖 `nssm.exe`、`sc` 与 `powershell Get-CimInstance`，全部 Windows-only。我们明确不做跨平台，不抽象服务管理后端，也不为 Linux / macOS 预留实现。

## Status

proposed

## Considered Options

- **Windows-only，不抽象（选定）**：跨平台的招牌收益在本项目不成立，别把它算进换栈收益。
- **抽象 `ServiceManager` trait（Nssm / Systemd / Launchd 三后端）**：唯一能真正跨平台的路，但工作量远超换 UI 本身——服务生命周期语义、日志、二进制替换目标路径、编码（UTF-16LE / GBK）全都得重写一套，且没人能验证另两个后端。
- **预留接口但不实现**：看起来稳健，实际是无人验证的死接口，且会诱导调用方写出「假装后端可替换」的代码。

## Consequences

- 不要在代码里为「以后可能上 Linux」留 seam、trait 或 cfg 分支。
- 所有 Windows 相关的坑要照单收下并显式处理：NSSM 输出 UTF-16LE、`sc` 输出本地代码页（GBK），需按字节特征探测解码；`powershell` 列举服务要 spawn 子进程并显式 `CREATE_NO_WINDOW`，否则闪控制台黑框。
- 跨平台能力不进入任何收益评估。若将来真要支持 Linux，那是一个新项目级决策，不是本 ADR 的延伸。

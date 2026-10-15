# 整体以管理员权限运行，前端资源全本地并收紧 CSP

工具约九成操作（`nssm set` / `sc start|stop` / 替换 llama.cpp 二进制）都需要管理员权限。我们选择让**整个进程**带 `requireAdministrator` manifest 运行，而不是按需 UAC 提权或常驻一个提权 sidecar。代价是 WebView2 渲染进程也在管理员权限下，因此前端必须锁死：资源全部打包进二进制、禁止任何远端加载、CSP 收紧。

## Status

proposed

## Considered Options

- **整体提权（选定）**：与当前 CustomTkinter 版行为一致，用户一次 UAC 后不再被打断。
- **按需 UAC 提权**：GUI 普通权限运行，每个特权操作用 `Start-Process -Verb RunAs` 起一个一次性提升进程。安全性最好，但这工具启停/重启/应用更改/官方更新都是特权操作，实际会一天弹几十次，且跨进程流式返回更新进度日志很别扭。
- **常驻提权 sidecar**：一个高权限后台进程，前端 IPC 调用。体验最顺，但把最大攻击面做成常驻，且要自己做鉴权，否则本机任意进程都能指挥它改服务。

## Consequences

- 渲染进程在高权限上下文中执行前端代码，因此：
  - 所有 HTML/CSS/JS/字体/图标必须随包分发，禁止 CDN、禁止运行时远程拉取。
  - CSP 收紧到 `default-src 'self'`，图片只允许 `data:` 与本地资源，`connect-src` 只放行 IPC 与 `/healthz` 探测。
  - Tauri 的 asset protocol 需显式限定 scope，不能放开全盘。
- 官方更新要下载的 zip 来自 GitHub，走 Rust 侧而非前端 `fetch`——不让渲染进程直接处理远端内容。
- 这条约束在代码里不显眼，任何后续「加个在线文档链接」「换个 CDN 图标字体」的改动都会破坏它。验收时要把 CSP 与无外链作为一条硬检查。

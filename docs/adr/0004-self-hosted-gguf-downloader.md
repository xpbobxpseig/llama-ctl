# GGUF 下载走自研流式引擎：不用 llama.cpp `-hf`，也不复用更新器 HTTP 路径

模型市场要把 5–40GB 的 GGUF 下载到用户指定目录，且要求进度可见、可暂停、断点续传、下载完校验、HF 与魔搭双源。三条实现路径里，我们选择在 core 里自研一个流式下载引擎，而不是复用任何现成的下载能力。

## Status

proposed

## Considered Options

- **自研流式引擎（选定）**：独立 ureq Agent + `Range` 续传 + `.part` 中转 + Sha256 校验，状态放独立 DownloadManager。唯一同时满足「双 Hub、用户目录约定、进度/暂停控制权、不冻结窗口」的路。
- **llama.cpp 自带 `-hf` / `--model-url`**：能力最现成（分片、自动 mmproj、续传、退避重试都有），但实测不支持魔搭——官方明言 "ModelScope is not an HF-compatible endpoint"，相关 `-ms` PR 全部未合并，把 `MODEL_ENDPOINT` 指向 modelscope.cn 返回的是 SPA 兜底 HTML，必然失败；缓存落到 `%LOCALAPPDATA%` 的 HF 布局，违背用户「模型归 `F:\AI_Model`」的目录约定；进度只在 stderr 打行，UI 拿不到结构化进度，也没有暂停语义。
- **复用更新器 `http_get`**：整包读进内存、`limit()` 上限 2GiB——40GB 资产必炸；且长事务持 `AppState` 互斥锁会把窗口其它命令全部卡死（v6 已为此修过一次主线程冻结，不能倒退）。它的骨架（阻塞 worker + 逐行事件 sink + `.part` + 退避重试）值得复刻，代码本身不可复用。

## Consequences

- core 的 `Deps` seam 新增两个能力：流式落盘 HTTP 与受控进程 spawn；测试全部走 FakeDeps，真实网络只进端到端联调。
- **下载必须用独立 Agent**：共享 updater agent 的 30 分钟 `timeout_recv_body` 是整包总预算——HF CDN 实测 4.2 MB/s，40GB 要 2.7 小时，必被砍断。下载 Agent 无总上限、只设无活动读超时。
- DownloadManager 持自己的锁，与 `AppState` 隔离是设计红线：任何把下载状态塞回 `AppState` 的改动都会复现「下载期间窗口假死」。
- 完整性校验依赖源侧校验和（HF tree 的 `lfs.oid`、魔搭 files 的 `Sha256`），两源都有；遇到都不给的仓库降级为体积校验并在 UI 明示「未校验」。
- 事件通道新增 `llama-ctl://download-progress`，与既有 `update-progress` 同构（先订阅后调用）。
- 断点续传的正确性依赖 `.part` + 续传前 HEAD 比对（长度/etag），防止源文件更新后拼出损坏文件——这条在单测里锁定。

# Spec: 模型市场 — GGUF 发现、下载、适配评估与实测

> 状态：**已实施（v0.2.0，2026-10-26 随版本发布）**。由 grill 会话整理（2026-10-25），决策依据见 `docs/adr/0004`，术语见 `CONTEXT.md`「模型市场」一节。网络与硬件事实均来自本机实测（见 Further Notes）。期一（Rust 领域层）与期二（前端与契约）均落地；2026-10-26 首轮界面标注评审后微调：量级筛选由分段 chips 改为带标签「规模」下拉（全部/≥1B/≥7B/≥30B），硬件配置改按设备分行展示，顶栏「打开安装目录」接线，浏览器 demo 支持本地搜索过滤。

## Problem Statement

拉马管家把 llama.cpp 服务管到了「改参数点一下就行」，但模型的获取仍全靠手动：开浏览器找 GGUF 仓库、挑量化档、下载几十 GB、放进 `F:\AI_Model`、回参数页手填路径——选量化档还要靠反复手动跑 llama-bench。本机（RTX 4090 24GB / 64GB 内存）恰好站在「27B Q4 能全进显存、70B 看量化」的边界上，量化档选错一档就是差几倍的速度或差十几 GB 的浪费。

两条外部链路都已实测可用但性格迥异：HF 直连 API 快（0.86s）但 CDN 下载慢（4.2 MB/s），魔搭 CDN 快 8.8 倍（37 MB/s）但搜索 API 只有 `PUT /api/v1/dolphin/models` 且不支持服务端 GGUF 过滤；llama.cpp 自带的 `-hf` 不支持魔搭（官方明言非 HF 兼容端点）。需要一个集成在管家里的市场：**发现 → 下载 → 适配评估 → 一键启用**的闭环。

## Solution

新增「市场」视图（侧栏底部辅助区，与设置/关于同区；内容区 预设/参数/日志 三项不动），Rust 侧新增 `market` 领域模块：

- **双 Hub 适配**：`Hub` trait 两个实现——`HfHub`（`filter=gguf` 搜索、`?blobs=true` 详情含 gguf 元数据块、tree 清单、resolve 302→CDN）与 `MsHub`（dolphin PUT 搜索 + 客户端 GGUF 过滤、`SortBy:"DownloadsCount"` 热门榜、repo/files 清单含 Sha256、resolve 302→国内 CDN）。
- **自研流式下载引擎**（ADR-0004）：Range 断点续传、`.part` 中转、Sha256 校验、独立 DownloadManager（绝不占 `AppState` 锁）、单任务队列、暂停/继续/跨重启恢复。
- **硬件检测与适配等级**：windows crate（DXGI 枚举 + GlobalMemoryStatusEx）取显存/内存，对量化档做四档判定（完全进显存 / 大部分进显存 / 勉强 / 不建议）+ 一行依据。
- **实测**：对已下载模型停服 → 跑 `llama-bench -o json` → 按原状态恢复服务，成绩存档。
- **一键启用**：回填 `--model`（含 `--mmproj`）到表单，走既有 Apply 流程写回 AppParameters——市场不直接改服务。

分两期交付：

- **期一：Rust 领域层**。hub / downloader / hwinfo / bench 全部落在 `core`，走 `Deps` seam，`cargo test` 可独立验收（对齐 tauri2-migration 的期一模式）。
- **期二：前端 MarketView**。契约三处同步（rail-foot 计数、CONTRACT 白名单、copy.js 键），fixture demo 数据，smoke 全绿。

## User Stories

### 期一：Rust 领域层（发现与下载）

1. As a 用户, I want 源在 HF/魔搭间切换且记住上次选择（初始魔搭）, so that 下载带宽优的魔搭成为默认动线而 HF 随时可切
2. As a 用户, I want 打开市场即见热门榜：按下载量排序的前 50 个 GGUF 仓库（HF `filter=gguf` 服务端过滤；魔搭 `SortBy:"DownloadsCount"` + 客户端按 Libraries 含 gguf 过滤）, so that 不用打字就能发现模型
3. As a 用户, I want 量级筛选条默认筛掉 1B 以下（按名称参数量正则 + 体积启发，详情页再精确）, so that 下载榜不被 0.6B 级小模型霸占且一键切回全量
4. As a 用户, I want 关键词搜索返回 ≤50 条结果并同样只含 GGUF, so that 看到的每个仓库都可直接加载
5. As a 用户, I want 仓库详情按文件名把文件归组为量化档（主文件 / `-000NN-of-000NN` 分片组 / `mmproj-` 投影 / 其他）, so that 一个量化档就是一次可执行的下载
6. As a 用户, I want 详情展示 gguf 元数据（架构/上下文长度/总参数，HF 元数据块；魔搭无则留空）, so that 不用去网页查参数
7. As a 用户, I want HF gated 仓库标注「需授权」（API `gated` 字段），魔搭侧优先展示开放镜像（如 `LLM-Research/`）, so that 点下载前就知道能不能下
8. As a 用户, I want 下载走 Range 断点续传（两源实测 206），`.part` 中转完成后原子改名, so that 断网/关机不前功尽弃
9. As a 用户, I want 暂停/继续/取消，同时最多 1 个任务排队, so that 40GB 级传输可控
10. As a 开发者, I want 下载完用 Sha256 校验（HF `lfs.oid` / 魔搭 files `Sha256`），无校验和的仓库降级为体积校验并明示, so that 坏文件不会静默落盘
11. As a 用户, I want 下载前预检目标盘剩余空间，不足直接拒绝并明示缺口, so that 不会下了 30GB 才报磁盘满
12. As a 开发者, I want 下载状态放在独立 DownloadManager（自己的锁），全程不碰 `AppState` 互斥锁, so that 40GB 下载期间参数页/日志页照常可用
13. As a 用户, I want 进度经 `llama-ctl://download-progress` 事件上报（已收/总量/速度/当前文件，≥1% 或 ≥2s 一跳）, so that 长下载有可见进展（既有原则：点了要有反应）
14. As a 用户, I want 任务列表持久化到 `market.json`，重启后仍显示、手动点继续即从断点拉起, so that 重启不丢任务也不擅自跑流量
15. As a 开发者, I want 下载文件落到 `<下载根>/<RepoName>/` 子目录（与现有 `Qwen3.8/` 布局一致），分片与 mmproj 作为一个任务拉齐, so that 市场下载的模型在磁盘上有统一形状
16. As a 开发者, I want 下载引擎用独立 ureq Agent（解除 30min 总 body 预算、改用无活动超时），失败按指数退避重试, so that HF 慢速链路 2.7h 的传输不会被共享 agent 的总预算砍断

### 期一：Rust 领域层（适配等级与实测）

17. As a 开发者, I want 硬件检测走 windows crate：DXGI 枚举适配器（型号/专用显存/共享显存/厂商）+ GlobalMemoryStatusEx 取物理内存，无子进程, so that NVIDIA/AMD/Intel/无独显全覆盖
18. As a 开发者, I want Intel 核显的 DedicatedVideoMemory 假值（128MB）按厂商防御，核显改用共享显存/内存口径, so that 核显机器不会全被判「不建议」
19. As a 用户, I want 四档适配等级（权重体积 +1.5GB 余量）：≤90% 显存=完全进显存；显存+内存富余装得下=大部分进显存（附估计 offload 比例）；≤70% 内存=勉强；否则=不建议, so that 选量化档前就有预期
20. As a 用户, I want 每档附一行依据（体积 vs 显存/内存）并注明「按权重估算，未计上下文对应的 KV 增长」, so that 131k ctx 这类大上下文场景知道等级偏乐观
21. As a 用户, I want 已下载模型可发起实测；服务在跑时确认后 停服→测→按原状态恢复，全程进度与失败原因就地可见, so that 不用记住「先停服务再跑 bench」
22. As a 开发者, I want bench 用 `llama-bench -o json` 结构化解析（pp512/tg128、fa、ngl 列），默认 `-ngl 99 -fa on -p 512 -n 128 -r 1`, so that 不解析 markdown 表格、单次实测十几秒到一分钟
23. As a 开发者, I want bench 子进程 `CREATE_NO_WINDOW` + 超时保护 + 可取消, so that 挂死不拖死界面也不闪黑框
24. As a 用户, I want 实测成绩存进本地模型条目并展示（pp512/tg128 两个数）, so that 同一模型不同量化档谁快一目了然

### 期一：Rust 领域层（本地模型）

25. As a 用户, I want 已下载区扫描下载根目录（两层深，兼容 `<模型名>/` 子目录与根目录平铺两种现有布局），`mmproj-` 文件归组到同目录主模型, so that 手动放的模型（如现有 Qwen3.8）同样获得实测/启用入口
26. As a 用户, I want 本地模型条目含 名称/体积/量化/适配等级/实测成绩，操作含 启用/实测/打开目录/删除, so that 管理闭环不离开市场页
27. As a 用户, I want 删除命中当前服务 `--model` 的模型时强警告, so that 不会把正在运行的服务的权重删掉
28. As a 用户, I want 一键启用把模型路径（含 `--mmproj`）回填到参数表单并走既有 Apply, so that 启用行为与手填路径完全同构（AppParameters 唯一真源不破）
29. As a 开发者, I want 写回路径沿用现有正斜杠风格（`F:/AI_Model/...`）, so that 与注册表现值风格一致、不触发假性 diff

### 期二：前端与契约

30. As a 用户, I want 市场页挂在侧栏底部辅助区（与设置/关于同区），内容区 预设/参数/日志 不动, so that 参数主页面地位不变
31. As a 用户, I want 卡片为纯文字（名称/参数量/量化 chips/体积/下载量/等级色标）, so that 符合 CSP 全本地约束（禁远程图）也省流量
32. As a 用户, I want 顶部 Dd 源切换 + 搜索框 + 「规模」下拉（全部/≥1B/≥7B/≥30B，默认 ≥1B；2026-10-26 评审由分段 chips 改为带标签下拉，chips 的意图不可读）, so that 三种动线（榜单/搜索/筛选）都顺手
33. As a 用户, I want 量化档行内直接下载，下载中显示进度条与速度, so that 不跳页就能盯传输
34. As a 开发者, I want 同一次改动里同步 smoke 契约三处：rail-foot 计数 2→3、CONTRACT 命令白名单追加、copy.js 中英键与 REQUIRED 清单，另加 fixture demo 数据与 smoke.entry 挂载, so that `npm run smoke` 始终全绿
35. As a 用户, I want 设置页新增「市场」节：HF/魔搭令牌（手填）、下载根目录（默认 `F:\AI_Model`）, so that 令牌与目录不用改配置文件
36. As a 用户, I want 下载/实测的失败原因就地显示（行内红字），不用翻日志页, so that 长操作失败不再是「点了没反应」

## Implementation Decisions

- **Hub 接口**（core/src/market/hub.rs）：`search(query, page) / hot_list() / repo_detail(id) / files(id) → Vec<MarketFile{path,size,sha256?}> / download_url(id, file)`。端点全部来自实测：
  - HF：列表 `GET /api/models?search=&filter=gguf&sort=downloads&limit=50`（注意 `library=gguf` 会被静默忽略）；详情 `GET /api/models/{repo}?blobs=true`（siblings + gguf 元数据块）；清单 `GET /api/models/{repo}/tree/main?recursive=true`（`lfs.oid` 即 sha256）；下载 `{repo}/resolve/main/{file}` 302→CDN，`Range` 206。匿名限流 ~3000 resolve/5min，gated 字段为 `"auto"/"manual"`。
  - 魔搭：搜索 `PUT /api/v1/dolphin/models` body `{Name, PageSize, PageNumber, SortBy}`（排序合法值实测为 `DownloadsCount` / `GmtModified` / `Default`；`Downloads` 会 400；默认为相关性排序）；结果在 `Data.Model.Models[]`，repo id = `Path/Name`；清单 `GET /api/v1/models/{id}/repo/files?Revision=master&Root=`（含 Size+Sha256）；下载 `/models/{org}/{model}/resolve/master/{file}` 302→国内 CDN。偶发 empty reply，按退避重试即可恢复。服务端无 gguf 过滤 → 客户端按 `Libraries` 含 `"gguf"` 过滤。
- **下载器**（core/src/market/downloader.rs）：独立 ureq Agent（rustls），**不用共享 updater agent 的 30min 总 body 预算**——改为无活动读超时 60s + 无总上限；逐块写入 `<file>.part`，续传先 HEAD 取 Content-Length/Accept-Ranges 再发 `Range: bytes={have}-`；指数退避重试（2s 起 ×10，沿用 update_files.rs 骨架）；完成后 Sha256 比对再原子改名。
- **DownloadManager**（core/src/market/manager.rs）：自有 `Mutex<DownloadState>`，与 `AppState` 完全隔离；队列深度 1；状态机 queued/running/paused/verifying/done/failed；每任务持久化于 `%APPDATA%\llama-ctl\market.json`（tasks[] + benchmarks[]，原子写同 persist.rs 惯例）。命令：`market_search` / `market_hot` / `market_repo` / `market_download` / `market_pause` / `market_resume` / `market_cancel` / `local_models` / `local_delete` / `bench_run`（save_settings 扩展 market 字段：hf_token / ms_token / download_root / last_hub）。事件：`llama-ctl://download-progress`。
- **适配等级规则**（表驱动，单测覆盖）：输入 权重总bytes S（含分片+mmproj）、最大独显 DedicatedVideoMemory V、物理内存 M；S' = S + 1.5GiB。S' ≤ 0.9V → `full_gpu`；S' ≤ V + 0.6·(M−8GiB) → `partial_gpu`（依据行给估计 offload 比例 V/S'）；S ≤ 0.7M → `cpu_only`；否则 `not_recommended`。等级仅对 LLM 权重口径；依据行固定注明未计 KV。
- **量级筛选启发**：名称正则 `(\d+(?:\.\d+)?)\s*[bB]` 抽参数量；无命中时按主文件体积兜底（<1.5GiB 视为小模型）。详情页展示 HF gguf 元数据块的精确 `total`（若有）。
- **bench_run 事务**：读服务运行态 → 运行中则确认 → `sc stop` → spawn `F:\llama.cpp\llama-bench.exe -m <path> -ngl 99 -fa on -p 512 -n 128 -r 1 -o json`（CREATE_NO_WINDOW，超时 30min 可取消）→ 解析 JSON 取 pp512/tg128 → 按原运行态恢复 → 成绩写入 market.json。失败路径尽力恢复服务（对齐 install.rs 的收尾原则）。
- **前端**：`MarketView.vue` 挂 rail-foot；列表卡片与详情沿用 v6 token（等级色标用状态色，不装饰）；下载状态组件订阅进度事件；全程不引远程资源（ADR-0001）。

## Testing Decisions

- `Deps` seam 扩展流式下载与进程 spawn 两个能力，测试走 FakeDeps（对齐现有 fake 模式）。
- Hub 解析用真实响应脱敏样本做 fixture 单测（HF 列表/详情/tree、MS dolphin/files 各 1–2 份），锁定字段路径。
- 适配等级规则表驱动：全档边界（90%/0.6M/0.7M）+ Intel 假显存 + 无独显用例。
- 下载器单测：Range 续传拼接、Sha256 失败路径、重试退避、`.part` 残留恢复（本地临时 HTTP 服务或 seam 模拟）。
- `npm run smoke` 全绿作为前端验收硬门槛；契约三处同步在同一提交内完成。
- 期一独立验收：`cargo test` + 一个最小 CLI 冒烟（搜索→选档→下载 639MB 的 Qwen3-0.6B → Sha256 通过）。

## 工单拆分（一期）

- **M1** core/market/hub：Hub trait + HfHub + MsHub + fixture 单测
- **M2** core/market/downloader：流式落盘/Range/Sha256/重试/独立 Agent 超时
- **M3** core/market/manager + commands：DownloadManager、market.json、事件通道、下载命令接线
- **M4** core/market/hwinfo：DXGI+内存检测、等级规则引擎（表驱动）
- **M5** core/market/bench：bench_run 事务 + JSON 解析 + 成绩存档
- **M6** core/local：本地扫描（两层/双布局/mmproj 归组/删除守卫）
- **M7** frontend MarketView：榜单/搜索/详情/已下载区 + 等级色标
- **M8** frontend 下载状态：进度订阅/暂停续传/失败就地显示
- **M9** 契约与设置：smoke 三处 + fixture + copy.js；设置页市场节
- **M10** 端到端联调：真实下载→启用→实测→删除全链路 + `build.ps1` 出 exe

## Out of Scope（一期）

- embedding / reranker 模型收录；精选推荐位；tok/s 静态估算；HF 镜像端点（实测 308 回源无价值）；>1 并发下载；非 GGUF 格式；HF gated 线上签署流程（仅提示+令牌）；魔搭 OAuth（令牌手填）；draft/投机解码模型的专门标注。

## Further Notes

实测证据（2026-10-25，本机）：HF API 0.86s / CDN 4.2 MB/s，魔搭 dolphin PUT 可用 / CDN 37.0 MB/s（8.8×）；两源 Range 206 均通；HF 匿名 gated 401（`X-Error-Code: GatedRepo`），魔搭 `LLM-Research/` 镜像匿名 200；魔搭排序 `SortBy:"DownloadsCount"` 严格降序验证通过；llama-bench v0.7.0-dev（b3fa69955）支持 `-o json`，本机参照 27B Q4_K_M 全 offload pp512=2235 / tg128=43.5 t/s；F 盘剩 1.07TB，`F:\AI_Model` 为子目录+平铺混合布局、无分片、有 `mmproj-` 前缀文件。已知风险与对策：KV 不入静态估算（依据行注明+实测补真）；魔搭偶发空响应（退避重试）；Intel 假显存（按厂商防御）；40GB 下载锁隔离（设计红线）。

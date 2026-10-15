# Spec: 从 CustomTkinter 迁移到 Tauri 2 + Vue 3 + Rust + NaiveUI

> 状态：草稿。由 grill 会话整理，决策依据见 `docs/adr/0001`–`0003`，术语见 `CONTEXT.md`。

## Problem Statement

llama_ctl 的呈现层是一份 2987 行的 CustomTkinter 单体，围绕它还有 1227 行手写的图形基础设施：一个逐帧 tick 的动画引擎（326 行）、一个手写 SVG 路径光栅化器（335 行）、566 行图标生成脚本。这些东西 tkinter 本该免费提供却没有——阴影、毛玻璃、CSS 级过渡、矢量图标——于是它们被一行一行补了出来，现在成了维护负担。

用户面对的具体问题是三重的：

1. **视觉与动效做不动**。想加一个效果要先在 `motion.py` 里写插值循环，再手工把颜色插值结果灌回 Tk 控件。每次主题切换都是一次手工重绘。
2. **代码已失控**。2987 行里绝大部分是 UI 装配与状态同步，视图与状态混在一起，改一处要担心碰坏另一处。
3. **分发体积**。PyInstaller 单文件 13 MB，且构建机全局环境（numpy / playwright / yt_dlp）会被误拖进包体，只能靠「每次构建新建干净 venv」这个约定来防御。

用户曾经以为自己还想要跨平台。但这个工具的领域层硬依赖 `nssm.exe`、`sc` 和 `powershell Get-CimInstance`，换前端框架并不能让它跑在 Linux 上——这一点已在 ADR-0003 中明确，跨平台收益不计入本次决策。

## Solution

把工具重写为 Tauri 2 桌面应用：

- **Rust 侧持有全部权威状态**，实现领域层（参数解析与语义等价、服务事实读取与控制、官方更新事务、预设与偏好持久化）。
- **Vue 3 + NaiveUI 只做呈现**：NaiveUI 仅作为组件地基（slider / select / modal / popover），视觉主题完全自定义，沿用现有 Apple 风的 token（圆角 12/8px、主色 `#0a84ff`、六级字阶 18/15/13/13/12/11、微软雅黑 UI + Cascadia Mono）。视觉对照见 `docs/design/naiveui-vs-current.html`。
- **单向数据流**：Rust 是真源，前端按需拉取全量 Snapshot；前端只在编辑期暂存表单值，点 Apply 才提交。这消灭了当前「前后端双份状态双向同步」导致的一致性 bug 类别。

分两期交付，先做可独立验收的领域层：

- **期一：Rust 化领域层**。移植 `params` / `nssm_adapter` / `updater` / `installer` / `presets` / `settings`，用 `cargo test` 覆盖。此时还没有前端，纯命令行可驱动。
- **期二：Vue 前端**。Rust 侧暴露 tauri command，前端接入 NaiveUI。

这样安排的理由是：领域层可以独立验收、独立保留回归网（现有 2278 行领域与 i18n 测试），做完再上前端；而且它能反证「代码失控」到底是结构问题还是框架问题——如果纯 Python 拆分就能解决，期二的收益会大幅缩水。

## User Stories

### 期一：领域层（无前端）

1. As a 开发者，I want `AppParameters` 的解析完全对齐 `CommandLineToArgvW` 的逐字节行为，so that 手写参数、其他工具生成的参数都能被正确切分（含 UNC 路径 `\\NAS\...` 反斜杠不吃掉、引号内反斜杠按 Windows 规则保留字面量）
2. As a 开发者，I want 负值参数（如随机种子 `-1`）被解析为值而非选项 flag，so that 现有行为不回归
3. As a 开发者，I want 别名（`-ngl` vs `--n-gpu-layers`）、顺序、缺省默认值、引号转义写法都不影响语义等价判定，so that 历史遗留配置不被误报为「未应用更改」
4. As a 开发者，I want 数值真差异、复选开关增删、未知参数增删仍被语义等价正确检出，so that 真改动不会被漏掉
5. As a 开发者，I want 滑块型字段缺失时自动回填默认值、越界值永不输出，so that 表单不会写出无效配置
6. As a 开发者，I want 冲突参数（`-c 4096 --ctx-size 131072`）在读取时报警并保留最后一项，写回时归一化为单一 `--ctx-size`，so that 这个已知 bug 在新实现里不复活
7. As a 运维人员，I want 服务事实（AppDirectory / AppParameters / Start 模式）走注册表直读，so that 读取不 spawn 任何子进程（现有硬指标：0 spawn）
8. As a 运维人员，I want 事实按服务名缓存、写回成功后才失效、写回失败时保留缓存，so that 不会读到陈旧状态也不会读到失败状态
9. As a 运维人员，I want 注册表不可读时回退到 `nssm get`，so that 非 NSSM 服务或权限不足时工具仍可用
10. As a 运维人员，I want 枚举本机所有 NSSM 服务，so that 顶部下拉能切换任意服务而不只是默认那个
11. As a 开发者，I want 枚举服务时的 `powershell` 调用显式带 `CREATE_NO_WINDOW`，so that 不闪控制台黑框
12. As a 开发者，I want NSSM 输出按 UTF-16LE、`sc` 输出按本地代码页（GBK）解码，按字节特征探测，so that 中文路径与中文服务名不乱码
13. As a 开发者，I want GBK 解码失败时容忍非法字节而不 panic，so that 个别畸形输出不会让整个工具崩掉（Rust 没有 Python `errors='replace'` 的宽容度，这一条必须显式实现）
14. As a 运维人员，I want 启停服务走 `sc`，so that 行为与当前一致
15. As a 运维人员，I want `/healthz` 探活，so that 重启后能确认服务真的就绪而不是只看到 START_PENDING
16. As a 运维人员，I want `server.err` 日志尾随，so that 出问题能看到 llama-server 自己的输出
17. As a 运维人员，I want 官方更新支持 `win-cuda-13.4-x64` / `win-cuda-12.4-x64` / `win-cpu-x64` / `win-vulkan-x64` 四条构建线，so that 能匹配本机硬件
18. As a 运维人员，I want 已停发的构建线（如 `win-cuda-13.3-x64`）从旧配置里读到时自动回退到默认线，so that 官方停发后旧配置不会卡死
19. As a 运维人员，I want 官方更新全程逐文件原子替换，任一步失败精确回滚已替换文件，so that 绝不留下半替换的二进制
20. As a 运维人员，I want 更新前把旧文件备份到带时间戳的目录，so that 回滚有据可依
21. As a 运维人员，I want 更新失败收尾时尽力重启服务，so that 绝不静默留下停摆的服务
22. As a 运维人员，I want 下载带重试与退避、已缓存的 zip 复用前先校验有效性，so that 坏缓存不会被当成有效资产（这是 `dc45c77` 修掉的 bug，不能回归）
23. As a 运维人员，I want 启动时后台清理陈旧的下载与备份目录、各保留最近 3 个、只删子目录不动普通文件、失败静默跳过，so that 磁盘不被长期累积
24. As a 运维人员，I want 更新进度日志逐行输出，so that 长事务有可见进展
25. As a 运维人员，I want 预设保存 / 载入 / 删除，跨服务复用，so that 不同模型配置能快速切换
26. As a 运维人员，I want 预设名已存在时保存为 no-op，so that 不会误覆盖已有预设
27. As a 运维人员，I want 载入预设只填表单不写服务，so that 载入是安全操作
28. As a 运维人员，I want 写回成功后同步覆盖当前同名预设，so that 预设不会与实际应用值漂移
29. As a 运维人员，I want 表单有未应用更改时切换服务或预设会先确认并提供自动备份，so that 编辑不丢
30. As a 开发者，I want 预设与设置的写入是原子写（临时文件 + rename），so that 崩溃不会留下半截 JSON
31. As a 开发者，I want 设置文件损坏时逐项回退默认值而不是整体丢弃，so that 一处损坏不会清空用户全部偏好
32. As a 开发者，I want 设置写入失败返回错误而非 panic，so that 目录只读时用户能看到提示而不是「看着生效、下次启动又变回去」
33. As a 开发者，I want `settings.json` 与 `presets.json` 存放在用户目录而非安装目录，so that 覆盖安装新版本不会清掉用户的预设与偏好（ADR-0002 的必需配套改动）

### 期二：前端

34. As a 运维人员，I want 顶部能切换服务，so that 一台机器上的多个 llama.cpp 服务都能管理
35. As a 运维人员，I want 数值参数用滑块、枚举参数用下拉，so that 不用手敲命令行参数
36. As a 运维人员，I want 每个参数旁有「?」按钮给出中文解释，说明该参数对性能/效果的影响与适用场景，so that 初学者不用查文档
37. As a 运维人员，I want 下拉切换选项时显示当前选项的解释，so that 选完就知道选了什么
38. As a 运维人员，I want 「?」悬停约 300ms 才触发、淡入 200ms，快速扫过不弹，so that 扫视参数列表时不被打断
39. As a 运维人员，I want 提示框移开后 0.8s 指数渐隐、渐隐途中移回立即恢复、同一时刻只显示一个，so that 提示不打架
40. As a 运维人员，I want 按钮 hover 高亮并在移出后 0.8s 渐隐回常态，so that 交互有反馈但不刺眼
41. As a 运维人员，I want 状态圆点在服务 RUNNING 期间呼吸、30s 无交互后自动静止，so that 有生命感又不持续分散注意
42. As a 运维人员，I want 7 个参数分组可折叠、默认展开前两组、展开状态在切换语言/主题后保留，so that 长表单能收起来
43. As a 运维人员，I want 应用更改前看到新旧参数对比并二次确认，so that 不会静默改动服务
44. As a 运维人员，I want 重启前二次确认，so that 不会误停线上的推理服务
45. As a 运维人员，I want 有未应用更改时看到明确提示，so that 知道表单和服务不一致
46. As a 运维人员，I want 还原按钮只在有未应用更改时可用，so that 不会出现无意义的还原动作
47. As a 运维人员，I want 开机自启切换二次确认、取消即不写入，so that 不会误改启动模式
48. As a 运维人员，I want 界面语言中英切换（参数详解保持中文），so that 双语用户都能用骨架界面
49. As a 运维人员，I want 外观跟随系统 / 强制浅色 / 强制深色，so that 能匹配使用环境
50. As a 运维人员，I want 动效总开关，关闭后所有动画直跳终态而功能不缺失，so that 低性能机器或厌动效的用户不受干扰
51. As a 运维人员，I want 设置页能看到官方更新区：当前版本、构建线选择、立即检查、立即更新，so that 更新在一处完成
52. As a 运维人员，I want 启动时自动检查官方更新但只提示不安装，so that 不会被静默升级
53. As a 运维人员，I want 发现新版本时看到更新日志再决定是否更新，so that 能判断要不要升
54. As a 运维人员，I want 立即更新前二次确认（含备份目录展示），so that 知道旧文件会去哪
55. As a 运维人员，I want 更新全过程日志实时滚动输出，so that 能盯着进度
56. As a 运维人员，I want 重启或官方更新进行中关闭窗口会弹确认，so that 不会误中断事务
57. As a 开发者，I want 强制退出时当前替换/回滚步骤仍执行完成，so that 事务不留半截
58. As a 操作员，I want 窗口几何在重启后恢复，so that 不用每次重摆窗口
59. As a 开发者，I want 前端资源全部随包分发、无 CDN、无运行时远程拉取、CSP 收紧，so that 高权限渲染进程不加载远端内容（ADR-0001）
60. As a 开发者，I want 官方更新的 zip 下载走 Rust 侧而非前端 fetch，so that 渲染进程不直接处理远端内容（ADR-0001）
61. As a 运维人员，I want 安装为 NSIS 安装包而非单文件 exe，so that 体积从 13 MB 降到 4–8 MB（ADR-0002，代价是失去绿色单文件）
62. As a 运维人员，I want 覆盖安装新版本后预设与偏好仍在，so that 升级不丢数据（ADR-0002 的配套）

## Implementation Decisions

**架构形状**：Rust 持真源，前端每次拉全量 Snapshot，单向、无状态竞争。前端不持有权威状态，只在编辑期暂存表单值。这条决策直接消灭了当前 tkinter 版的一类 bug——那份 bug 现在只能靠 `semantically_equal` 打补丁。

**两期交付**：期一 Rust 化领域层（无前端，可命令行驱动，可独立验收）；期二 Vue 前端。理由：领域层能独立保住回归网，且能反证「代码失控」是结构问题还是框架问题。

**依赖注入形状沿用现状**：现有 `installer.RealDeps` 已经把外部副作用（网络、文件、服务控制）全部参数化注入，测试传假实现即可在无 UI、无网络、无服务的环境下跑完整失败/回滚路径。Rust 侧照搬这个形状——一个 `Deps` trait 注入到 tauri command 层，而不是让领域函数直接调用系统 API。

**NaiveUI 只取组件，主题全自定义**：用 `n-slider` / `n-select` / `n-modal` / `n-popover` 省掉自绘组件，但 themeOverrides 完全按现有 token 写一份（圆角 12/8px、主色 `#0a84ff`、字阶 18/15/13/13/12/11、微软雅黑 UI + Cascadia Mono）。理由见 `docs/design/naiveui-vs-current.html` 的对照——NaiveUI 默认主题是 3px 圆角 + 绿色主色 + 14px 字阶，与现有设计语言不是一回事。

**Windows-only，不抽象服务后端**：不为 Linux/macOS 留 trait、seam 或 cfg 分支（ADR-0003）。所有 Windows 坑照单收下：UTF-16LE / GBK 按字节特征探测、`powershell` 调用带 `CREATE_NO_WINDOW`。

**整体管理员权限运行**：进程带 `requireAdministrator` manifest，不做按需 UAC、不做常驻提权 sidecar（ADR-0001）。代价是 WebView2 渲染进程也在高权限下，因此前端资源必须全本地 + CSP 收紧，官方更新下载走 Rust 侧。

**分发形态**：NSIS 安装包（ADR-0002）。**必需配套**：`settings.json` / `presets.json` 从程序侧路径迁到用户目录，否则覆盖安装会清掉用户数据——当前代码不满足，是迁移期必改项。

**工具自身不自更新**：只更新 llama.cpp，不代用户更新本工具。发布走 GitHub Release 手动下载。

**i18n 权威来源需提前约定**：前端 vue-i18n 一份文案，Rust 侧错误消息另一份。不约定就会漂移。待定：以 Rust 侧为权威、前端只做 key 查找。

**以下现有代码不迁移，直接删除**：`motion.py`（326 行手写 tick 动画 → CSS `@keyframes`）、`svgpath.py`（335 行手写 SVG 光栅化 → 内联 SVG）、`make_icons.py` + `make_icon.py`（442 行图标生成 → 静态 SVG 资源）。合计 1227 行（含 `icon.py` 124 行则 GUI 侧基础设施共 1351 行）。这是本次迁移最大的单项收益：不是迁移，是删除。

## Testing Decisions

**什么算好测试**：只测外部可观察行为，不测实现细节。现有 `test_nssm_facts.py` 是正面样板——它断言「第二次 `facts()` 调用不再读 reader」和「`_spawn_count == 0`」，而不是断言内部缓存字典的形状。Rust 侧测试沿用这个口味。

**接缝一：Rust 侧 `Deps` trait 注入到 tauri command 层。** 等价于现有 `RealDeps`。覆盖：

- `params`：解析 / 重建 / 语义等价（迁移 `test_params.py` 418 行）
- `nssm_adapter`：事实缓存与失效、0 spawn 断言、Start DWORD 映射、注册表不可读时回退（迁移 `test_nssm_facts.py` 145 行）
- `installer`：完整更新事务与失败回滚（迁移 `test_installer.py` 357 行）
- `updater`：资产选择、版本号解析、坏缓存校验、陈旧目录清理（迁移 `test_updater.py` 879 行）
- `presets` / `settings`：原子写、损坏回退、已存在预设 no-op（迁移 `test_presets.py` 128 + `test_preset_safety.py` 247 行）
- `strings`：双语文案完整性（迁移 `test_strings.py` 104 行）

迁移总量约 2278 行。**不迁的部分**：`test_motion.py`（444）、`test_first_paint.py`（61）、`test_font_tokens.py`（103）、`test_icon.py`（239）、`test_icons_assets.py`（146）合计 993 行——被测对象本身被 CSS/SVG 取代了，是退役而非迁移。

**接缝二：Vue 侧 mock `invoke`。** 组件测试用 vitest 打桩 tauri 的 IPC，断言表单渲染与交互行为（未应用更改提示的显隐、还原按钮可用性、确认对话框触发时机、折叠组状态保持）。

**不做 e2e**（不选 tauri-driver + WebDriver）：基建成本与 CI 时长不成比例，两个接缝已覆盖行为契约。

## Out of Scope

- **跨平台**。ADR-0003 明确不做，不抽象服务管理后端。
- **工具自更新**。只更新 llama.cpp；本工具自身走 GitHub Release 手动下载。
- **单文件绿色 exe**。ADR-0002 已选 NSIS 安装包。
- **按需 UAC 提权 / 常驻提权 sidecar**。ADR-0001 已选整体提权。
- **端到端测试**。见 Testing Decisions。
- **领域层之外的功能新增**。本次是重写，不是加功能；除 ADR 要求的配套改动（用户目录存储、CSP）外不加任何新特性。
- **纯 Python 拆分重构试探**。这是 grill 阶段提出的最短路径判别法（先不动技术栈把 2987 行按视图/状态/领域拆开，拆得动说明痛点是结构不是框架），但用户已选择直接全量重写，故本次不做。

## Further Notes

**最大的低估风险是 Windows 编码**。`nssm_adapter._run` 现在靠字节特征探测 UTF-16LE 与 GBK，并用 `errors="replace"` 兜住非法字节。Rust 的 `String::from_utf8` 不宽容，`encoding_rs` / `iconv` 也没有等价的一行兜底。这一块必须在期一早段做原型验证，否则会拖到后期才发现。

**261 个现有用例是本次迁移的回归网**（实测 `261 passed`，全绿）。迁移后 `cargo test` 应覆盖同等行为契约；领域部分 2278 行照搬，UI 部分 993 行退役。

**体积预期**：13 MB → 4–8 MB。NaiveUI 约 +300–500 KB gzipped，不影响结论。

**三个 ADR 各含一条会被无意破坏的硬约束**，验收时需逐条查：ADR-0001「别加 CDN 链接」、ADR-0002「settings/presets 必须在用户目录」、ADR-0003「不许为跨平台留 trait 或 cfg 分支」。

**术语消歧**（详见 `CONTEXT.md`）：Revert（用户主动还原表单）≠ Rollback（更新失败路径恢复文件）；Auto backup（预设的自动备份）≠ Backup（更新前的文件备份）；Fact（只读服务事实）≠ Snapshot（给前端的全量副本）。这四组在现有代码里混用，迁移时容易把语义带错。

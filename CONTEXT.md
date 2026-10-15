# llama_ctl 领域词汇表

一个接管 Windows 上由 NSSM 管理的 llama.cpp 服务的控制台。本文件只定义术语，不含实现决策（实现决策见 `docs/adr/`）。

## 服务与参数

**Service（服务）**：
被 NSSM 注册并托管的一个 Windows 服务，是本工具操作的唯一目标对象。一台机器上可有多个，用户通过顶部下拉切换。
_Avoid_: 进程、实例、server

**AppParameters**：
NSSM 中保存的、启动服务时交给 `llama-server.exe` 的原始命令行字符串。它是服务的**唯一真源**：本工具不另存一份服务参数。
_Avoid_: 配置、config、参数文件

**Field（字段）**：
AppParameters 中一个可辨识的逻辑参数（如 GPU 层数、上下文长度）及其呈现规则（滑块范围、枚举选项、默认值）。一个 Field 可有多个别名写法。
_Avoid_: 选项、参数项、控件

**Alias（别名）**：
同一 Field 的多种命令行写法（`-ngl` 与 `--n-gpu-layers`）。别名差异不构成配置差异。
_Avoid_: 短名、简写

**Fact（服务事实）**：
从系统**只读**取得的当前状态：服务运行状态、开机自启模式、安装目录、健康探测结果、已安装版本号。Fact 只能被读取，不能被本工具直接改写；改写必须经由一次 Apply。
_Avoid_: 状态、信息、snapshot

## 变更判定

**Semantic equivalence（语义等价）**：
两侧 AppParameters 各自解析为 Field 值后相等。别名、顺序、缺省默认值、引号与转义写法的差异**不影响**语义等价。
_Avoid_: 文本相同、diff

**Unapplied changes（未应用更改）**：
表单当前值与 AppParameters 的语义等价判定为「不等」。这是**唯一**决定是否提示、是否允许 Revert、是否在切换时触发自动备份的依据。
_Avoid_: 脏状态、dirty、已修改

**Apply（应用更改）**：
把表单值重建为 AppParameters 并写回服务。写回同时是**规范化**动作，因此 Apply 自身的「无变化」判定按文本而非语义等价。
_Avoid_: 保存、提交、同步

**Revert（还原）**：
丢弃表单改动，重新从 AppParameters 读回。不触碰服务。
_Avoid_: 撤销、undo、回滚（回滚属于更新流程，见下）

## 预设

**Preset（预设）**：
一套命名的 Field 值集合，本地保存、跨 Service 复用。Preset **不是**服务的状态——载入 Preset 只填表单，仍需 Apply 才生效。
_Avoid_: 配置档、profile、模板

**Auto backup（自动备份）**：
在表单有未应用更改时切换 Service 或 Preset，经确认后自动落地的 Preset，名字带时间戳。它不是文件备份。
_Avoid_: 备份（见下）

## 更新与备份

**Build variant（二进制版本）**：
官方发布的一条 Windows 构建线（`win-cuda-13.4-x64` / `win-cpu-x64` 等），决定下载哪个资产。用户选定并持久化。
_Avoid_: 通道、channel、版本（版本指已安装的构建号）

**Backup（备份）**：
更新前把 llama.cpp 目录下的旧文件复制到带时间戳的目录。**只指文件备份**，与 Preset 的 Auto backup 是两回事。
_Avoid_: 自动备份、快照

**Rollback（回滚）**：
更新过程任一步失败时，从 Backup 恢复被替换的文件并尽力重启服务。这是失败路径，不是用户可主动触发的操作。
_Avoid_: 还原（Revert 才是用户主动的还原）

## 呈现层

**Snapshot（快照）**：
某一时刻 Rust 侧完整状态的一次性全量副本，前端按需拉取。前端不持有权威状态，只在编辑期暂存表单值。
_Avoid_: 状态、模型、Fact

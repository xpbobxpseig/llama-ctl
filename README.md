# llama.cpp 服务控制台 (llama_ctl)

通用 GUI，直接接管由 NSSM 管理的**任意** llama.cpp 服务（默认 `QwenLLM`，顶部可切换）。

- 模型无关：支持 Qwen / Llama / DeepSeek / GLM 等任意开源 GGUF 模型
- 数值参数用**滑块**、枚举参数用**下拉**，每项带「?」按钮给出初学者友好的中文解释
- 直接读写 NSSM `AppParameters`（修掉 `-c` 与 `--ctx-size` 冲突）
- 启停 / 重启 / 开机自启切换、`/healthz` 探活、`server.err` 日志尾随
- 写回 / 重启均二次确认，先展新旧参数对比

## 启动

**推荐：双击 `dist\llama_ctl.exe`**（单文件，无需 Python 环境）。

开发方式运行：

```
cd F:\llama_ctl
python llama_ctl_gui.py
```

仅支持 Windows（依赖系统 `nssm.exe`、`sc`、`powershell`）。
重新打包：`python -m PyInstaller --onefile --noconsole --name llama_ctl --clean llama_ctl_gui.py`

## 控件说明

| 类型 | 呈现 | 字段示例 |
|------|------|----------|
| 滑块 | `CTkSlider` + 实时数值 | GPU 层数、上下文长度、并发槽、批大小、温度、min-p、线程 |
| 下拉 | `CTkOptionMenu`（预设名为可编辑 `CTkComboBox`） | 投机解码、KV cache 类型、Flash Attention、监听地址 |
| 复选 | `CTkCheckBox` | 禁用 mmap / 锁定内存 / 禁用 KV 卸载 / MoE 走 CPU |
| 文件 | `CTkEntry` + 浏览按钮 | 模型文件、视觉投影 |
| 文本 | `CTkEntry` | 别名、随机种子、端口 |

每个参数右侧有「?」按钮，点开看该参数对**性能 / 效果**的影响与适用场景；下拉项切换时也会在下方显示当前选项的解释。

## 参数预设（本地保存/加载）

工具支持把当前整套参数存为命名预设，跨服务复用（如「Qwen27B-128K」「DFlash 实验」）。预设名是一个**可编辑下拉框**（`CTkComboBox`，输入与选择合一）：

- **保存**：输入新名字 → 按回车或点击别处（失焦），表单所有字段值即写入 `F:\llama_ctl\presets.json`；名字已存在则不动作（避免误覆盖）。
- **载入**：下拉选已有预设 → 参数**即选即载**入表单（**不直接写回服务**，需再点「应用更改」写回；服务运行中会先二次确认再自动重启）。
- **删除**：下拉选预设 → 点右侧垃圾桶图标（二次确认）。
- **自动备份**：表单有未应用的更改时切换预设或服务，会先弹确认框；确认后自动把当前表单备份为「自动备份 月-日 时:分:秒」新预设，避免参数丢失。

「应用更改」把表单写回 NSSM `AppParameters`；「还原」重新读取服务当前参数覆盖表单。预设存于本地 `presets.json`，与具体 NSSM 服务解耦；切换不同服务时预设仍可用。

## 修复 / 通用化处理

- 原 NSSM 参数含冲突：`-c 4096 --ctx-size 131072`（`-c` 是 `--ctx-size` 别名）。读取弹红色告警并保留最后一项（`131072`），写回统一为单一 `--ctx-size`。
- 服务名通用：通过 `powershell Get-CimInstance` 列出本机所有 NSSM 服务，顶部下拉切换；不再硬编码 QwenLLM。
- 滑块型字段若原参数缺失，自动回填 `default`（范围由 FIELDS 定义），不输出越界值。
- 负数值参数（如随机种子 `-1`）正确解析为值而非选项 flag（pytest 覆盖）。
- 引号内反斜杠路径（如 `"F:\AI_Model\Qwen.gguf"`）按 Windows 引号规则保留字面量，不再被吞字符（pytest 覆盖）。

## 编码注意

NSSM 输出为 UTF-16LE（`sc` 为本地代码页 GBK）。工具按字节特征自动解码。

## 安全

- 写回 / 重启均弹二次确认，且先展示新旧参数对比；不会静默改动服务。
- 开机自启切换同样弹二次确认，取消即不写入。
- 表单有未应用的更改时切换服务 / 预设会先弹确认并支持自动备份为新预设，不会静默丢失参数。
- 工具不持有任何密钥 / token；`api-key` 不在本工具管理范围。

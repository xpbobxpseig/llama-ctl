#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
llama_ctl_gui.py — llama.cpp 服务控制台（通用版）

直接接管由 NSSM 管理的任意 llama.cpp 服务（默认 QwenLLM，可在顶部切换）：
  - 读取 / 写回 NSSM AppParameters（自动修掉 -c 与 --ctx-size 冲突）
  - 启停 / 重启服务、切换开机自启
  - /healthz 探活 + server.err 日志实时跟随
  - 所有核心参数以滑块 / 下拉呈现，每项带初学者友好的中文解释

设计原则：不 build、不 venv、不聊天、不探测二进制。只控制已部署服务。
通用性：模型无关，支持任意开源 GGUF / llama.cpp 服务。
"""

import os
import json
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from PIL import Image as PILImage
from tkinter import filedialog, messagebox, scrolledtext, ttk

from nssm_adapter import (
    NSSM_EXE, DEFAULT_SERVICE, get_app_parameters, set_app_parameters,
    get_start_mode, set_start_mode, sc_query_state, sc_action,
    list_nssm_services, check_health,
)

# ---------------------------------------------------------------------------
# 配置（本机固定事实）
# ---------------------------------------------------------------------------
APP_DIR = r"F:\llama.cpp"
# 日志路径无法从 exe 参数读出；默认指向 AppDirectory 下的 server.err，
# 若服务实际重定向到别处，可在下方 ERR_LOG 覆盖。
ERR_LOG = r"F:\llama.cpp\server.err"
GPU_COUNT = 1  # 本机 RTX 4090 x1；多卡时调大或改自动探测
# 预设文件：存命名参数组合（含全部字段 values），独立于具体服务。
# 统一固定到 F:\llama_ctl\presets.json：exe 在 dist\ 下运行也读写同一份，
# 避免「exe 换目录/升级后预设丢失」与双副本分裂。
PRESETS_FILE = r"F:\llama_ctl\presets.json"
CPU_THREADS = os.cpu_count() or 8

# ---------------------------------------------------------------------------
# 参数定义（通用核心参数）
# kind:
#   path   文件浏览
#   text   自由文本
#   combo  下拉（options 为 ["值", ...]，option_help 逐项解释）
#   check  复选（写回时带标志名，无值）
#   slider 滑块（min/max/step/unit）
# group: 仅用于 UI 分组标题
# ---------------------------------------------------------------------------
FIELDS = [
    # ---- 模型与视觉 ----
    {"key": "model", "group": "模型与视觉", "kind": "path",
     "label": "模型文件 (-m/--model)", "aliases": ["-m", "--model"],
     "help": "要加载的 GGUF 模型文件路径。这是最核心的参数——决定用哪个开源模型（如 Qwen、Llama、DeepSeek、GLM 等）。"
             " 模型越大、量化越高，占显存越多、效果与速度各异。路径必须是本机存在的 .gguf 文件。"},

    {"key": "mmproj", "group": "模型与视觉", "kind": "path",
     "label": "视觉投影 (--mmproj)", "aliases": ["--mmproj", "-mm"],
     "help": "多模态投影文件（.gguf）。仅当模型支持看图/传图时才需要，例如 Qwen-VL 类模型。"
             " 填了之后服务才能接收图片。纯文本模型留空即可。"},

    {"key": "alias", "group": "模型与视觉", "kind": "text",
     "label": "模型别名 (-a/--alias)", "aliases": ["-a", "--alias"],
     "help": "给模型起一个对外暴露的名字（逗号可分隔多个）。调用 OpenAI 兼容 API 时用它做 model 字段，方便区分。"
             " 例如 qwen3.8-27b。可留空，服务会用模型自带 id。"},

    # ---- 加速（GPU / 投机解码）----
    {"key": "ngl", "group": "加速", "kind": "slider",
     "label": "GPU 层数 (-ngl)", "aliases": ["-ngl", "--n-gpu-layers", "--gpu-layers"],
     "min": 0, "max": 200, "step": 1, "unit": "层",
     "default": 99,
     "help": "把多少层模型权重放到显卡显存里。数值越大越快（显存够时尽量拉满）。"
             " 设 0 = 纯 CPU 推理（极慢）。设 99 表示尽量全部上 GPU。"
             " 若显存不足会 OOM 崩溃，此时调小。效果无影响，只影响速度。"},

    {"key": "spec_type", "group": "加速", "kind": "combo",
     "label": "投机解码 (-spec-type)", "aliases": ["--spec-type"],
     "options": ["", "draft-mtp", "draft-eagle3", "draft-simple", "draft-dflash",
                 "draft-dspark", "ngram-simple", "ngram-map-k", "ngram-map-k4v",
                 "ngram-mod", "ngram-cache"],
     "option_help": {
         "": "不启用投机解码（标准单 token 生成）。",
         "draft-mtp": "MTP：用模型内置的『预测下一 token』头做草稿，提速明显，无需额外文件。推荐 27B 类模型。",
         "draft-eagle3": "EAGLE3 草稿模型：需配套 draft 模型文件，质量高但配置复杂。",
         "draft-simple": "简单草稿（同模型自预测），轻微提速。",
         "draft-dflash": "block-diffusion 草稿（DFlash2）：需配套的 draft 模型文件（用下方『草稿模型』填路径）。本机构建已支持，可试。",
         "draft-dspark": "DeepSeek 系 spark 草稿。",
         "ngram-simple": "n-gram 草稿：基于历史 token 的统计预测，零额外成本但提速有限。",
         "ngram-map-k": "n-gram（map-k 变体）。",
         "ngram-map-k4v": "n-gram（map-k4v 变体）。",
         "ngram-mod": "n-gram（mod 变体）。",
         "ngram-cache": "n-gram（cache 变体）。",
     },
     "help": "投机解码：让『草稿』先批量猜多个 token，主模型一次验证整批，从而提速。"
             " 常见选 draft-mtp（用模型自带的 MTP 头，无需额外文件）。"
             " 注意 MTP 会强制单槽（-np 1），且 LLM 类模型才有效；嵌入/小模型无需开。"},

    {"key": "spec_draft_model", "group": "加速", "kind": "path",
     "label": "草稿模型 (--spec-draft-model)", "aliases": ["--spec-draft-model", "-md", "--model-draft"],
     "help": "投机解码用的『草稿模型』GGUF 文件路径。仅当 spec-type 选 draft-* 时需要："
             " 例如 draft-dflash 要填 DFlash2 草稿文件，draft-eagle3 要填 EAGLE3 草稿文件。"
             " 填错或不填对应草稿文件，服务会启动失败。普通模式（none）留空即可。"},

    {"key": "spec_draft_n_max", "group": "加速", "kind": "slider",
     "label": "草稿长度 (--spec-draft-n-max)", "aliases": ["--spec-draft-n-max"],
     "min": 1, "max": 16, "step": 1, "unit": "tok", "default": 3,
     "help": "每次投机最多猜测的草稿 token 数。越大单次验证越多、提速潜力越高，但草稿质量下降可能反噬。"
             " 默认 3 通常够用；draft-dflash 可试 4~8。仅 draft/ngram 模式生效。"},

    # ---- 上下文与显存 ----
    {"key": "ctx_size", "group": "上下文与显存", "kind": "slider",
     "label": "上下文长度 (-ctx-size)", "aliases": ["--ctx-size", "-c"],
     "min": 512, "max": 1048576, "step": 512, "unit": "token",
     "default": 131072, "snap": [8192, 16384, 32768, 65536, 131072, 262144, 524288, 1048576],
     "quick": [32768, 65536, 131072, 262144, 524288, 1048576],
     "help": "上下文窗口大小，即可同时『记住』的最长对话长度（含历史）。"
             " 越大能处理的文档/对话越长，但占用显存越多、加载越慢。"
             " 常用档位：32K（轻量）/128K（本机 24G 稳妥）/256K（需配 KV 量化）/512K~1M（长文档，强烈建议 KV 量化）。"
             " 点下方快捷按钮即可一键跳到档位。注：旧参数里 '-c' 是 '--ctx-size' 简写，冲突时本工具只保留一个。"},

    {"key": "ctk", "group": "上下文与显存", "kind": "combo",
     "label": "KV cache 类型 K (-ctk)", "aliases": ["-ctk", "--cache-type-k"],
     "options": ["", "f16", "f32", "bf16", "q8_0", "q4_0", "q4_1", "iq4_nl", "q5_0", "q5_1"],
     "option_help": {
         "": "默认（f16，精度最高但最占显存）。",
         "f16": "16 位浮点，精度最高、显存占用最大。",
         "f32": "32 位浮点，精度最高、更占显存（一般没必要）。",
         "bf16": "bfloat16，精度接近 f32 但范围更稳，省显存略优于 f32。",
         "q8_0": "8 位量化，几乎无损、显存减半。",
         "q4_0": "4 位量化，显存大幅降低，长上下文首选，轻微精度损失。",
         "q4_1": "4 位量化变体。",
         "iq4_nl": "4 位重要性量化（non-linear），比 q4_0 更稳，省显存同时保持质量。",
         "q5_0": "5 位量化，介于 q4 与 q8 之间。",
         "q5_1": "5 位量化变体。",
     },
     "help": "KV cache 是『注意力记忆』的缓存。量化它能大幅省显存、支撑更长上下文，但精度略降。"
             " 长上下文（≥64K）强烈建议 q4_0 / iq4_nl / q8_0。ctk/ctv 通常设为一致。"},

    {"key": "ctv", "group": "上下文与显存", "kind": "combo",
     "label": "KV cache 类型 V (-ctv)", "aliases": ["-ctv", "--cache-type-v"],
     "options": ["", "f16", "f32", "bf16", "q8_0", "q4_0", "q4_1", "iq4_nl", "q5_0", "q5_1"],
     "option_help": {
         "": "默认（f16）。",
         "f16": "16 位浮点，精度最高。",
         "f32": "32 位浮点，最稳但最占显存。",
         "bf16": "bfloat16，省显存略优于 f32。",
         "q8_0": "8 位量化，近乎无损。",
         "q4_0": "4 位量化，省显存首选。",
         "q4_1": "4 位量化变体。",
         "iq4_nl": "4 位重要性量化，比 q4_0 更稳。",
         "q5_0": "5 位量化。",
         "q5_1": "5 位量化变体。",
     },
     "help": "KV cache 的 V（Value）部分类型。一般与 ctk 设成相同量化。见上方 ctk 说明。"},

    {"key": "flash_attn", "group": "上下文与显存", "kind": "combo",
     "label": "Flash Attention (-fa)", "aliases": ["-fa", "--flash-attn"],
     "options": ["auto", "on", "off"],
     "option_help": {
         "auto": "由 llama.cpp 自动判断是否启用（默认，最稳妥）。",
         "on": "强制开启。现代 NVIDIA 显卡开启后更省显存、更快。",
         "off": "关闭。极少数老卡或异常时回退用。",
     },
     "help": "Flash Attention 是一种更高效的注意力计算方式：更快、更省显存。"
             " 现代显卡（如 RTX 40 系）建议 on；不确定就 auto。"},

    # ---- 并发与吞吐 ----
    {"key": "parallel", "group": "并发与吞吐", "kind": "slider",
     "label": "并发槽数 (-np)", "aliases": ["-np", "--parallel"],
     "min": 1, "max": 16, "step": 1, "unit": "槽",
     "default": 1,
     "help": "服务能同时处理的请求『槽位』数。1 = 单用户独占；调大可并发服务多人，但每个槽都占显存/上下文。"
             " 开投机解码(MTP)时会被强制为 1。普通个人使用设 1~4。"},

    {"key": "batch_size", "group": "并发与吞吐", "kind": "slider",
     "label": "批大小 (-b)", "aliases": ["-b", "--batch-size"],
     "min": 128, "max": 8192, "step": 128, "unit": "tok",
     "default": 2048,
     "help": "一次处理的最大逻辑 token 批量。影响吞吐（多人/长提示时）。调太大占显存。"
             " 默认 2048 通常够用；若要更高并发可适度上调。"},

    {"key": "ubatch_size", "group": "并发与吞吐", "kind": "slider",
     "label": "物理批大小 (-ub)", "aliases": ["-ub", "--ubatch-size"],
     "min": 64, "max": 2048, "step": 64, "unit": "tok",
     "default": 512,
     "help": "物理批大小，配合 batch-size 使用。一般保持为 batch 的约 1/4。默认 512 即可，调参会同时带动吞吐与显存。"},

    {"key": "threads", "group": "并发与吞吐", "kind": "slider",
     "label": "CPU 线程 (-t)", "aliases": ["-t", "--threads"],
     "min": 1, "max": max(CPU_THREADS, 8), "step": 1, "unit": "线程",
     "default": CPU_THREADS,
     "help": "生成时使用的 CPU 线程数。仅在部分计算落到 CPU 时影响速度（如 ngl 没拉满）。"
             " 一般设为本机物理核心数；全 GPU 推理时影响不大。"},

    # ---- 采样（生成质量）----
    {"key": "temperature", "group": "采样", "kind": "slider",
     "label": "温度 (--temp)", "aliases": ["--temp", "--temperature"],
     "min": 0, "max": 2, "step": 0.05, "unit": "",
     "default": 0.8,
     "help": "随机性。低（0.2）= 更确定、更死板；高（1.0+）= 更发散、更有创意但易跑题。"
             " 日常对话 0.7~0.9；代码/事实问答可调低到 0.2~0.5；0 = 贪心（最确定）。"},

    {"key": "min_p", "group": "采样", "kind": "slider",
     "label": "min-p (--min-p)", "aliases": ["--min-p"],
     "min": 0, "max": 0.5, "step": 0.01, "unit": "",
     "default": 0.05,
     "help": "最低概率阈值：只从累计概率足够高的候选里采样，过滤垃圾 token。"
             " 0.05 是 llama.cpp 默认；调高更『保守』，调 0 关闭。与 temperature 配合控制质量。"},

    {"key": "top_k", "group": "采样", "kind": "slider",
     "label": "top-k (--top-k)", "aliases": ["--top-k"],
     "min": 0, "max": 100, "step": 1, "unit": "", "default": 40,
     "help": "只从概率最高的前 k 个候选里采样。k 越小输出越聚焦、越可预测；k 越大越发散。"
             " 默认 40；设 0 = 关闭 top-k（只看 top-p）。与 top-p 叠加使用，共同限制候选集。"},

    {"key": "top_p", "group": "采样", "kind": "slider",
     "label": "top-p (--top-p)", "aliases": ["--top-p"],
     "min": 0, "max": 1, "step": 0.01, "unit": "", "default": 0.95,
     "help": "核采样：只从累计概率达 p 的最小候选集里采样。p 越小越保守（如 0.9 只取覆盖 90% 概率的词），"
             " p=1.0 = 关闭。默认 0.95。与 top-k 配合：先按 top-k 截前 k 个，再在其中按 top-p 截概率。"},

    {"key": "seed", "group": "采样", "kind": "text",
     "label": "随机种子 (-s)", "aliases": ["-s", "--seed"],
     "help": "随机种子。固定一个整数可让生成『可复现』（同样输入同样输出）。-1 = 每次随机。调试/评测时设固定值，日常留空或 -1。"},

    {"key": "jinja", "group": "采样", "kind": "check",
     "label": "Jinja 模板 (--jinja)", "aliases": ["--jinja"],
     "help": "启用服务端 Jinja 聊天模板渲染。参考配置（Qwen 官方示例）均带 --jinja，"
             " 能正确套用模型的对话/思考模板。本服务也应勾上，否则可能用错模板导致格式异常。"},

    {"key": "chat_template_kwargs", "group": "采样", "kind": "text",
     "label": "模板参数 (--chat-template-kwargs)", "aliases": ["--chat-template-kwargs"],
     "help": "传给聊天模板的 JSON 参数，控制推理行为。Qwen3.8 常用："
             " 关思考 '{\"enable_thinking\":false}'；调推理强度 '{\"reasoning_effort\":\"low|medium|xhigh\"}'"
             "（默认 xhigh，无 high/max）。需写合法 JSON，含花括号与引号。留空=默认。"},

    # ---- 网络 ----
    {"key": "host", "group": "网络", "kind": "combo",
     "label": "监听地址 (--host)", "aliases": ["--host"],
     "options": ["127.0.0.1", "0.0.0.0", "localhost"],
     "option_help": {
         "127.0.0.1": "仅本机可访问（最安全，推荐个人使用）。",
         "0.0.0.0": "监听所有网卡，局域网/外网其他机器也能连（注意安全风险，需配 api-key）。",
         "localhost": "等价本机回环。",
     },
     "help": "服务监听哪个网络地址。个人单机用 127.0.0.1 最安全；要让手机/其他电脑访问才用 0.0.0.0（务必同时设 api-key）。"},

    {"key": "port", "group": "网络", "kind": "text",
     "label": "端口 (--port)", "aliases": ["--port"],
     "help": "服务监听的端口。默认 8080。若被占用就改一个（如 8081）。客户端连 http://地址:端口/v1 。"},

    # ---- 高级开关 ----
    {"key": "no_mmap", "group": "高级", "kind": "check",
     "label": "禁用 mmap (--no-mmap)", "aliases": ["--no-mmap"],
     "help": "关闭内存映射加载。默认用 mmap 加载更快更省内存；某些特殊环境才需要关掉（会变慢）。一般保持关闭此选项。"},

    {"key": "mlock", "group": "高级", "kind": "check",
     "label": "锁定内存 (--mlock)", "aliases": ["--mlock"],
     "help": "强制把模型锁在物理内存，避免被系统换页到磁盘导致卡顿。仅在内存充足时有意义；本机显存/GPU 推理一般无需开。"},

    {"key": "no_kv_offload", "group": "高级", "kind": "check",
     "label": "禁用 KV 卸载 (--no-kv-offload)", "aliases": ["--no-kv-offload"],
     "help": "不让 KV cache 卸载到 GPU（强制留 CPU）。仅在你明确想压低显存、牺牲速度时启用。常规使用保持关闭。"},

    {"key": "cpu_moe", "group": "高级", "kind": "check",
     "label": "MoE 走 CPU (--cpu-moe)", "aliases": ["--cpu-moe"],
     "help": "MoE（混合专家）模型把专家权重留在 CPU。仅 MoE 架构模型（如 Qwen-MoE、DeepSeek-MoE）相关；非 MoE 模型忽略。显存不够时可用，但会慢。"},
]
ALIAS_TO_KEY = {}
for _f in FIELDS:
    for _a in _f["aliases"]:
        ALIAS_TO_KEY[_a] = _f["key"]




# ---------------------------------------------------------------------------
# 参数解析 / 重建
# ---------------------------------------------------------------------------
def split_args(text):
    """按空格切分参数，正确处理双引号包裹（支持 \\" 转义）。

    不用 shlex：shlex posix=False 不处理引号（含空格 JSON 会崩），
    posix=True 又会把 Windows 路径的 \\ 当转义。自研切分兼顾两者。
    """
    out, i, n = [], 0, len(text or "")
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c == '"':
            j, buf = i + 1, ""
            while j < n:
                if text[j] == "\\" and j + 1 < n:
                    buf += text[j + 1]
                    j += 2
                    continue
                if text[j] == '"':
                    break
                buf += text[j]
                j += 1
            out.append(buf)
            i = j + 1
        else:
            j = i
            while j < n and not text[j].isspace():
                j += 1
            out.append(text[i:j])
            i = j
    return out


def parse_params(text):
    """解析 NSSM AppParameters 为 (values: dict, extras: list, warnings: list)。

    -c 与 --ctx-size 冲突：保留最后一项并告警；滑块型数值缺失则取 default。
    check 型（如 --no-mmap）无值，记为值 "1"。
    """
    values = {f["key"]: "" for f in FIELDS}
    extras = []
    warnings = []
    tokens = split_args(text) if text else []
    i, n = 0, len(tokens)
    ctx_seen = []
    while i < n:
        tok = tokens[i]
        if tok in ALIAS_TO_KEY:
            key = ALIAS_TO_KEY[tok]
            fld = next(f for f in FIELDS if f["key"] == key)
            if fld["kind"] == "check":
                values[key] = "1"
                i += 1
                continue
            if i + 1 < n and not tokens[i + 1].startswith("-"):
                val = tokens[i + 1]
                i += 2
            else:
                val = ""
                i += 1
            if key == "ctx_size":
                ctx_seen.append(val)
            values[key] = val
        else:
            extras.append(tok)
            i += 1
    # 滑块默认值回填（解析到的若为空或越界则用 default）；整数 step 字段规范化去 .0
    for fld in FIELDS:
        if fld["kind"] == "slider":
            v = values[fld["key"]].strip()
            int_step = float(fld["step"]).is_integer()
            if v == "" or not _is_number(v):
                dflt = fld.get("default", fld["min"])
                values[fld["key"]] = str(int(dflt)) if int_step else str(dflt)
            else:
                num = float(v)
                lo, hi = fld["min"], fld["max"]
                if num < lo or num > hi:
                    warnings.append(f"{fld['label']} 值 {v} 超出范围[{lo},{hi}]，已回退默认。")
                    dflt = fld.get("default", lo)
                    values[fld["key"]] = str(int(dflt)) if int_step else str(dflt)
                else:
                    values[fld["key"]] = str(int(num)) if int_step else str(num)
    if len(ctx_seen) > 1:
        warnings.append(
            f"检测到冲突：-c 与 --ctx-size 同时出现 {len(ctx_seen)} 次，"
            f"已保留最后一项 '{ctx_seen[-1]}'（llama.cpp 以最后为准）。"
        )
    return values, extras, warnings


def _is_number(s):
    try:
        float(s)
        return True
    except ValueError:
        return False


def build_params(values, extras):
    """由字段字典 + extras 重建 AppParameters。

    顺序：FIELDS 顺序输出有值字段（统一长名）。check 型仅当值为真输出标志名。
    滑块/数值/文本为空则跳过。combo 空字符串跳过。
    """
    out = []
    st = (values.get("spec_type") or "").strip()
    for fld in FIELDS:
        key = fld["key"]
        v = (values.get(key) or "").strip()
        # 草稿相关字段仅在投机解码（draft-*）模式下输出，避免普通/ngram 模式带无效参数
        if key.startswith("spec_draft") and not st.startswith("draft"):
            continue
        if fld["kind"] == "check":
            if v in ("1", "true", "on", "yes"):
                out.append(fld["aliases"][-1])
            continue
        if not v:
            continue
        if fld["kind"] == "combo" and v == "":
            continue
        primary = max(fld["aliases"], key=len)
        out.append(primary)
        out.append(v)
    out.extend(extras)
    def _quote(t):
        # 含空格/引号/花括号的值才用双引号包裹（Windows 路径含 \\ 但不含这些，不包裹）
        # 包裹时若内部含 \\ 或 " 再转义，保证 JSON 等可往返
        if any(ch in t for ch in (' ', '"', '{', '}')):
            return '"' + t.replace("\\", "\\\\").replace('"', '\\"') + '"'
        return t
    return " ".join(_quote(t) for t in out)


# ---------------------------------------------------------------------------
# 预设（命名参数组合，本地 JSON）
# ---------------------------------------------------------------------------
def load_presets():
    """读取预设字典 {name: {key: value}}。文件不存在/损坏返回空字典。"""
    try:
        with open(PRESETS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except FileNotFoundError:
        return {}
    except Exception:  # noqa: BLE001
        return {}
    return {}


def save_presets(presets):
    """写回预设字典到 PRESETS_FILE（原子写：先临时文件再替换）。"""
    tmp = PRESETS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(presets, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PRESETS_FILE)


# ---------------------------------------------------------------------------
# 预设（命名参数组合，本地 JSON）
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# GUI（CustomTkinter）
# ---------------------------------------------------------------------------
import customtkinter as ctk

# 设计基线：Apple 风浅色 —— 中性灰白底、去饱和系统蓝强调、轻分隔、大留白
C_BG = "#f5f5f7"       # 窗口底（Apple 灰白）
C_CARD = "#ffffff"     # 卡片底（纯白）
C_BORDER = "#e3e3e8"   # 轻分隔线
C_FIELD = "#fafafa"    # 输入框/下拉内底
C_TXT = "#1d1d1f"      # 主文本（Apple 近黑）
C_MUT = "#86868b"      # 次要文本
C_ACC = "#0a84ff"      # 强调色（系统蓝，唯一）
C_ACCH = "#0071e3"     # 强调 hover
C_RED = "#ff3b30"      # Apple 红
C_ORG = "#ff9500"      # Apple 橙
C_GRAY = "#aeaeb2"
C_TIP = "#f0f0f2"      # 提示框底（浅灰）

F_BODY = ("Microsoft YaHei UI", 13)
F_SMALL = ("Microsoft YaHei UI", 12)
F_TITLE = ("Microsoft YaHei UI", 18, "bold")
F_GROUP = ("Microsoft YaHei UI", 12, "bold")


class _HelpTip:
    """问号按钮 hover 提示：鼠标指到即显示，移开即隐藏，无需点击或关闭。"""
    def __init__(self, widget, text_fn):
        self.widget = widget
        self.text_fn = text_fn          # 延迟取值，内容始终最新
        self.win = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)
        widget.bind("<Button-1>", self._hide)   # 万一点击也立即收起

    def _show(self, _=None):
        if self.win is not None:
            return
        text = self.text_fn()
        if not text:
            return
        win = tk.Toplevel(self.widget)
        win.overrideredirect(True)
        win.wm_attributes("-topmost", True)
        fr = ctk.CTkFrame(win, fg_color=C_TIP, corner_radius=10,
                          border_width=1, border_color=C_BORDER)
        fr.pack(padx=0, pady=0)
        ctk.CTkLabel(fr, text=text, font=F_SMALL, text_color=C_TXT,
                     justify="left", anchor="w", wraplength=420,
                     padx=12, pady=8).pack()
        x = self.widget.winfo_rootx() + self.widget.winfo_width() + 6
        y = self.widget.winfo_rooty()
        win.geometry(f"+{x}+{y}")
        self.win = win

    def _hide(self, _=None):
        if self.win is not None:
            self.win.destroy()
            self.win = None


class ControlGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        if sys.platform != "win32":
            messagebox.showerror("不支持", "本工具仅支持 Windows（依赖 NSSM / sc / powershell）。")
            self.destroy()
            return
        ctk.set_appearance_mode("light")
        self.title("llama.cpp 服务控制台")
        try:
            self.iconbitmap(os.path.join(os.path.dirname(os.path.abspath(__file__)), "llama_icon.ico"))
        except Exception:  # noqa: BLE001 - 图标缺失不阻断启动
            pass
        self.geometry("1000x860")
        self.minsize(920, 720)
        self.configure(fg_color=C_BG)

        self.service = DEFAULT_SERVICE
        self.values = {f["key"]: "" for f in FIELDS}
        self.extras = []
        self.var = {}
        self.widgets = {}
        self.val_labels = {}
        self._stop_poll = False

        self._build_widgets()
        self.refresh_all()
        self._start_polling()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---- 通用小组件 ----
    def _btn(self, parent, text, cmd, kind="ghost"):
        """kind: primary / ghost / danger-text"""
        kw = dict(font=F_BODY, corner_radius=8, height=32)
        if kind == "primary":
            kw.update(fg_color=C_ACC, hover_color=C_ACCH, text_color="#ffffff")
        elif kind == "danger":
            kw.update(fg_color="transparent", hover_color="#fdeceb",
                      text_color=C_RED, border_width=1, border_color=C_BORDER)
        else:
            kw.update(fg_color="transparent", hover_color=C_CARD,
                      text_color=C_TXT, border_width=1, border_color=C_BORDER)
        return ctk.CTkButton(parent, text=text, command=cmd, **kw)

    def _card(self, parent, title=None, expand=False):
        fr = ctk.CTkFrame(parent, fg_color=C_CARD, corner_radius=14,
                          border_width=1, border_color=C_BORDER)
        fr.pack(fill="both" if expand else "x", expand=expand, padx=12, pady=(6, 0))
        inner = ctk.CTkFrame(fr, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=14, pady=12)
        if title:
            ctk.CTkLabel(inner, text=title, font=F_GROUP, text_color=C_MUT,
                         anchor="w").pack(fill="x", pady=(0, 8))
        return inner

    # ---- 布局 ----
    def _build_widgets(self):
        # 头部：标题 + 服务选择
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(14, 2))
        ctk.CTkLabel(head, text="llama.cpp 服务控制台", font=F_TITLE,
                     text_color=C_TXT).pack(side="left")
        svc = ctk.CTkFrame(head, fg_color="transparent")
        svc.pack(side="right")
        ctk.CTkLabel(svc, text="服务", font=F_BODY, text_color=C_MUT).pack(side="left", padx=(0, 6))
        self.service_var = tk.StringVar(value=self.service)
        self.cmb_service = ctk.CTkOptionMenu(svc, variable=self.service_var,
                                             values=list_nssm_services(),
                                             width=170, font=F_BODY,
                                             fg_color=C_CARD, button_color=C_BORDER,
                                             button_hover_color=C_ACC,
                                             text_color=C_TXT,
                                             command=lambda v: self.on_service_change())
        self.cmb_service.pack(side="left")

        # 状态条（单行：状态 + 探活 + 自启 + 控制按钮）
        st = self._card(self)
        row = ctk.CTkFrame(st, fg_color="transparent")
        row.pack(fill="x")
        self.lbl_state = ctk.CTkLabel(row, text="服务 —", font=F_BODY, text_color=C_MUT)
        self.lbl_state.pack(side="left")
        self.lbl_health = ctk.CTkLabel(row, text="探活 —", font=F_BODY, text_color=C_MUT)
        self.lbl_health.pack(side="left", padx=(18, 0))
        ctk.CTkLabel(row, text="开机自启", font=F_SMALL, text_color=C_MUT
                     ).pack(side="left", padx=(24, 6))
        self.auto_var = tk.StringVar(value="手动")
        self.opt_auto = ctk.CTkOptionMenu(row, variable=self.auto_var,
                                          values=["自动(开机)", "手动", "禁用"],
                                          width=130, height=30, font=F_BODY,
                                          fg_color=C_FIELD, button_color=C_BORDER,
                                          button_hover_color=C_ACC, text_color=C_TXT,
                                          command=lambda v: self.apply_auto())
        self.opt_auto.pack(side="left")
        act = ctk.CTkFrame(row, fg_color="transparent")
        act.pack(side="right")
        self._btn(act, "启动", lambda: self.do_action("start")).pack(side="left", padx=3)
        self._btn(act, "停止", lambda: self.do_action("stop"), kind="danger").pack(side="left", padx=3)
        self._btn(act, "重启", self.do_restart).pack(side="left", padx=3)

        # 预设区（单行：标题 + 可编辑下拉 + 删除图标；右侧 应用更改/还原）
        pr = self._card(self)
        prow = ctk.CTkFrame(pr, fg_color="transparent")
        prow.pack(fill="x")
        ctk.CTkLabel(prow, text="参数预设", font=F_GROUP, text_color=C_MUT).pack(side="left")
        self.lbl_dirty = ctk.CTkLabel(prow, text="", font=F_SMALL, text_color=C_ORG)
        self.lbl_dirty.pack(side="left", padx=12)
        self._btn(prow, "还原", self.load_params).pack(side="right")
        self._btn(prow, "应用更改", self.apply_changes, kind="primary").pack(side="right", padx=(0, 8))
        base = getattr(sys, "frozen", False) and os.path.dirname(os.path.abspath(sys.executable)) \
            or os.path.dirname(os.path.abspath(__file__))
        try:
            ic_del = ctk.CTkImage(PILImage.open(os.path.join(base, "ic_trash.png")), size=(18, 18))
        except Exception:  # noqa: BLE001 - 图标缺失退化为文字
            ic_del = None
        self.preset_var = tk.StringVar()
        self.cmb_preset = ctk.CTkComboBox(prow, variable=self.preset_var, values=[],
                                          width=300, font=F_BODY,
                                          fg_color=C_FIELD, border_color=C_BORDER,
                                          button_color=C_BORDER,
                                          text_color=C_TXT,
                                          command=lambda v: self.on_preset_selected(v))
        self.cmb_preset.pack(side="left", padx=(14, 6))
        self.cmb_preset.bind("<Return>", lambda e: self._on_preset_committed())
        self.cmb_preset.bind("<FocusOut>", lambda e: self._on_preset_committed())
        if ic_del:
            self._btn(prow, "", self.delete_preset, kind="danger").configure(image=ic_del, width=34)
        else:
            self._btn(prow, "删除", self.delete_preset, kind="danger")
        self.refresh_presets()
        self.refresh_presets()

        # 参数区（滚动卡片，占最大纵向空间）
        pcfr = ctk.CTkFrame(self, fg_color=C_CARD, corner_radius=14,
                            border_width=1, border_color=C_BORDER)
        pcfr.pack(fill="both", expand=True, padx=12, pady=(6, 0))
        pc = ctk.CTkFrame(pcfr, fg_color="transparent")
        pc.pack(fill="both", expand=True, padx=14, pady=12)
        phead = ctk.CTkFrame(pc, fg_color="transparent")
        phead.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(phead, text="启动参数", font=F_GROUP, text_color=C_MUT,
                     anchor="w").pack(side="left")
        self.scroll = ctk.CTkScrollableFrame(pc, fg_color="transparent",
                                             scrollbar_button_color=C_GRAY,
                                             scrollbar_button_hover_color=C_GRAY)
        self.scroll.pack(fill="both", expand=True)
        self.scroll.grid_columnconfigure(2, weight=1)
        row_i = 0
        last_group = None
        for fld in FIELDS:
            g = fld.get("group")
            if g != last_group:
                sep = ctk.CTkFrame(self.scroll, fg_color=C_BORDER, height=1)
                if last_group is not None:
                    sep.grid(row=row_i, column=0, columnspan=4, sticky="ew", pady=(10, 2))
                    row_i += 1
                ctk.CTkLabel(self.scroll, text=g, font=F_GROUP, text_color=C_ACC,
                             anchor="w").grid(row=row_i, column=0, columnspan=4,
                                              sticky="w", pady=(6, 4))
                row_i += 1
                last_group = g
            row_i = self._build_field(self.scroll, fld, row_i)

        # combo 选项实时解释行
        self.lbl_hint = ctk.CTkLabel(pc, text="", font=F_SMALL, text_color=C_MUT,
                                     anchor="w", wraplength=880, justify="left")
        self.lbl_hint.pack(fill="x", pady=(8, 0))

        # 日志（可折叠，默认收起，把空间留给启动参数）
        self._log_open = tk.BooleanVar(value=False)
        lg = ctk.CTkFrame(self, fg_color=C_CARD, corner_radius=14)
        lg.pack(fill="x", padx=12, pady=(6, 0))
        head = ctk.CTkFrame(lg, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(10, 4))
        self.btn_log_toggle = ctk.CTkButton(
            head, text="日志尾随 server.err（已折叠）", font=F_GROUP,
            text_color=C_MUT, anchor="w", fg_color="transparent",
            hover_color=C_BG, command=self.toggle_log)
        self.btn_log_toggle.pack(side="left")
        self.txt_log = ctk.CTkTextbox(lg, height=170, font=("Consolas", 11),
                                      fg_color=C_FIELD, border_width=1,
                                      border_color=C_BORDER, wrap="none")
        self.txt_log.configure(state="disabled")
        # 默认不打包日志区，仅头部行
        # 警告行（解析告警）挂在日志折叠条下方
        self.lbl_warn = ctk.CTkLabel(self, text="", font=F_SMALL, text_color=C_ORG,
                                     anchor="w", wraplength=900, justify="left")
        self.lbl_warn.pack(fill="x", padx=16, pady=(2, 8))

    def _build_field(self, parent, fld, row):
        key = fld["key"]
        btn = ctk.CTkButton(parent, text="?", width=26, height=26, corner_radius=13,
                            font=F_SMALL, fg_color="transparent", border_width=1,
                            border_color=C_BORDER, hover_color=C_CARD, text_color=C_MUT,
                            cursor="question_arrow")
        btn.grid(row=row, column=0, padx=(0, 8), pady=4)
        _HelpTip(btn, lambda k=key: self._help_text(k))

        v = tk.StringVar()
        self.var[key] = v

        if fld["kind"] == "slider":
            iv = tk.DoubleVar()
            self.var[key] = iv
            ctk.CTkLabel(parent, text=fld["label"], font=F_BODY, text_color=C_TXT,
                         anchor="w").grid(row=row, column=1, sticky="w", padx=2)
            n_steps = max(int(round((fld["max"] - fld["min"]) / fld["step"])), 1)
            w = ctk.CTkSlider(parent, variable=iv, from_=fld["min"], to=fld["max"],
                              number_of_steps=n_steps, width=300,
                              button_color=C_ACC, button_hover_color=C_ACCH,
                              progress_color=C_ACC,
                              command=lambda val, k=key: self._on_slide(k, val))
            w.grid(row=row, column=2, sticky="w", padx=4, pady=6)
            self.widgets[key] = w
            lbl = ctk.CTkLabel(parent, text="", font=("Consolas", 12), text_color=C_MUT,
                               width=110, anchor="w")
            lbl.grid(row=row, column=3, sticky="w")
            self.val_labels[key] = lbl
            row += 1
            # 快捷档位按钮（仅定义了 quick 的字段，如上下文长度）
            if fld.get("quick"):
                qfr = ctk.CTkFrame(parent, fg_color="transparent")
                qfr.grid(row=row, column=1, columnspan=3, sticky="w", padx=2, pady=(0, 4))
                ctk.CTkLabel(qfr, text="快捷：", font=F_SMALL, text_color=C_MUT
                             ).pack(side="left")
                for qv in fld["quick"]:
                    txt = self._fmt_ctx(qv)
                    ctk.CTkButton(qfr, text=txt, font=F_SMALL, width=64, height=26,
                                  corner_radius=8, fg_color=C_FIELD, hover_color=C_CARD,
                                  border_width=1, border_color=C_BORDER,
                                  text_color=C_TXT,
                                  command=lambda val=qv, k=key: self._set_ctx(k, val)
                                  ).pack(side="left", padx=(3, 0))
            return row + 1

        if fld["kind"] == "combo":
            ctk.CTkLabel(parent, text=fld["label"], font=F_BODY, text_color=C_TXT,
                         anchor="w").grid(row=row, column=1, sticky="w", padx=2)
            cv = tk.StringVar()
            self.var[key] = cv
            opts = [o if o else "（空）" for o in fld["options"]]
            w = ctk.CTkOptionMenu(parent, variable=cv, values=opts, width=220,
                                  font=F_BODY, fg_color=C_FIELD, button_color=C_BORDER,
                                  button_hover_color=C_ACC, text_color=C_TXT,
                                  command=lambda val, k=key: self._update_combo_hint(k))
            w.grid(row=row, column=2, sticky="w", padx=4, pady=6)
            # 空值映射：显示（空）时变量实际置 ""
            self._combo_map = getattr(self, "_combo_map", {})
            self._combo_map[key] = {o: orig for o, orig in zip(opts, fld["options"])}
            self.widgets[key] = w
            return row + 1

        if fld["kind"] == "check":
            w = ctk.CTkCheckBox(parent, text=fld["label"], variable=v,
                                onvalue="1", offvalue="", font=F_BODY,
                                text_color=C_TXT, fg_color=C_ACC,
                                hover_color=C_ACCH, border_color=C_BORDER,
                                corner_radius=6)
            w.grid(row=row, column=1, columnspan=2, sticky="w", padx=2, pady=6)
            self.widgets[key] = w
            return row + 1

        if fld["kind"] == "path":
            ctk.CTkLabel(parent, text=fld["label"], font=F_BODY, text_color=C_TXT,
                         anchor="w").grid(row=row, column=1, sticky="w", padx=2)
            w = ctk.CTkEntry(parent, textvariable=v, width=430, font=F_BODY,
                             fg_color=C_FIELD, border_color=C_BORDER)
            w.grid(row=row, column=2, sticky="ew", padx=4, pady=6)
            self._btn(parent, "浏览", lambda k=key: self._browse(k)).grid(
                row=row, column=3, sticky="w", padx=4)
            self.widgets[key] = w
            return row + 1

        # text
        ctk.CTkLabel(parent, text=fld["label"], font=F_BODY, text_color=C_TXT,
                     anchor="w").grid(row=row, column=1, sticky="w", padx=2)
        w = ctk.CTkEntry(parent, textvariable=v, width=430, font=F_BODY,
                         fg_color=C_FIELD, border_color=C_BORDER)
        w.grid(row=row, column=2, sticky="ew", padx=4, pady=6)
        self.widgets[key] = w
        return row + 1

    def _fmt_ctx(self, num):
        if num >= 1048576:
            return f"{num // 1048576}M"
        if num >= 1024:
            return f"{num // 1024}K"
        return f"{num:g}"

    def _set_ctx(self, key, val):
        fld = next(f for f in FIELDS if f["key"] == key)
        self.var[key].set(float(val))
        self.widgets[key].set(float(val))
        self.val_labels[key].configure(text=f"{val:g} {fld.get('unit', '')}".strip())

    def _on_slide(self, key, val):
        fld = next(f for f in FIELDS if f["key"] == key)
        num = round(float(val), 3)
        if "snap" in fld:
            for s in fld["snap"]:
                if abs(num - s) <= fld["step"] * 1.5:
                    num = s
                    self.var[key].set(num)
                    break
        unit = fld.get("unit", "")
        self.val_labels[key].configure(text=f"{num:g} {unit}".strip())

    def _update_combo_hint(self, key):
        fld = next(f for f in FIELDS if f["key"] == key)
        shown = self.var[key].get()
        real = self._combo_map.get(key, {}).get(shown, shown)
        hint = fld.get("option_help", {}).get(real, "")
        self.lbl_hint.configure(text=f"[{fld['label']}] {hint}" if hint else "")
        if real != shown:
            self.var[key].set(real)

    def _help_text(self, key):
        fld = next(f for f in FIELDS if f["key"] == key)
        body = fld.get("help", "（无说明）")
        if fld.get("option_help"):
            body += "\n\n选项说明：\n" + "\n".join(
                f"  - {k or '（空）'}: {v}" for k, v in fld["option_help"].items())
        if fld["kind"] == "slider":
            body += f"\n\n范围：{fld['min']} ~ {fld['max']}（步长 {fld['step']}），默认 {fld.get('default')}"
        return body

    def _browse(self, key):
        p = filedialog.askopenfilename(title="选择文件", initialdir=r"F:\AI_Model")
        if p:
            self.var[key].set(p)

    # ---- 状态刷新 ----
    def on_service_change(self):
        self.service = self.service_var.get()
        self.refresh_all()

    def refresh_all(self):
        self.refresh_status()
        self.load_params()
        mode = get_start_mode(self.service)
        self.auto_var.set({"auto": "自动(开机)", "manual": "手动", "disabled": "禁用"}.get(mode, "手动"))

    @staticmethod
    def _state_color(state):
        return {"RUNNING": C_ACC, "STOPPED": C_GRAY}.get(state, C_ORG)

    def refresh_status(self):
        state = sc_query_state(self.service)
        self.lbl_state.configure(text=f"服务 {state}",
                                 text_color=self._state_color(state))
        host = self.var["host"].get().strip() or "127.0.0.1"
        port = self.var["port"].get().strip() or "8080"
        if state == "RUNNING":
            ok, detail = check_health(host, port)
            self.lbl_health.configure(
                text=f"探活 {'OK' if ok else 'FAIL'} · {detail[:40]}",
                text_color=C_ACC if ok else C_RED)
        else:
            self.lbl_health.configure(text="探活 未运行", text_color=C_GRAY)

    # ---- 参数读写 ----
    def _apply_values(self, values, warnings=None):
        """字段字典填入表单（滑块/下拉/复选/文本通用）。"""
        self.values = dict(values)
        for fld in FIELDS:
            key = fld["key"]
            val = values.get(key, "")
            if fld["kind"] == "slider":
                try:
                    num = float(val)
                except (ValueError, TypeError):
                    num = float(fld.get("default", fld["min"]))
                self.var[key].set(num)
                self.val_labels[key].configure(text=f"{num:g} {fld.get('unit','')}".strip())
            else:
                self.var[key].set(val)
        if warnings is not None:
            self.lbl_warn.configure(text=" | ".join(warnings) if warnings else "")

    def load_params(self):
        text = get_app_parameters(self.service)
        values, extras, warnings = parse_params(text)
        self.extras = extras
        self._apply_values(values, warnings)

    # ---- 预设 ----
    def refresh_presets(self):
        names = list(load_presets().keys())
        self.cmb_preset.configure(values=names)
        if names and self.preset_var.get() not in names:
            self.preset_var.set(names[0])

    def save_preset(self):
        """把当前表单存为预设。名称取自合并下拉框；已有名则覆盖更新，无弹窗。"""
        name = self.preset_var.get().strip()
        if not name:
            messagebox.showwarning("提示", "请先在下拉框输入或选择一个预设名。")
            return
        values, _ = self._collect()
        presets = load_presets()
        presets[name] = values
        save_presets(presets)
        self.refresh_presets()
        self.preset_var.set(name)

    def load_preset(self, name=None):
        """按名载入预设到表单（无弹窗）。"""
        name = name or self.preset_var.get()
        if not name:
            return
        presets = load_presets()
        if name not in presets:
            messagebox.showerror("错误", f"预设「{name}」不存在。")
            return
        # 即选即载：直接填表单，无弹窗
        self._apply_values(presets[name])

    def on_preset_selected(self, name):
        """下拉选择：若表单有未应用更改，先把当前表单自动存为新预设，再载入所选。"""
        if self._dirty():
            cur = self.preset_var.get().strip()
            cur_name = cur if (cur and cur != name) else f"自动备份 {time.strftime('%m-%d %H:%M')}"
            values, _ = self._collect()
            presets = load_presets()
            presets[cur_name] = values
            save_presets(presets)
        self.load_preset(name)

    def _on_preset_committed(self):
        """回车或失去焦点：框内是新名字→把当前参数另存为该预设；是已有名→不动作。"""
        name = self.preset_var.get().strip()
        if not name:
            return
        if name in load_presets():
            return  # 已有名（刚由下拉 command 载入），避免误覆盖
        values, _ = self._collect()
        presets = load_presets()
        presets[name] = values
        save_presets(presets)

    def delete_preset(self):
        name = self.preset_var.get()
        if not name:
            messagebox.showwarning("提示", "请先在下拉选择一个预设。")
            return
        if not messagebox.askyesno("确认", f"删除预设「{name}」？"):
            return
        presets = load_presets()
        presets.pop(name, None)
        save_presets(presets)
        self.refresh_presets()

    def _collect(self):
        values = {}
        for fld in FIELDS:
            key = fld["key"]
            if fld["kind"] == "slider":
                num = float(self.var[key].get())
                if float(fld["step"]).is_integer():
                    values[key] = str(int(round(num)))
                else:
                    values[key] = str(round(num, 4))
            else:
                values[key] = self.var[key].get().strip()
        return values, self.extras

    def _dirty(self):
        """表单参数与当前服务是否不一致。"""
        values, extras = self._collect()
        return build_params(values, extras) != get_app_parameters(self.service)

    def apply_changes(self):
        """写回表单参数；服务运行中则确认后自动重启，未运行仅写回。"""
        values, extras = self._collect()
        new_text = build_params(values, extras)
        cur = get_app_parameters(self.service)
        if new_text == cur:
            messagebox.showinfo("无需改动", "参数与当前服务一致。")
            return
        state = sc_query_state(self.service)
        if state == "RUNNING":
            msg = (f"服务正在运行，将写回新参数并自动重启（{self.service}）：\n\n"
                   f"新参数：\n{new_text}\n\n旧参数：\n{cur}\n\n确认？")
        else:
            msg = (f"即将写回 NSSM AppParameters（服务 {self.service}，当前未运行）：\n\n"
                   f"新参数：\n{new_text}\n\n旧参数：\n{cur}\n\n确认写回？")
        if not messagebox.askyesno("二次确认", msg):
            return
        ok, out = set_app_parameters(self.service, new_text)
        if not ok:
            messagebox.showerror("失败", f"写回失败：{out}")
            return
        if state == "RUNNING":
            self.do_restart()
        else:
            messagebox.showinfo("成功", "已写回。服务未运行，下次启动即生效。")
            self.refresh_status()

    # ---- 生命周期 ----
    def do_action(self, action):
        ok, msg = sc_action(action, self.service)
        if ok:
            messagebox.showinfo("成功", f"sc {action} 已提交（服务 {self.service}）。")
        else:
            messagebox.showerror("失败", f"sc {action} 失败：{msg}")
        self.after(1500, self.refresh_status)

    def do_restart(self):
        threading.Thread(target=self._restart_worker, daemon=True).start()

    def _restart_worker(self):
        self._log_line(f">>> 重启 {self.service}：停止...")
        sc_action("stop", self.service)
        for _ in range(40):
            if sc_query_state(self.service) == "STOPPED":
                break
            time.sleep(0.5)
        self.after(0, self.refresh_status)
        self._log_line(">>> 启动...")
        sc_action("start", self.service)
        for _ in range(120):
            if sc_query_state(self.service) == "RUNNING":
                ok, d = check_health(self.var["host"].get().strip() or "127.0.0.1",
                                     self.var["port"].get().strip() or "8080")
                if ok:
                    self._log_line(f">>> 服务就绪：{d}")
                    break
            time.sleep(0.5)
        self.after(0, self.refresh_status)

    def apply_auto(self):
        """下拉即选即应用（无成功弹窗，失败才提示）。"""
        mode = {"自动(开机)": "auto", "手动": "manual", "禁用": "disabled"}.get(self.auto_var.get(), "manual")
        ok, out = set_start_mode(self.service, mode)
        if not ok:
            messagebox.showerror("失败", f"开机自启设置失败：{out}")

    # ---- 日志 ----
    def toggle_log(self):
        self._log_open.set(not self._log_open.get())
        if self._log_open.get():
            self.btn_log_toggle.configure(text="日志尾随 server.err（点击折叠）", text_color=C_TXT)
            self.txt_log.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        else:
            self.btn_log_toggle.configure(text="日志尾随 server.err（已折叠）", text_color=C_MUT)
            self.txt_log.pack_forget()

    def _log_line(self, text):
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", text + "\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _start_polling(self):
        self._poll_log()
        self._poll_health()

    def _poll_log(self):
        if self._stop_poll:
            return
        try:
            if os.path.exists(ERR_LOG):
                with open(ERR_LOG, "rb") as fh:
                    fh.seek(0, 2)
                    size = fh.tell()
                    fh.seek(max(0, size - 4000))
                    data = fh.read().decode("utf-8", "replace")
                lines = data.splitlines()[-25:]
                cur = self.txt_log.get("1.0", "end").strip()
                new = "\n".join(lines)
                if cur != new:
                    self.txt_log.configure(state="normal")
                    self.txt_log.delete("1.0", "end")
                    self.txt_log.insert("end", new)
                    self.txt_log.see("end")
                    self.txt_log.configure(state="disabled")
        except Exception:  # noqa: BLE001
            pass
        self.after(1500, self._poll_log)

    def _poll_health(self):
        if self._stop_poll:
            return
        # 未应用更改提示（表单 != 服务）
        try:
            self.lbl_dirty.configure(text="● 有未应用的更改" if self._dirty() else "")
        except Exception:  # noqa: BLE001
            pass
        state = sc_query_state(self.service)
        if state == "RUNNING":
            ok, detail = check_health(self.var["host"].get().strip() or "127.0.0.1",
                                      self.var["port"].get().strip() or "8080")
            self.lbl_health.configure(
                text=f"探活 {'OK' if ok else 'FAIL'} · {detail[:40]}",
                text_color=C_ACC if ok else C_RED)
        else:
            self.lbl_health.configure(text="探活 未运行", text_color=C_GRAY)
        self.lbl_state.configure(text=f"服务 {state}",
                                 text_color=self._state_color(state))
        self.after(3000, self._poll_health)

    def _on_close(self):
        self._stop_poll = True
        self.destroy()


def main():
    app = ControlGUI()
    app.mainloop()


if __name__ == "__main__":
    main()

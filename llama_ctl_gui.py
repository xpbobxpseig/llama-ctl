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
import math
import queue
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
    list_nssm_services, check_health, app_directory,
)
from params import parse_params, build_params
from settings import load_settings, save_settings
from motion import Animator, format_hex, lerp, parse_hex, ease_out_cubic, ease_in_cubic
import strings
from strings import t, fmt


def _resource_dir():
    """资源目录：onefile 打包时取 PyInstaller 解包目录（sys._MEIPASS），
    开发模式取脚本所在目录。图标（ico/png）在构建时经 spec datas 打入包内。"""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return meipass
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# 配置（本机固定事实）
# ---------------------------------------------------------------------------
# 日志路径优先从 NSSM AppDirectory 推导（_log_path，T4 起）；
# ERR_LOG 仅作推导失败时的回退（如 nssm 不可用或 AppDirectory 未配置）。
ERR_LOG = r"F:\llama.cpp\server.err"
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
# Apple 风双调色板：浅色为原版；深色同构（底/卡/分隔/输入框/文字互换灰阶，强调蓝不变）
PALETTES = {
    "light": {
        "BG": "#f5f5f7", "CARD": "#ffffff", "BORDER": "#e3e3e8",
        "FIELD": "#fafafa", "TXT": "#1d1d1f", "MUT": "#86868b",
        "ACC": "#0a84ff", "ACCH": "#0071e3",
        "RED": "#ff3b30", "ORG": "#ff9500", "GRAY": "#aeaeb2",
        "RUN": "#30d158", "STOP": "#8e8e93",
        "TIP": "#f0f0f2",
    },
    "dark": {
        "BG": "#1e1e20", "CARD": "#2c2c2e", "BORDER": "#3a3a3c",
        "FIELD": "#252527", "TXT": "#f5f5f7", "MUT": "#98989d",
        "ACC": "#0a84ff", "ACCH": "#0071e3",
        "RED": "#ff453a", "ORG": "#ff9f0a", "GRAY": "#636366",
        "RUN": "#30d158", "STOP": "#636366",
        "TIP": "#2c2c2e",
    },
}
_appearance = "light"  # 当前外观名，由 _apply_palette 维护


def _apply_palette(mode):
    """把调色板展开为模块级常量（C_*），供全部控件取色。切换外观时重建调用。"""
    global _appearance
    pal = PALETTES.get(mode, PALETTES["light"])
    g = globals()
    for name, val in pal.items():
        g[f"C_{name}"] = val
    _appearance = mode


_apply_palette("light")

F_BODY = ("Microsoft YaHei UI", 13)
F_SMALL = ("Microsoft YaHei UI", 12)
F_TITLE = ("Microsoft YaHei UI", 18, "bold")
F_GROUP = ("Microsoft YaHei UI", 12, "bold")


class _HelpTip:
    """问号按钮 hover 提示（D7 延迟 hover + F2 渐隐动效）：

    悬停 300ms 后淡入（200ms ease-out，窗口 alpha 0→1），移开后 2s 指数渐隐
    （α=exp(-k·t/τ)，τ=0.51s，每 16ms 一帧，末段 α 阶梯 0.05/0.02/0 后销毁）；
    渐隐期移回立即恢复 α=1；新提示出现时旧提示立即终止并销毁（全局互斥，
    后悬停者优先）。300ms 延迟是交互防误触，不受动效开关影响；淡入/渐隐
    受动效开关控制（关→瞬时显示/瞬时消失）。所有 after 帧回调在窗口销毁
    竞态下吞 TclError（winfo_exists 检查 + try/except）。
    """

    _TAU = 0.51          # 指数渐隐时间常数：2s 末 α=exp(-2/0.51)≈0.02
    _FADE_MS = 16        # 淡入/渐隐帧间隔
    _FADE_IN_MS = 200    # 淡入时长
    _active = None       # 当前唯一活动提示实例（全局互斥）
    _hovering = None     # 最近进入悬停的实例（后悬停者优先）

    def __init__(self, widget, text_fn, motion_on=None):
        self.widget = widget
        self.text_fn = text_fn          # 延迟取值，内容始终最新
        self.motion_on = motion_on if motion_on is not None else (lambda: True)
        self.win = None
        self._after_id = None           # 延迟显示计时器 token（300ms 防误触）
        self._frame = None              # 淡入/渐隐帧 after token（帧链）
        self._t0 = 0.0                  # 当前帧链起点（墙钟）
        self._alpha = 1.0               # 最近写入的窗口 alpha
        self._stage = 0                 # 末段阶梯：0 自然衰减 / 1 定格 0.05 / 2 定格 0.02
        widget.bind("<Enter>", self._enter)
        widget.bind("<Leave>", self._leave)
        widget.bind("<Button-1>", self._hide)   # 万一点击也立即收起

    # ---- 帧链工具 ----

    def _cancel_frame(self):
        """取消在途淡入/渐隐帧（若有）。控件销毁后 after_cancel 会 TclError，吞掉。"""
        if self._frame is not None:
            try:
                self.widget.after_cancel(self._frame)
            except Exception:  # noqa: BLE001 - 控件销毁后 token 已失效
                pass
            self._frame = None

    def _schedule(self, fn, ms):
        """调度一帧并把 token 存 _frame（下一帧/取消时用）。"""
        self._frame = self.widget.after(ms, fn)

    def _destroy_win(self):
        """销毁提示窗并清理全部计时器/帧链与互斥状态（收尾/互斥/点击共用）。"""
        self._cancel_frame()
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:  # noqa: BLE001
                pass
            self._after_id = None
        if self.win is not None:
            win = self.win            # 先保存局部引用再置空（规格 2.2）
            self.win = None
            try:
                win.destroy()
            except Exception:  # noqa: BLE001 - 已销毁则忽略
                pass
        if _HelpTip._active is self:
            _HelpTip._active = None
        if _HelpTip._hovering is self:
            _HelpTip._hovering = None

    # ---- 事件 ----

    def _enter(self, _=None):
        # 互斥：新提示出现，旧提示立即终止并销毁（后悬停者优先）
        if _HelpTip._active is not None and _HelpTip._active is not self:
            _HelpTip._active._destroy_win()
        _HelpTip._hovering = self
        if self.win is not None:
            # 渐隐期移回：中断渐隐帧，立即恢复 α=1 显示
            self._cancel_frame()
            self._stage = 0
            try:
                self.win.attributes("-alpha", 1.0)
            except Exception:  # noqa: BLE001 - 销毁竞态下静默
                pass
            self._alpha = 1.0
            return
        if self._after_id is None:
            self._after_id = self.widget.after(300, self._show)

    def _leave(self, _=None):
        if _HelpTip._hovering is self:
            _HelpTip._hovering = None
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:  # noqa: BLE001 - 控件销毁后 token 已失效
                pass
            self._after_id = None
        if self.win is None:
            return
        self._cancel_frame()
        if not self.motion_on():
            self._destroy_win()  # 动效关：瞬时消失
            return
        # 从当前 alpha 起步渐隐（淡入中途移出也自然衔接）
        try:
            self._alpha = max(0.0, min(1.0, float(self.win.attributes("-alpha"))))
        except Exception:  # noqa: BLE001 - 读不到 alpha 按全显处理
            self._alpha = 1.0
        self._stage = 0
        self._t0 = time.monotonic()
        self._schedule(self._fade_frame, _HelpTip._FADE_MS)

    # ---- 显示 / 渐隐帧 ----

    def _show(self, _=None):
        self._after_id = None  # 定时器已触发
        if _HelpTip._hovering is not self:
            return  # 已被更新的悬停者抢占（旧定时器晚到）
        try:
            if self.win is not None:
                return
            text = self.text_fn()
            if not text:
                return
            if _HelpTip._active is not None and _HelpTip._active is not self:
                _HelpTip._active._destroy_win()
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
            _HelpTip._active = self
            if self.motion_on():
                self._alpha = 0.0
                win.attributes("-alpha", 0.0)
                self._t0 = time.monotonic()
                self._schedule(self._fade_in_frame, _HelpTip._FADE_MS)
            else:
                win.attributes("-alpha", 1.0)  # 动效关：瞬时显示
                self._alpha = 1.0
        except Exception:  # noqa: BLE001 - 定时器晚到且控件已销毁（UI 重建）时静默放弃
            pass

    def _fade_in_frame(self):
        """淡入帧：200ms ease-out，α 0→1。"""
        try:
            self._frame = None
            win = self.win
            if win is None:
                return
            if not win.winfo_exists():
                self.win = None
                if _HelpTip._active is self:
                    _HelpTip._active = None
                return
            t = (time.monotonic() - self._t0) * 1000.0 / _HelpTip._FADE_IN_MS
            if t >= 1.0:
                win.attributes("-alpha", 1.0)
                self._alpha = 1.0
                return
            a = ease_out_cubic(t, 1.0)
            win.attributes("-alpha", max(0.0, a))
            self._alpha = a
            self._schedule(self._fade_in_frame, _HelpTip._FADE_MS)
        except Exception:  # noqa: BLE001 - 销毁竞态下的 TclError 等吞掉
            self._frame = None

    def _fade_frame(self):
        """渐隐帧：α=exp(-k·t/τ)；k 随光标离问号距离加速（加分 1），
        末段 α 按 0.05/0.02 阶梯定格后销毁（加分 2）。"""
        try:
            self._frame = None
            win = self.win
            if win is None:
                return
            if not win.winfo_exists():
                self.win = None
                if _HelpTip._active is self:
                    _HelpTip._active = None
                return
            # 加分 1：光标离问号越远渐隐越快（0~400px 线性加速至 2 倍）
            px = win.winfo_pointerx() - (self.widget.winfo_rootx()
                                         + self.widget.winfo_width() // 2)
            py = win.winfo_pointery() - (self.widget.winfo_rooty()
                                         + self.widget.winfo_height() // 2)
            k = 1.0 + min(max(abs(px), abs(py)) / 400.0, 1.0)
            a = math.exp(-(time.monotonic() - self._t0) * k / _HelpTip._TAU)
            # 加分 2：末段阶梯化（0.05 / 0.02 / 0），避免低 alpha 闪烁
            if a < 0.05:
                if self._stage == 0:
                    a, self._stage = 0.05, 1
                elif self._stage == 1:
                    a, self._stage = 0.02, 2
                else:
                    self._destroy_win()
                    return
            win.attributes("-alpha", max(0.0, a))
            self._alpha = a
            self._schedule(self._fade_frame, _HelpTip._FADE_MS)
        except Exception:  # noqa: BLE001 - 销毁竞态下的 TclError 等吞掉
            self._frame = None

    def _hide(self, _=None):
        """点击立即收起（清理帧链与互斥状态，同收尾路径）。"""
        self._destroy_win()


class ControlGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        if sys.platform != "win32":
            messagebox.showerror(t("mb.unsupported"), t("msg.winonly"))
            self.destroy()
            return
        self.settings = load_settings()
        strings.set_lang(self.settings["language"])
        _apply_palette("light" if self.settings["appearance"] == "dark" else
                       ({"light": "light", "dark": "dark"}.get(self.settings["appearance"], "light")))
        ctk.set_appearance_mode(
            {"system": "system", "light": "light", "dark": "dark"}[self.settings["appearance"]])
        self.title(t("app.title"))
        try:
            self.iconbitmap(os.path.join(_resource_dir(), "llama_icon.ico"))
        except Exception:  # noqa: BLE001 - 图标缺失不阻断启动
            pass
        if self.settings.get("geometry"):
            self.geometry(self.settings["geometry"])
        else:
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
        self._log_q = queue.Queue()
        # 动效引擎：注入 Tk after 作调度器（motion.py 纯数值模块）；
        # 必须在 _build_widgets 之前创建，D4 起的 hover 绑定会用到。
        # frame_ms=66：长驻动效（呼吸循环）降到约 15fps，重绘压力再减半；
        # 160ms 的 hover 过渡此时约 2-3 帧仍可接受（ease-out 末段占大头），
        # 缩放/拖拽期间动画帧与 WM_CONFIGURE 的抢帧概率显著下降。
        self.anim = Animator(schedule=lambda fn, ms: self.after(ms, fn),
                             frame_ms=66)
        # 状态圆点动效状态（D3）：呼吸/错误闪烁的注册 id 与守卫标志
        self._breathing = False      # 呼吸循环是否应持续
        self._breath_id = -1         # 当前呼吸动画 id（-1 = 无）
        self._breath_busy = False    # 防同步重入（animate 降级时 on_done 同步回调）
        self._breath_resume = False  # 错误闪烁结束后是否恢复呼吸
        self._flash_id = -1          # 当前闪烁动画 id（-1 = 无）
        self._flash_armed = True     # FAIL 只闪一次，恢复 OK 后重新武装
        self._log_anim_id = -1       # 日志面板高度过渡动画 id（-1 = 无）
        # D7 字段改动高亮：每字段恢复色 after token；_suppress_trace 屏蔽程序化填值
        self._field_flash_after = {}  # key -> after token（快速连改重置计时器）
        self._suppress_trace = False  # load_params/预设载入等程序化 set 期间屏蔽 trace
        # F1 按钮渐隐帧 token 注册表 btn -> after token（手写 after 链，不走
        # Animator；每帧执行前先摘除自身，关窗/重建时统一取消在途帧）
        self._hover_fades = {}
        # D8 折叠分组：展开状态（_restart_ui 重建后保留，默认仅第一组展开）
        self.group_open = {}
        self._log_off = 0  # _poll_log 增量渲染：上次读到的文件偏移
        # 探活 worker（拖拽卡顿修复）：所有同步阻塞的 nssm/sc/urlopen 移出
        # 主线程。请求走 _status_q（主→worker），结果走 _status_r（worker→主）；
        # 两条队列分离，避免 worker 把自己的 result 当请求消费。
        self._status_q = queue.Queue()
        self._status_r = queue.Queue()
        self._status_worker = threading.Thread(target=self._status_worker_loop,
                                               daemon=True)
        # dirty 主线程缓存（worker 线程不能读 Tk 变量）：6s 降频重算，
        # 表单编辑/载入/写回时失效
        self._dirty_cache = None
        self._dirty_at = 0.0

        self._build_widgets()
        self.refresh_all()
        self._start_polling()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # 缩放/拖拽防抖：WM_CONFIGURE 高频触发期间挂起 UI 应用与日志渲染，
        # 停止 300ms 后恢复（缩放卡顿修复）。
        self._resizing = False
        self._resize_after = None
        self.bind("<Configure>", self._on_configure)

    # ---- 通用小组件 ----
    def _btn(self, parent, text, cmd, kind="ghost"):
        """kind: primary / ghost / danger-text。

        hover 动效（D4 + 指数渐隐）：native hover_color 固定为底色，颜色过渡完全由
        <Enter>/<Leave> 驱动——进入 160ms ease-out 插到高亮并驻留（不回落）；
        移出 2s 指数渐隐（α=exp(-t/τ), τ=0.67s, 每 16ms 一帧, α≤0.05 末帧定格
        80ms 后直跳终态）；渐隐期移回中断渐隐、从当前色续插回高亮。动效关时
        瞬时切换（原生 hover 行为）。禁用态（t5 联动置灰）跳过动效。
        """
        kw = dict(font=F_BODY, corner_radius=8, height=32)
        if kind == "primary":
            base, hover = C_ACC, C_ACCH
        elif kind == "danger":
            base, hover = C_RED, "#fdeceb"
        else:
            base, hover = C_TXT, C_CARD
        # hover=False：禁用 CTkButton 原生 hover 状态机（其 _on_enter/_on_leave
        # 用 canvas.itemconfig 直接画 inner_parts，绕过 fg_color——与我们的
        # 16ms 动画帧交替重绘会深/浅爆闪）。视觉完全由 _fade_enter/_fade_leave
        # 驱动；动效关时 _fade_enter 的非 motion 分支做瞬时切换，行为等价。
        if kind == "primary":
            kw.update(fg_color=base, hover_color=hover, text_color="#ffffff",
                      hover=False)
        else:
            kw.update(fg_color="transparent", hover_color=hover, text_color=base,
                      border_width=1, border_color=C_BORDER, hover=False)
        btn = ctk.CTkButton(parent, text=text, command=cmd, **kw)

        # hover 动效状态（闭包）：
        #   aid  进入/续插 tween 的 Animator id（-1 = 无）
        #   cur  我们最近写入的可插值颜色。关键点：Tk 事件按注册序执行，CTk 内部
        #        <Enter>/<Leave> 先于本 handler 把 fg_color 复位，因此不能读 cget
        #        取起点——必须用闭包记住自己写的颜色
        #   fade 在途渐隐帧的 after token（None = 无）；每帧自替换，token 同步
        #        登记进 self._hover_fades，供关窗/_restart_ui 统一取消
        hstate = {"aid": -1, "cur": None, "fade": None}
        _FADE_TAU = 0.67   # 指数渐隐时间常数：2s 末 α=exp(-2/0.67)≈0.05
        _FADE_STOP = 0.05  # α 降到该值 → 定格 _FADE_HOLD 毫秒后直跳终态
        _FADE_HOLD = 80    # 末帧定格时长（ms，生动加分 2）
        _FADE_FRAME = 16   # 渐隐帧间隔（ms）

        def _resolve_base():
            """transparent 基色按祖先链解析出真实底色（ghost/danger 落在卡片/行上）。

            None（fg_color 未设置）与 transparent 等价，都继续向上找。
            """
            p = btn.master
            while p is not None:
                try:
                    c = p.cget("fg_color")
                    if c and c != "transparent":
                        return c
                except Exception:  # noqa: BLE001 - 非 ctk 容器无 fg_color
                    pass
                p = getattr(p, "master", None)
            return C_CARD

        def _fade_cancel():
            """取消本按钮在途渐隐帧（若有），并从注册表摘除 token。"""
            tok = self._hover_fades.pop(btn, None)
            if tok is not None:
                try:
                    self.after_cancel(tok)
                except Exception:  # noqa: BLE001 - token 已执行/已清理
                    pass
            hstate["fade"] = None

        def _fade_enter(hover_col):
            """进入 / 渐隐期移回：取消在途渐隐，从当前色续插回高亮（160ms ease-out）。"""
            _fade_cancel()
            if hstate["aid"] > 0:
                self.anim.cancel(hstate["aid"])
                hstate["aid"] = -1
            if btn.cget("state") == "disabled":
                return  # t5 联动置灰时不动外观
            if hstate["cur"] is None:
                hstate["cur"] = _resolve_base()
            start = hstate["cur"]
            if not self._motion_on():
                btn.configure(fg_color=hover_col)
                hstate["cur"] = hover_col
                return

            def _tick(p):
                if btn.cget("state") == "disabled":
                    return  # 中途被置灰（如 t5 轮询）：停止写色，保住禁用外观
                col = format_hex(lerp(start, hover_col, ease_out_cubic(p, 1)))
                hstate["cur"] = col
                btn.configure(fg_color=col)

            def _done():
                hstate["aid"] = -1
                if btn.cget("state") == "disabled":
                    return
                hstate["cur"] = hover_col

            hstate["aid"] = self.anim.animate(_tick, 160, on_done=_done)
            if hstate["aid"] <= 0:  # 瞬时/降级：on_done 已同步执行
                hstate["aid"] = -1

        def _fade_leave(final_col, back_to_transparent=False):
            """移出：2s 指数渐隐 高亮→终态（手写 after 帧链，不用 Animator）。

            每帧 α = exp(-t/τ)，t 取墙钟（time.monotonic，窗口卡顿时自然掉帧
            不拖长）；颜色 = lerp(终态, 高亮, α)。终态色先按亮度压 2%
            （生动加分 1：消退更真实），α≤0.05 时定格 80ms 再直跳终态。
            """
            _fade_cancel()
            if hstate["aid"] > 0:
                self.anim.cancel(hstate["aid"])
                hstate["aid"] = -1
            if btn.cget("state") == "disabled":
                return  # t5 联动置灰时不动外观
            if hstate["cur"] is None:
                hstate["cur"] = _resolve_base()
            peak = hstate["cur"]          # 渐隐起点（离开瞬间的实际颜色）
            hstate["cur"] = final_col     # 渐隐期终态基准（移回续插的终点）
            if not self._motion_on():
                btn.configure(fg_color="transparent" if back_to_transparent
                              else final_col)
                return
            if btn.cget("state") == "disabled":
                return

            # 终态色亮度轻压 2%（浅色向黑、深色向白偏移）
            if final_col == "transparent":
                base_col = _resolve_base()
            else:
                base_col = final_col
            rgb = parse_hex(base_col)
            lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
            anchor = (0, 0, 0) if lum > 128 else (255, 255, 255)
            target = format_hex(lerp(base_col, anchor, 0.02))

            t0 = time.monotonic()

            def _schedule_frame(fn, ms):
                """调度一帧并登记 token（hstate + 注册表）；帧执行时先摘除自身。"""
                box = {}

                def _run():
                    self._hover_fades.pop(btn, None)
                    hstate["fade"] = None
                    fn()

                box["tok"] = self.after(ms, _run)
                self._hover_fades[btn] = box["tok"]
                hstate["fade"] = box["tok"]

            def _frame():
                try:
                    if not btn.winfo_exists():
                        return  # 按钮已随 _restart_ui 销毁：帧链自灭
                    if btn.cget("state") == "disabled":
                        # 中途被置灰（如 t5 轮询）：停在当前帧色，保住禁用外观
                        hstate["cur"] = None
                        return
                    a = math.exp(-(time.monotonic() - t0) / _FADE_TAU)
                    if a <= _FADE_STOP:
                        # 末帧定格 80ms 再直跳终态（生动加分 2）
                        _schedule_frame(lambda: _fade_finish(final_col),
                                        _FADE_HOLD)
                        return
                    col = format_hex(lerp(target, peak, a))
                    hstate["cur"] = col
                    btn.configure(fg_color=col)
                    _schedule_frame(_frame, _FADE_FRAME)
                except Exception:  # noqa: BLE001 - 销毁竞态下的 TclError 等吞掉
                    self._hover_fades.pop(btn, None)
                    hstate["fade"] = None

            def _fade_finish(final):
                try:
                    if not btn.winfo_exists():
                        return
                    if btn.cget("state") == "disabled":
                        hstate["cur"] = None
                        return
                    if back_to_transparent:
                        btn.configure(fg_color="transparent")
                        hstate["cur"] = _resolve_base()
                    else:
                        btn.configure(fg_color=final)
                        hstate["cur"] = final
                except Exception:  # noqa: BLE001
                    self._hover_fades.pop(btn, None)
                    hstate["fade"] = None

            _schedule_frame(_frame, _FADE_FRAME)

        btn.bind("<Enter>", lambda e: _fade_enter(hover))
        # 离开：primary 回 C_ACC；ghost/danger 回 transparent（终态按祖先底色插值）
        btn.bind("<Leave>", lambda e: _fade_leave(
            base if kind == "primary" else _resolve_base(),
            back_to_transparent=(kind != "primary")))
        return btn

    def _card(self, parent, title=None, expand=False):
        fr = ctk.CTkFrame(parent, fg_color=C_CARD, corner_radius=14,
                          border_width=1, border_color=C_BORDER)
        fr.pack(fill="both" if expand else "x", expand=expand, padx=12, pady=(6, 0))
        inner = ctk.CTkFrame(fr, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=14, pady=12)
        if title:
            ctk.CTkLabel(inner, text=title, font=F_GROUP, text_color=C_MUT,
                         anchor="w").pack(fill="x", pady=(0, 8))
        # 卡片 hover 抬升（D4，动效 2）：边框从 C_BORDER 插到浅蓝再插回，200ms
        hover_border = "#cfe6ff" if ctk.get_appearance_mode() == "Light" else "#0a84ff"

        def _tick(p):
            t = ease_out_cubic(p, 1)
            fr.configure(border_color=format_hex(lerp(C_BORDER, hover_border, t)))

        def _enter(_):
            if self._motion_on():
                self.anim.animate(_tick, 200)  # -1 降级即同步终态
            else:
                fr.configure(border_color=hover_border)  # 动效关：瞬切

        def _leave(_):
            if self._motion_on():
                def _back(p):
                    t = ease_out_cubic(p, 1)
                    fr.configure(border_color=format_hex(lerp(hover_border, C_BORDER, t)))

                self.anim.animate(_back, 200)  # -1 降级即同步终态
            else:
                fr.configure(border_color=C_BORDER)

        fr.bind("<Enter>", _enter)
        fr.bind("<Leave>", _leave)
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
        ctk.CTkLabel(svc, text=t("svc.label"), font=F_BODY, text_color=C_MUT).pack(side="left", padx=(0, 6))
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
        self.dot_state = ctk.CTkLabel(row, text="\u25CF", width=12, font=F_BODY)
        self.dot_state.configure(text_color=C_STOP)
        self.dot_state.pack(side="left")
        self.lbl_state = ctk.CTkLabel(row, text=t("state.unknown"), font=F_BODY, text_color=C_MUT)
        self.lbl_state.pack(side="left")
        self.lbl_health = ctk.CTkLabel(row, text=t("health.idle"), font=F_BODY, text_color=C_MUT)
        self.lbl_health.pack(side="left", padx=(18, 0))
        ctk.CTkLabel(row, text=t("boot.label"), font=F_SMALL, text_color=C_MUT
                     ).pack(side="left", padx=(24, 6))
        self.auto_var = tk.StringVar(value=t("boot.manual"))
        self.opt_auto = ctk.CTkOptionMenu(row, variable=self.auto_var,
                                          values=[t("boot.auto"), t("boot.manual"), t("boot.disabled")],
                                          width=130, height=30, font=F_BODY,
                                          fg_color=C_FIELD, button_color=C_BORDER,
                                          button_hover_color=C_ACC, text_color=C_TXT,
                                          command=lambda v: self.apply_auto())
        self.opt_auto.pack(side="left")
        act = ctk.CTkFrame(row, fg_color="transparent")
        act.pack(side="right")
        self.btn_start = self._btn(act, t("btn.start"), lambda: self.do_action("start"))
        self.btn_start.pack(side="left", padx=3)
        self.btn_stop = self._btn(act, t("btn.stop"), lambda: self.do_action("stop"), kind="danger")
        self.btn_stop.pack(side="left", padx=3)
        self._btn(act, t("btn.restart"), self.do_restart).pack(side="left", padx=3)
        self._btn(act, t("btn.settings"), self.open_settings).pack(side="left", padx=(18, 3))

        # 预设区（单行：标题 + 可编辑下拉 + 删除图标；右侧 应用更改/还原）
        pr = self._card(self)
        prow = ctk.CTkFrame(pr, fg_color="transparent")
        prow.pack(fill="x")
        ctk.CTkLabel(prow, text=t("card.presets"), font=F_GROUP, text_color=C_MUT).pack(side="left")
        self.lbl_dirty = ctk.CTkLabel(prow, text="", font=F_SMALL, text_color=C_ORG)
        self.lbl_dirty.pack(side="left", padx=12)
        self.btn_revert = self._btn(prow, t("btn.revert"), self.load_params)
        self.btn_revert.pack(side="right")
        self.btn_apply = self._btn(prow, t("btn.apply2"), self.apply_changes, kind="primary")
        self.btn_apply.pack(side="right", padx=(0, 8))
        base = _resource_dir()
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
            self._btn(prow, t("preset.delete"), self.delete_preset, kind="danger")
        self.refresh_presets()

        # 参数区（滚动卡片，占最大纵向空间）
        pcfr = ctk.CTkFrame(self, fg_color=C_CARD, corner_radius=14,
                            border_width=1, border_color=C_BORDER)
        pcfr.pack(fill="both", expand=True, padx=12, pady=(6, 0))
        pc = ctk.CTkFrame(pcfr, fg_color="transparent")
        pc.pack(fill="both", expand=True, padx=14, pady=12)
        phead = ctk.CTkFrame(pc, fg_color="transparent")
        phead.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(phead, text=t("card.params"), font=F_GROUP, text_color=C_MUT,
                     anchor="w").pack(side="left")
        self.scroll = ctk.CTkScrollableFrame(pc, fg_color="transparent",
                                             scrollbar_button_color=C_GRAY,
                                             scrollbar_button_hover_color=C_GRAY)
        self.scroll.pack(fill="both", expand=True)
        self.scroll.grid_columnconfigure(2, weight=1)
        # D8 折叠分组：每个 group 一个可折叠区（头按钮 + 独立 grid 容器，行号各从 0 计）
        self._group_containers = {}  # group -> 内容 CTkFrame
        self._group_headers = {}     # group -> 头部按钮
        groups = []
        for fld in FIELDS:
            g = fld.get("group")
            if g not in groups:
                groups.append(g)
        self.group_open = self.group_open or {}  # 历史空字典（升级路径）
        # 仅第一组默认展开；已存在的展开状态（跨 _restart_ui）原样保留
        for i, g in enumerate(groups):
            self.group_open.setdefault(g, i == 0)
            head = ctk.CTkButton(
                self.scroll, text=self._group_label(g), font=F_GROUP,
                text_color=C_ACC if self.group_open[g] else C_MUT,
                fg_color="transparent", hover_color=C_CARD,
                anchor="w", height=30, corner_radius=6,
                command=lambda gg=g: self._toggle_group(gg))
            head.grid(row=len(self._group_containers) * 2, column=0,
                      columnspan=4, sticky="ew", pady=(6, 2))
            body = ctk.CTkFrame(self.scroll, fg_color="transparent")
            body.grid(row=len(self._group_containers) * 2 + 1, column=0,
                      columnspan=4, sticky="ew", padx=(10, 0))
            body.grid_columnconfigure(2, weight=1)
            self._group_containers[g] = body
            self._group_headers[g] = head
            if not self.group_open[g]:
                body.grid_remove()
        # 每组容器独立从 0 计数（FIELDS 按 group 连续排列）
        row_i = 0
        last_group = None
        for fld in FIELDS:
            g = fld.get("group")
            if g != last_group:
                row_i = 0
                last_group = g
            body = self._group_containers[g]
            row_i = self._build_field(body, fld, row_i)

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
            head, text=t("log.collapsed"), font=F_GROUP,
            text_color=C_MUT, anchor="w", fg_color="transparent",
            hover_color=C_BG, command=self.toggle_log)
        self.btn_log_toggle.pack(side="left")
        self.txt_log = ctk.CTkTextbox(lg, height=40, font=("Consolas", 11),
                                      fg_color=C_FIELD, border_width=1,
                                      border_color=C_BORDER, wrap="none")
        self.txt_log.configure(state="disabled")
        # 新行渐隐高亮 tag（D5）：插入后 ≤200ms 移除背景
        self.txt_log._textbox.tag_configure("flash", background="#fff3cd")
        # 默认不打包日志区，仅头部行
        # 警告行（解析告警）挂在日志折叠条下方
        self.lbl_warn = ctk.CTkLabel(self, text="", font=F_SMALL, text_color=C_ORG,
                                     anchor="w", wraplength=900, justify="left")
        self.lbl_warn.pack(fill="x", padx=16, pady=(2, 8))

    def _group_label(self, group):
        """组头文案：组名 + 展开指示（▾ 展开 / ▸ 收起）。"""
        indicator = chr(0x25BE) if self.group_open.get(group, False) else chr(0x25B8)
        return f"{group} {indicator}"

    def _toggle_group(self, group):
        """点击组头切换展开/收起（D8）。瞬时切换优先正确性；状态写入
        self.group_open 供 _restart_ui 重建后恢复。"""
        self.group_open[group] = not self.group_open.get(group, False)
        head = self._group_headers[group]
        body = self._group_containers[group]
        head.configure(text=self._group_label(group),
                       text_color=C_ACC if self.group_open[group] else C_MUT)
        if self.group_open[group]:
            body.grid()
        else:
            body.grid_remove()

    def _build_field(self, parent, fld, row):
        key = fld["key"]
        btn = ctk.CTkButton(parent, text="?", width=26, height=26, corner_radius=13,
                            font=F_SMALL, fg_color="transparent", border_width=1,
                            border_color=C_BORDER, hover_color=C_CARD, text_color=C_MUT,
                            cursor="question_arrow")
        btn.grid(row=row, column=0, padx=(0, 8), pady=4)
        _HelpTip(btn, lambda k=key: self._help_text(k), motion_on=self._motion_on)

        v = tk.StringVar()
        self.var[key] = v
        self._hook_trace(key, v)

        if fld["kind"] == "slider":
            iv = tk.DoubleVar()
            self.var[key] = iv
            self._hook_trace(key, iv)
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
                ctk.CTkLabel(qfr, text=t("quick.label"), font=F_SMALL, text_color=C_MUT
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
            self._hook_trace(key, cv)
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
            self._btn(parent, t("browse"), lambda k=key: self._browse(k)).grid(
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

    def _hook_trace(self, key, var):
        """字段变量 write trace：改动即高亮该控件 1s（D7）。

        程序化填值（load_params/预设载入/快键/snap）期间 _suppress_trace=True
        时直接 return，防启动加载全屏闪。
        """
        def _on_write(*_):
            self._dirty_cache = None  # 用户改字段：dirty 缓存立即失效
            if self._suppress_trace:
                return
            self._flash_field(key)

        var.trace_add("write", _on_write)

    def _flash_field(self, key):
        """字段控件高亮 1s：边框/按钮色闪强调蓝后恢复（快速连改重置计时器）。

        动效关时跳过（D2 契约：动画直跳终态 = 不闪）。
        各控件着色能力不同：slider 用 button_color；entry 用 border_color；
        checkbox 用 border_color；combo（CTkOptionMenu 无 border_color 参数）
        退化为 button_color 闪（try/except 吞 TypeError）。
        """
        if not self._motion_on():
            return
        w = self.widgets.get(key)
        if w is None:
            return
        old = self._field_flash_after.pop(key, None)
        if old:
            try:
                self.after_cancel(old)  # 快速连改：重置恢复计时器
            except Exception:  # noqa: BLE001
                pass
        # 先恢复基准色，再瞬时闪强调蓝（连续改动时从强调色直接重闪）
        self._restore_field_color(key)
        try:
            w.configure(border_color=C_ACC)
        except Exception:  # noqa: BLE001 - combo 无 border_color 参数，退化用 button_color
            try:
                w.configure(button_color=C_ACC)
            except Exception:  # noqa: BLE001 - 不支持的控件静默跳过
                return
        self._field_flash_after[key] = self.after(1000, lambda k=key: self._restore_field_color(k))

    def _restore_field_color(self, key):
        """恢复字段控件基准色（slider 保持原生蓝按钮、其余回主题色）。"""
        w = self.widgets.get(key)
        if w is None:
            return
        fld = next((f for f in FIELDS if f["key"] == key), None)
        try:
            if fld and fld["kind"] == "slider":
                w.configure(button_color=C_ACC)
            else:
                w.configure(border_color=C_BORDER)
        except Exception:  # noqa: BLE001 - combo 无 border_color，button_color 恢复
            try:
                w.configure(button_color=C_BORDER)
            except Exception:  # noqa: BLE001
                pass

    def _fmt_ctx(self, num):
        if num >= 1048576:
            return f"{num // 1048576}M"
        if num >= 1024:
            return f"{num // 1024}K"
        return f"{num:g}"

    def _set_ctx(self, key, val):
        """快捷档位：程序化 set（D7 屏蔽 trace），但随后手动闪一次给用户反馈。"""
        fld = next(f for f in FIELDS if f["key"] == key)
        self._suppress_trace = True
        try:
            self.var[key].set(float(val))
        finally:
            self._suppress_trace = False
        self.widgets[key].set(float(val))
        self.val_labels[key].configure(text=f"{val:g} {fld.get('unit', '')}".strip())
        self._flash_field(key)

    def _on_slide(self, key, val):
        fld = next(f for f in FIELDS if f["key"] == key)
        num = round(float(val), 3)
        if "snap" in fld:
            for s in fld["snap"]:
                if abs(num - s) <= fld["step"] * 1.5:
                    num = s
                    self._suppress_trace = True  # snap 程序化回写不触发第二次高亮
                    try:
                        self.var[key].set(num)
                    finally:
                        self._suppress_trace = False
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
            self._suppress_trace = True  # 显示名归一化（（空）→""）不触发高亮
            try:
                self.var[key].set(real)
            finally:
                self._suppress_trace = False

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
        p = filedialog.askopenfilename(title=t("file.pick"), initialdir=r"F:\AI_Model")
        if p:
            self.var[key].set(p)

    # ---- 状态刷新 ----
    def on_service_change(self):
        """切换服务：若有未应用更改，先确认（可自动备份为预设）。"""
        new_name = self.service_var.get()
        if new_name != self.service and self._dirty():
            if messagebox.askyesno(t("mb.confirm"), fmt("msg.svc.dirty", n=new_name)):
                values, _ = self._collect()
                presets = load_presets()
                presets[fmt("preset.autobackup", t=time.strftime('%m-%d %H:%M:%S'))] = values
                save_presets(presets)
                self.refresh_presets()
        self.service = new_name
        self.refresh_all()

    def refresh_all(self):
        self.refresh_status()
        self.load_params()
        mode = get_start_mode(self.service)
        self.auto_var.set({"auto": t("boot.auto"), "manual": t("boot.manual"), "disabled": t("boot.disabled")}.get(mode, t("boot.manual")))
        # 恢复上次预设（仅当仍存在）
        last = self.settings.get("last_preset") if getattr(self, "settings", None) else ""
        if last and last in load_presets():
            self.preset_var.set(last)
            self.load_preset(last)

    @staticmethod
    def _state_color(state):
        return {"RUNNING": C_RUN, "STOPPED": C_STOP}.get(state, C_ORG)

    # ---- 状态圆点动效（D3：呼吸 + 错误闪烁） ----
    def _breath_loop(self):
        """绿点呼吸：1200ms/周期，亮度 ±12% 余弦脉动，on_done 续调下一轮。

        用 self.anim（schedule 注入 after）驱动；动效关或状态变化时
        _update_status_dot 会 cancel 掉当前 id 并置 _breathing=False，循环自然终止。
        animate() 返回 -1（瞬时/降级）时不进注册表：id 直接置 -1，on_done 已同步
        执行（_breath_loop 再入时若 _breathing 仍真则继续下一轮）。
        """
        def _frame(p):
            if getattr(self, "_resizing", False):
                return  # 缩放期间跳过帧（颜色停在当前值，缩放结束续跑）
            amp = 0.12 * (0.5 - 0.5 * math.cos(2 * math.pi * p))
            self.dot_state.configure(
                text_color=format_hex(lerp(C_RUN, _breath_peak, amp)))

        if not self._breathing or self._breath_busy:
            return
        _breath_peak = "#ffffff" if ctk.get_appearance_mode() == "Light" else "#000000"
        self._breath_busy = True
        self._breath_id = self.anim.animate(_frame, 1200, on_done=self._breath_loop)
        self._breath_busy = False
        if self._breath_id <= 0:  # 瞬时/降级：on_done 已同步续调过，不再续
            self._breath_id = -1

    def _flash_error(self):
        """错误闪烁：dot 在 C_RED 与 RUNNING 原色间交替 2 轮（600ms，ease-out cubic）。

        动效关时只切一次红色，不循环。on_done 恢复原色并决定是否续呼吸。
        降级（animate 返回 -1）时 on_done 已同步执行，不续调。
        """
        if not self._motion_on():
            self.dot_state.configure(text_color=C_RED)
            return

        def _frame(p):
            t = ease_out_cubic(p, 1)  # 索引式缓动：i=p, steps=1 → 连续化
            red = math.sin(t * 4 * math.pi) > 0  # 2 轮完整交替：红/原/红/原（2×300ms）
            self.dot_state.configure(text_color=C_RED if red else C_RUN)

        self._flash_id = self.anim.animate(
            _frame, 600, on_done=self._flash_done)
        if self._flash_id <= 0:  # 瞬时/降级：on_done 已同步执行完毕
            self._flash_id = -1

    def _flash_done(self):
        self._flash_id = -1
        if self._breath_resume:
            self._breath_resume = False
            self._breathing = True
            self._breath_loop()
        else:
            self.dot_state.configure(text_color=C_RUN)  # 安全回退：闪烁只在 RUNNING 时触发

    def _update_status_dot(self, state, health_ok):
        """状态圆点同步入口（refresh_status 与 _poll_health 共用）。

        RUNNING：健康则呼吸（动效关 = 静态绿），探活失败则错误闪烁（武装标志
        保证连续 FAIL 只闪一次，恢复 OK 重新武装）；STOPPED 静态灰；
        其他（过渡态）静态橙。
        """
        if state == "RUNNING":
            if health_ok:
                self._flash_armed = True
                if self._flash_id > 0:
                    return  # 闪烁进行中，由 on_done 恢复
                if self._motion_on():
                    self._breathing = True
                    if self._breath_id <= 0:  # 已有动画在跑（on_done 续调）则不重复开
                        self._breath_loop()
                else:
                    self._breathing = False
                    if self._breath_id > 0:
                        self.anim.cancel(self._breath_id)
                        self._breath_id = -1
                    self.dot_state.configure(text_color=C_RUN)
            else:
                self._breathing = False
                if self._breath_id > 0:
                    self.anim.cancel(self._breath_id)
                    self._breath_id = -1
                if self._flash_armed:
                    self._flash_armed = False
                    self._breath_resume = True  # 闪完若仍 RUNNING 则续呼吸
                    self._flash_error()
        else:
            self._breathing = False
            if self._breath_id > 0:
                self.anim.cancel(self._breath_id)
                self._breath_id = -1
            if self._flash_id > 0:
                self._breath_resume = False
                self.anim.cancel(self._flash_id)
                self._flash_id = -1
            self.dot_state.configure(
                text_color=C_STOP if state == "STOPPED" else C_ORG)

    def refresh_status(self):
        """派活给 worker（拖拽卡顿修复）：不再同步 sc_query_state/check_health。
        结果由 _drain_status 应用；worker 未启动时（极早期）直接排队。"""
        host = self.var["host"].get().strip() or "127.0.0.1"
        port = self.var["port"].get().strip() or "8080"
        try:
            self._status_q.put(("refresh", self.service, host, port, None))
        except Exception:  # noqa: BLE001
            pass

    # ---- 参数读写 ----
    def _apply_values(self, values, warnings=None):
        """字段字典填入表单（滑块/下拉/复选/文本通用）。

        程序化填值（load_params/预设载入均经此入口）：_suppress_trace 屏蔽
        字段高亮 trace，防启动加载全屏闪（D7）。
        """
        self.values = dict(values)
        self._suppress_trace = True
        try:
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
        finally:
            self._suppress_trace = False
        if warnings is not None:
            self.lbl_warn.configure(text=" | ".join(warnings) if warnings else "")

    def load_params(self):
        text = get_app_parameters(self.service)
        values, extras, warnings = parse_params(text, FIELDS)
        self.extras = extras
        self._apply_values(values, warnings)
        self._dirty_cache = None  # 载入后表单=服务，dirty 缓存失效待重算

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
            messagebox.showwarning(t("mb.hint"), t("msg.presetname"))
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
            messagebox.showerror(t("mb.error"), fmt("msg.preset.miss", n=name))
            return
        # 即选即载：直接填表单，无弹窗
        self._apply_values(presets[name])
        self._flash_preset_highlight()

    def on_preset_selected(self, name):
        """下拉选择：若表单有未应用更改，先把当前表单自动存为新预设，再载入所选。"""
        if self._dirty():
            cur = self.preset_var.get().strip()
            cur_name = cur if (cur and cur != name) else fmt("preset.autobackup", t=time.strftime('%m-%d %H:%M:%S'))
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
        self._flash_preset_highlight()

    def _flash_preset_highlight(self):
        """预设选中高亮（D4，动效 6）：下拉框底色插到 #0a84ff 12% 等效浅蓝再插回 FIELD。

        动效关时直接跳过（无动画，不打扰）。降级（animate 返回 -1）时 on_done
        已同步执行，无需处理 id。
        """
        if not self._motion_on():
            return
        target = format_hex(lerp(C_FIELD, C_ACC, 0.12))  # 蓝 12% 等效浅蓝（随主题）

        def _out(p):
            t = ease_out_cubic(p, 1)
            self.cmb_preset.configure(fg_color=format_hex(lerp(C_FIELD, target, t)))

        def _back(p):
            t = ease_out_cubic(p, 1)
            self.cmb_preset.configure(fg_color=format_hex(lerp(target, C_FIELD, t)))

        self.anim.animate(_out, 120, on_done=lambda: self.anim.animate(_back, 120))

    def delete_preset(self):
        name = self.preset_var.get()
        if not name:
            messagebox.showwarning(t("mb.hint"), t("msg.preset.pick"))
            return
        if not messagebox.askyesno(t("mb.confirm"), fmt("msg.preset.del", n=name)):
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
        return build_params(values, extras, FIELDS) != get_app_parameters(self.service)

    def apply_changes(self):
        """写回表单参数；服务运行中则确认后自动重启，未运行仅写回。"""
        values, extras = self._collect()
        new_text = build_params(values, extras, FIELDS)
        cur = get_app_parameters(self.service)
        if new_text == cur:
            messagebox.showinfo(t("mb.unchanged"), t("msg.nochange"))
            return
        state = sc_query_state(self.service)
        if state == "RUNNING":
            msg = fmt("msg.apply.run", s=self.service, n=new_text, o=cur)
        else:
            msg = fmt("msg.apply.stop", s=self.service, n=new_text, o=cur)
        if not messagebox.askyesno(t("mb.doublecheck"), msg):
            return
        ok, out = set_app_parameters(self.service, new_text)
        if not ok:
            messagebox.showerror(t("mb.fail"), fmt("msg.write.fail", o=out))
            return
        # 应用成功即时反馈（D4）：按钮短变绿 240ms 后插回原色（无论运行/未运行）
        self._flash_applied()
        if state == "RUNNING":
            self.do_restart()
        else:
            messagebox.showinfo(t("mb.success"), t("msg.written"))
            self.refresh_status()

    def _flash_applied(self):
        """「应用更改」成功反馈：fg_color 从 C_ACC 插到 C_RUN（240ms）再插回 C_ACC。

        动效关时跳过；降级（-1）时两段 on_done 同步执行，无需处理 id。
        """
        if not self._motion_on():
            return

        def _to_green(p):
            t = ease_out_cubic(p, 1)
            self.btn_apply.configure(fg_color=format_hex(lerp(C_ACC, C_RUN, t)))

        def _to_blue(p):
            t = ease_out_cubic(p, 1)
            self.btn_apply.configure(fg_color=format_hex(lerp(C_RUN, C_ACC, t)))

        self.anim.animate(_to_green, 240,
                          on_done=lambda: self.anim.animate(_to_blue, 240))

    # ---- 生命周期 ----
    def do_action(self, action):
        ok, msg = sc_action(action, self.service)
        if ok:
            messagebox.showinfo(t("mb.success"), fmt("msg.sc.done", a=action, s=self.service))
        else:
            messagebox.showerror(t("mb.fail"), fmt("msg.sc.fail", a=action, m=msg))
        self.after(1500, self.refresh_status)

    def do_restart(self):
        """启动重启工作线程（防重入：进行中再点只提示）。"""
        if self._restarting:
            messagebox.showinfo(t("mb.hint"), t("msg.restarting"))
            return
        self._restarting = True
        # 主线程读取表单值后传入 worker；worker 内不再触碰任何 Tk 对象
        host = self.var["host"].get().strip() or "127.0.0.1"
        port = self.var["port"].get().strip() or "8080"
        threading.Thread(target=self._restart_worker,
                         args=(self.service, host, port), daemon=True).start()

    def _restart_worker(self, service, host, port):
        """后台重启序列：只允许 _log_q.put 与子进程调用，禁止碰控件 / self.after。"""
        # 停止前健康检查（只提示，不阻断——重启本身就是修复手段）
        if not check_health(host, port)[0]:
            self._log_q.put(t("log.restart.unhealthy"))
        self._log_q.put(fmt("log.restart.stop", s=service))
        ok, msg = sc_action("stop", service)
        if not ok:
            self._log_q.put(fmt("log.restart.stopfail", m=msg))
            self._log_q.put("__RESTART_DONE__")
            return
        stopped = False
        for _ in range(40):
            if sc_query_state(service) == "STOPPED":
                stopped = True
                break
            time.sleep(0.5)
        if not stopped:
            self._log_q.put(t("log.restart.stoptimeout"))
            self._log_q.put("__RESTART_DONE__")
            return
        self._log_q.put("__REFRESH_STATUS__")
        self._log_q.put(t("log.restart.start"))
        sc_action("start", service)
        for _ in range(120):
            if sc_query_state(service) == "RUNNING":
                ok, d = check_health(host, port)
                if ok:
                    self._log_q.put(fmt("log.restart.ready", d=d))
                    break
            time.sleep(0.5)
        self._log_q.put("__REFRESH_STATUS__")
        self._log_q.put("__RESTART_DONE__")

    def apply_auto(self):
        """下拉即选即应用（先确认；无成功弹窗，失败才提示）。"""
        mode = {t("boot.auto"): "auto", t("boot.manual"): "manual", t("boot.disabled"): "disabled"}.get(self.auto_var.get(), "manual")
        if not messagebox.askyesno(t("mb.confirm"), fmt("msg.auto.confirm", m=self.auto_var.get())):
            return
        ok, out = set_start_mode(self.service, mode)
        if not ok:
            messagebox.showerror(t("mb.fail"), fmt("msg.auto.fail", o=out))

    # ---- 日志 ----
    def toggle_log(self):
        """展开/折叠日志面板：动效开时高度 40↔170 平滑过渡（D5，动效 4/5）。

        连点防重入：先 cancel 在途过渡动画再反向续跑；折叠的 pack_forget
        必须在高度动画完成后执行（闪烁防护）；动效关时瞬时切换。
        """
        self._log_open.set(not self._log_open.get())
        if self._log_anim_id > 0:
            self.anim.cancel(self._log_anim_id)
            self._log_anim_id = -1
        if self._log_open.get():
            self.btn_log_toggle.configure(text=t("log.expanded"), text_color=C_TXT)
            # 关键：动画期间用 fill="x"（高度由 configure(height) 控制），
            # 不能用 expand=True——pack 的 expand 会每帧把高度拉回可用空间，
            # 与动画的 height 写入打架形成高频抽动。动画完成后才切 expand。
            self.txt_log.pack(fill="x", padx=14, pady=(0, 12))
            if not self._motion_on():
                self.txt_log.configure(height=170)
                self.txt_log.pack_configure(fill="both", expand=True)
                return
            self.txt_log.configure(height=40)

            def _open_frame(p):
                t = ease_out_cubic(p, 1)
                self.txt_log.configure(height=int(40 + (170 - 40) * t))

            def _open_done():
                self._log_anim_id = -1
                self.txt_log.configure(height=170)
                self.txt_log.pack_configure(fill="both", expand=True)  # 动画结束才撑满

            self._log_anim_id = self.anim.animate(_open_frame, 180, on_done=_open_done)
            if self._log_anim_id <= 0:  # 瞬时/降级：on_done 已同步执行
                self._log_anim_id = -1
        else:
            self.btn_log_toggle.configure(text=t("log.collapsed"), text_color=C_MUT)
            if not self._motion_on():
                self.txt_log.configure(height=40)
                self.txt_log.pack_forget()
                return

            def _close_frame(p):
                t = ease_in_cubic(p, 1)
                self.txt_log.configure(height=int(170 - (170 - 40) * t))

            def _close_done():
                self._log_anim_id = -1
                self.txt_log.configure(height=40)
                self.txt_log.pack_forget()  # 动画完成后才移除，避免闪烁

            self._log_anim_id = self.anim.animate(_close_frame, 140, on_done=_close_done)
            if self._log_anim_id <= 0:  # 瞬时/降级：on_done 已同步执行
                self._log_anim_id = -1

    def _log_line(self, text):
        """主线程专用：直接写日志控件。worker 线程一律经 _log_q.put。"""
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", text + "\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _drain_log(self):
        """主线程消费日志队列：普通消息打印，哨兵驱动状态复位/刷新。"""
        if self._stop_poll:
            return
        while True:
            try:
                text = self._log_q.get_nowait()
            except queue.Empty:
                break
            if text == "__RESTART_DONE__":
                self._restarting = False
            elif text == "__REFRESH_STATUS__":
                self.refresh_status()
            else:
                self._log_line(text)
        self.after(120, self._drain_log)

    def _start_polling(self):
        self._drain_log()
        self._poll_log()
        self._status_worker.start()
        self._drain_status()
        self._poll_health()

    def _poll_log(self):
        if self._stop_poll:
            return
        if getattr(self, "_resizing", False):
            self.after(1500, self._poll_log)  # 缩放期间跳过读文件+渲染
            return
        try:
            log_path = self._log_path()
            if log_path and os.path.exists(log_path):
                with open(log_path, "rb") as fh:
                    fh.seek(0, 2)
                    size = fh.tell()
                    if size < self._log_off:
                        self._log_off = 0  # 文件被截断/轮转，从头读尾部
                    if size > self._log_off:
                        fh.seek(self._log_off)
                        data = fh.read().decode("utf-8", "replace")
                        self._log_off = size
                        self._append_log_lines(data)
        except Exception:  # noqa: BLE001
            pass
        self.after(1500, self._poll_log)

    def _append_log_lines(self, data):
        """增量渲染：只把文件尾部新增行追加进日志框，超 500 行裁剪头部。

        新行渐隐高亮（D5，动效 ≤200ms）：插入前记 mark 起点（随编辑自动调整），
        插入后 flash tag 打到起点→结尾，200ms 后移除背景；动效关或单批 >200 行
        时跳过，不打断现有增量渲染逻辑。
        """
        new_lines = data.splitlines()
        if not new_lines:
            return
        start = None
        if self._motion_on() and len(new_lines) <= 200:
            self.txt_log.configure(state="normal")
            self.txt_log._textbox.mark_set("flash_start", "end-1c")
            start = self.txt_log._textbox.index("flash_start")
        self.txt_log.configure(state="normal")
        for ln in new_lines:
            self.txt_log.insert("end", ln + "\n")
        if start is not None:
            self.txt_log._textbox.tag_add("flash", "flash_start", "end-1c")
            self.txt_log.after(200, self._clear_flash_tag)
        if int(self.txt_log.index("end-1c").split(".")[0]) > 500:
            self.txt_log.delete("1.0", "501.0")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _clear_flash_tag(self):
        """新行渐隐收尾：移除 flash 背景 tag（控件销毁后调用会抛 TclError，吞掉）。"""
        try:
            self.txt_log._textbox.tag_delete("flash")
        except Exception:  # noqa: BLE001 - 控件已销毁/重建时无需处理
            pass

    def _log_path(self):
        """日志路径：优先 AppDirectory 推导（T4），失败回退硬编码 ERR_LOG。"""
        try:
            d = app_directory(self.service)
            return os.path.join(d, "server.err") if d else ERR_LOG
        except Exception:  # noqa: BLE001
            return ERR_LOG

    def _poll_health(self):
        """纯调度器（拖拽卡顿修复）：只派活给 worker，不做任何同步阻塞。
        全部 nssm/sc/urlopen 调用移入 _status_worker_loop（daemon 线程），
        结果经 _status_q 回主线程，由 _drain_status 应用 UI。"""
        if self._stop_poll:
            return
        svc = self.service
        host = self.var["host"].get().strip() or "127.0.0.1"
        port = self.var["port"].get().strip() or "8080"
        # 轻量防堆积：worker 没消费完就跳过一次派活（服务状态变化不丢，
        # 只是延迟一拍，drain 立即触发下一轮）
        if self._status_q.qsize() < 2:
            try:
                snapshot = self._collect()[0]   # 主线程读 Tk 变量（安全）
            except Exception:  # noqa: BLE001
                snapshot = None
            self._status_q.put(("poll", svc, host, port, snapshot))
        self.after(3000, self._poll_health)

    def _dirty_cached(self):
        """主线程 dirty 读取（纯缓存，绝不阻塞）：真正的 nssm 对比由 worker
        完成并回传。缩放/拖拽期间主线程永远不 spawn 子进程。"""
        return self._dirty_cache if self._dirty_cache is not None else False

    def _status_worker_loop(self):
        """探活 worker（daemon）：所有同步阻塞调用都在这条线程里。
        nssm.exe / sc / urlopen 卡住不会冻结主线程；结果 put 回 _status_q。"""
        import json as _json
        while not self._stop_poll:
            try:
                item = self._status_q.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                break
            tag, svc, host, port, snapshot = item
            try:
                if tag in ("poll", "refresh"):
                    state = sc_query_state(svc)
                    ok, detail = (False, "未探活") if state != "RUNNING" else check_health(host, port)
                    dirty = None
                    if snapshot is not None:
                        try:
                            cur = get_app_parameters(svc)
                            dirty = build_params(snapshot, self.extras, FIELDS) != cur
                        except Exception:  # noqa: BLE001
                            dirty = None
                    self._status_r.put(("result", state, ok, detail, dirty))
            except Exception as exc:  # noqa: BLE001 - worker 任何异常不致死循环
                self._status_r.put(("result", "UNKNOWN", False, f"worker 异常: {exc}", None))

    def _on_configure(self, _event=None):
        """缩放/拖拽防抖（缩放卡顿修复）：置 _resizing 并重置 300ms 定时器；
        连续 WM_CONFIGURE 期间 _drain_status/_poll_log 跳过 UI 应用。
        注意：不在此处隐藏滚动条——展开日志面板等任何布局重排都会触发
        Configure，隐藏/恢复滚动条会形成「Configure→隐藏→重排→Configure」
        的振荡循环（日志面板持续抽动的根因）。滚动条保持常驻。"""
        self._resizing = True
        if self._resize_after is not None:
            try:
                self.after_cancel(self._resize_after)
            except Exception:  # noqa: BLE001
                pass
        self._resize_after = self.after(300, self._resize_done)

    def _resize_done(self):
        self._resizing = False
        self._resize_after = None

    def _drain_status(self):
        """主线程消费 _status_r：应用状态/探活/按钮联动/dirty 提示。
        节流合并（一次 drain 处理全部积压）；窗口缩放/拖拽期间（_resizing）
        跳过 UI 应用，避免与 WM_CONFIGURE 高频重排抢主线程。"""
        if self._stop_poll:
            return
        got = None
        try:
            while True:
                item = self._status_r.get_nowait()
                if item and item[0] == "result":
                    got = item
        except queue.Empty:
            pass
        if getattr(self, "_resizing", False):
            self.after(500, self._drain_status)
            return
        if got is not None:
            _, state, ok, detail, dirty = got
            try:
                if state == "RUNNING":
                    self.btn_start.configure(state="disabled")
                    self.btn_stop.configure(state="normal")
                elif state == "STOPPED":
                    self.btn_start.configure(state="normal")
                    self.btn_stop.configure(state="disabled")
                else:
                    self.btn_start.configure(state="disabled")
                    self.btn_stop.configure(state="disabled")
                self.lbl_state.configure(text=fmt("status.svc", st=state),
                                         text_color=self._state_color(state))
                if state == "RUNNING":
                    self.lbl_health.configure(
                        text=(fmt("status.health.ok", d=detail[:40]) if ok else fmt("status.health.bad", d=detail[:40])),
                        text_color=C_RUN if ok else C_RED)
                    self._update_status_dot(state, ok)
                else:
                    self.lbl_health.configure(text=t("health.down"), text_color=C_GRAY)
                    self._update_status_dot(state, True)
                # dirty 由 worker 用表单快照 + nssm 对比回传（主线程永不 spawn nssm）
                if got[4] is not None:
                    self._dirty_cache = got[4]
                dirty = self._dirty_cached()
                self.lbl_dirty.configure(text="● 有未应用的更改" if dirty else "")
                self.btn_revert.configure(state="normal" if dirty else "disabled")
            except Exception:  # noqa: BLE001 - 控件销毁竞态静默
                pass
        self.after(400, self._drain_status)

    def _on_close(self):
        self._stop_poll = True
        self.anim.cancel_all()  # 停掉全部在途动画，帧回调发现不在注册表即自停
        # 取消全部按钮渐隐 after 帧（F1：无泄漏 after；按钮销毁后回调自吞 TclError）
        for tok in list(self._hover_fades.values()):
            try:
                self.after_cancel(tok)
            except Exception:  # noqa: BLE001
                pass
        self._hover_fades.clear()
        # 取消全部字段高亮恢复计时器（D7：无泄漏 after）
        for _k, tok in list(self._field_flash_after.items()):
            try:
                self.after_cancel(tok)
            except Exception:  # noqa: BLE001
                pass
        self._field_flash_after.clear()
        try:
            self.settings["geometry"] = self.geometry()
            self.settings["last_preset"] = self.preset_var.get().strip()
            save_settings(self.settings)
        except Exception:  # noqa: BLE001 - 设置保存失败不阻断退出
            pass
        self.destroy()

    def _motion_on(self):
        """动效总开关（design-guide §五）：关闭后 D3-D7 所有动画直跳终态。"""
        return bool(self.settings.get("motion_enabled", True))

    # ---- 设置窗口 ----
    def open_settings(self):
        win = ctk.CTkToplevel(self)
        win.title(t("settings.title"))
        win.geometry("420x320")
        win.transient(self)
        win.grab_set()
        self._settings_win = win

        ctk.CTkLabel(win, text=t("settings.lang"), font=F_BODY, anchor="w"
                     ).pack(fill="x", padx=20, pady=(20, 4))
        lang_menu = ctk.CTkOptionMenu(
            win, values=["中文", "English"], width=180, font=F_BODY,
            command=lambda v: self._change_language(v, win))
        lang_menu.set("中文" if strings._current == "zh" else "English")
        lang_menu.pack(anchor="w", padx=20)

        ctk.CTkLabel(win, text=t("settings.appear"), font=F_BODY, anchor="w"
                     ).pack(fill="x", padx=20, pady=(16, 4))
        appear_names = {"system": t("appear.system"), "light": t("appear.light"),
                        "dark": t("appear.dark")}
        rev = {v: k for k, v in appear_names.items()}
        appear_menu = ctk.CTkOptionMenu(
            win, values=list(appear_names.values()), width=180, font=F_BODY,
            command=lambda v: self._change_appearance(rev[v], win))
        appear_menu.set(appear_names.get(self.settings.get("appearance", "system"),
                                         t("appear.system")))
        appear_menu.pack(anchor="w", padx=20)

        # 动效总开关（即时生效，无需 _restart_ui）
        self._motion_var = tk.BooleanVar(value=self.settings.get("motion_enabled", True))
        motion_cb = ctk.CTkCheckBox(
            win, text=t("settings.motion"), variable=self._motion_var,
            font=F_BODY, text_color=C_TXT, fg_color=C_ACC,
            hover_color=C_ACCH, border_color=C_BORDER, corner_radius=6,
            command=self._change_motion)
        motion_cb.pack(anchor="w", padx=20, pady=(16, 4))

        ctk.CTkLabel(win, text=t("settings.note"), font=F_SMALL, text_color=C_MUT,
                     wraplength=360, justify="left").pack(fill="x", padx=20, pady=(16, 0))
        self._btn(win, t("settings.close"), win.destroy).pack(pady=(14, 12))

    def _change_language(self, shown, win=None):
        self.settings["language"] = "zh" if shown == "中文" else "en"
        strings.set_lang(self.settings["language"])
        save_settings(self.settings)
        self._restart_ui()

    def _change_appearance(self, mode, win=None):
        self.settings["appearance"] = mode
        save_settings(self.settings)
        ctk.set_appearance_mode({"system": "system", "light": "light",
                                 "dark": "dark"}[mode])
        self._restart_ui()

    def _change_motion(self):
        """动效开关回调：写设置并落盘，即时生效，不重启 UI。"""
        self.settings["motion_enabled"] = bool(self._motion_var.get())
        save_settings(self.settings)

    def _restart_ui(self):
        """销毁并按新语言/调色板重建全部部件（设置即时生效）。"""
        _apply_palette("dark" if self.settings.get("appearance") == "dark" else "light")
        for w in self.winfo_children():
            w.destroy()
        self.var.clear()
        self.widgets.clear()
        self.val_labels.clear()
        # 状态圆点动效复位：新控件未知，取消在途动画并重置全部 id/守卫
        self.anim.cancel_all()
        self._log_anim_id = -1
        # 字段高亮计时器全部失效（旧控件已销毁），清空即可（D7）
        self._field_flash_after.clear()
        self._suppress_trace = False
        # F1 按钮渐隐帧：旧控件已随上方 destroy 销毁，取消防残留 after 帧。
        # 帧回调发现 token 不在注册表即自停，兜底 winfo_exists 保证无 TclError。
        for tok in list(self._hover_fades.values()):
            try:
                self.after_cancel(tok)
            except Exception:  # noqa: BLE001
                pass
        self._hover_fades.clear()
        # D8 折叠分组展开状态保留（group_open 在 _build_widgets 里按存量恢复）
        self._breathing = False
        self._breath_id = -1
        self._flash_id = -1
        self._breath_resume = False
        self._flash_armed = True
        self.title(t("app.title"))
        self.configure(fg_color=C_BG)
        self._build_widgets()
        self.refresh_all()


def main():
    app = ControlGUI()
    app.mainloop()


if __name__ == "__main__":
    main()

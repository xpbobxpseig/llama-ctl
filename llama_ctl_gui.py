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
import math
import queue
import sys
import threading
import time
import tkinter as tk
from PIL import Image as PILImage
from tkinter import filedialog, font as tkfont, messagebox

from nssm_adapter import (
    DEFAULT_SERVICE, get_app_parameters, set_app_parameters,
    get_start_mode, set_start_mode, sc_query_state, sc_action,
    list_nssm_services, check_health, app_directory,
)
from params import parse_params, build_params, semantically_equal
from settings import load_settings, save_settings
from presets import load_presets, save_presets
from motion import Animator, format_hex, lerp, parse_hex, ease_out_cubic, ease_in_cubic
import strings
import updater
import installer
from strings import t, fmt
import icon as ic


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
# 日志路径优先从 NSSM AppDirectory 推导（_log_path）；ERR_LOG 仅作推导失败时的回退。
# 以下路径均可用环境变量覆盖，默认值与历史行为一致：
#   LLAMA_CTL_ERR_LOG        日志尾随回退路径
#   LLAMA_CTL_LLAMA_DIR      llama.cpp 安装目录（官方更新替换目标回退）
#   LLAMA_CTL_DOWNLOAD_DIR   官方资产下载缓存目录
#   LLAMA_CTL_BACKUP_DIR     旧文件备份根目录
ERR_LOG = os.environ.get("LLAMA_CTL_ERR_LOG") or r"F:\llama.cpp\server.err"
LLAMA_DIR = os.environ.get("LLAMA_CTL_LLAMA_DIR") or r"F:\llama.cpp"
LLAMA_SERVER_EXE = os.path.join(LLAMA_DIR, "llama-server.exe")
UPD_DOWNLOAD_DIR = os.environ.get("LLAMA_CTL_DOWNLOAD_DIR") or r"F:\llama_ctl\downloads"
UPD_BACKUP_ROOT = os.environ.get("LLAMA_CTL_BACKUP_DIR") or r"F:\llama_ctl\backup"
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
     "label": "模型文件 (-m/--model)", "label_en": "Model file (-m/--model)",
     "aliases": ["-m", "--model"],
     "help": "要加载的 GGUF 模型文件路径。这是最核心的参数——决定用哪个开源模型（如 Qwen、Llama、DeepSeek、GLM 等）。"
             " 模型越大、量化越高，占显存越多、效果与速度各异。路径必须是本机存在的 .gguf 文件。",
     "help_en": "Path to the GGUF model to load. The most important setting: it decides which open model is served "
             "(Qwen, Llama, DeepSeek, GLM, etc.). Bigger or higher-quantization models use more VRAM. "
             "The file must exist on this machine."},

    {"key": "mmproj", "group": "模型与视觉", "kind": "path",
     "label": "视觉投影 (--mmproj)", "label_en": "Vision projector (--mmproj)",
     "aliases": ["--mmproj", "-mm"],
     "help": "多模态投影文件（.gguf）。仅当模型支持看图/传图时才需要，例如 Qwen-VL 类模型。"
             " 填了之后服务才能接收图片。纯文本模型留空即可。",
     "help_en": "Multimodal projector file (.gguf). Only needed for vision models such as Qwen-VL. "
             "Leave empty for text-only models."},

    {"key": "alias", "group": "模型与视觉", "kind": "text",
     "label": "模型别名 (-a/--alias)", "label_en": "Model alias (-a/--alias)",
     "aliases": ["-a", "--alias"],
     "help": "给模型起一个对外暴露的名字（逗号可分隔多个）。调用 OpenAI 兼容 API 时用它做 model 字段，方便区分。"
             " 例如 qwen3.8-27b。可留空，服务会用模型自带 id。",
     "help_en": "Name(s) exposed by the server for this model (comma-separated). Used as the model field in "
             "OpenAI-compatible API calls, e.g. qwen3.8-27b. Leave empty to use the model's own ID."},

    # ---- 加速（GPU / 投机解码）----
    {"key": "ngl", "group": "加速", "kind": "slider",
     "label": "GPU 层数 (-ngl)", "label_en": "GPU layers (-ngl)",
     "aliases": ["-ngl", "--n-gpu-layers", "--gpu-layers"],
     "min": 0, "max": 200, "step": 1, "unit": "层", "unit_en": "layers",
     "default": 99,
     "help": "把多少层模型权重放到显卡显存里。数值越大越快（显存够时尽量拉满）。"
             " 设 0 = 纯 CPU 推理（极慢）。设 99 表示尽量全部上 GPU。"
             " 若显存不足会 OOM 崩溃，此时调小。效果无影响，只影响速度。",
     "help_en": "How many model layers to offload to the GPU. Higher is faster (raise it as long as VRAM allows). "
             "0 = CPU-only inference (very slow); 99 = offload as much as possible. "
             "Lower it if you run out of VRAM. Quality is unaffected; only speed changes."},

    {"key": "spec_type", "group": "加速", "kind": "combo",
     "label": "投机解码 (-spec-type)", "label_en": "Speculative decoding (-spec-type)",
     "aliases": ["--spec-type"],
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
             " 注意 MTP 会强制单槽（-np 1），且 LLM 类模型才有效；嵌入/小模型无需开。",
     "help_en": "Speculative decoding: a draft guesses several tokens ahead and the main model verifies the whole batch "
             "at once, speeding up generation. draft-mtp is the common pick (uses the model's built-in MTP head, "
             "no extra file). Note: MTP forces a single slot (-np 1); it only helps LLM-class models."},

    {"key": "spec_draft_model", "group": "加速", "kind": "path",
     "label": "草稿模型 (--spec-draft-model)", "label_en": "Draft model (--spec-draft-model)",
     "aliases": ["--spec-draft-model", "-md", "--model-draft"],
     "help": "投机解码用的『草稿模型』GGUF 文件路径。仅当 spec-type 选 draft-* 时需要："
             " 例如 draft-dflash 要填 DFlash2 草稿文件，draft-eagle3 要填 EAGLE3 草稿文件。"
             " 填错或不填对应草稿文件，服务会启动失败。普通模式（none）留空即可。",
     "help_en": "GGUF path of the draft model used for speculative decoding. Required for draft-* spec types only: "
             "e.g. draft-dflash needs the DFlash2 draft file, draft-eagle3 needs the EAGLE3 draft file. "
             "A wrong or missing draft file will stop the server from starting. Leave empty otherwise."},

    {"key": "spec_draft_n_max", "group": "加速", "kind": "slider",
     "label": "草稿长度 (--spec-draft-n-max)", "label_en": "Draft length (--spec-draft-n-max)",
     "aliases": ["--spec-draft-n-max"],
     "min": 1, "max": 16, "step": 1, "unit": "tok", "unit_en": "tok", "default": 3,
     "help": "每次投机最多猜测的草稿 token 数。越大单次验证越多、提速潜力越高，但草稿质量下降可能反噬。"
             " 默认 3 通常够用；draft-dflash 可试 4~8。仅 draft/ngram 模式生效。",
     "help_en": "Maximum number of draft tokens guessed per speculation step. Larger values can verify more at once, "
             "but poor drafts may backfire. Default 3 is usually fine; try 4-8 for draft-dflash. "
             "Only applies to draft/ngram modes."},

    # ---- 上下文与显存 ----
    {"key": "ctx_size", "group": "上下文与显存", "kind": "slider",
     "label": "上下文长度 (-ctx-size)", "label_en": "Context length (-ctx-size)",
     "aliases": ["--ctx-size", "-c"],
     "min": 512, "max": 1048576, "step": 512, "unit": "token", "unit_en": "tokens",
     "default": 131072, "snap": [8192, 16384, 32768, 65536, 131072, 262144, 524288, 1048576],
     "quick": [32768, 65536, 131072, 262144, 524288, 1048576],
     "help": "上下文窗口大小，即可同时『记住』的最长对话长度（含历史）。"
             " 越大能处理的文档/对话越长，但占用显存越多、加载越慢。"
             " 常用档位：32K（轻量）/128K（本机 24G 稳妥）/256K（需配 KV 量化）/512K~1M（长文档，强烈建议 KV 量化）。"
             " 点下方快捷按钮即可一键跳到档位。注：旧参数里 '-c' 是 '--ctx-size' 简写，冲突时本工具只保留一个。",
     "help_en": "Context window size: the longest conversation (including history) the model can keep in memory at once. "
             "Bigger handles longer documents but uses more VRAM and loads slower. "
             "Common picks: 32K light / 128K safe on 24GB VRAM / 256K needs KV quantization / 512K-1M for long docs. "
             "Use the quick buttons below to jump. Note: '-c' is an alias of '--ctx-size'; duplicates are deduplicated."},

    {"key": "ctk", "group": "上下文与显存", "kind": "combo",
     "label": "KV cache 类型 K (-ctk)", "label_en": "KV cache type K (-ctk)",
     "aliases": ["-ctk", "--cache-type-k"],
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
             " 长上下文（≥64K）强烈建议 q4_0 / iq4_nl / q8_0。ctk/ctv 通常设为一致。",
     "help_en": "KV cache stores attention memory. Quantizing it saves a lot of VRAM and enables longer contexts, "
             "with a small precision loss. For contexts >= 64K, q4_0 / iq4_nl / q8_0 are recommended. "
             "ctk and ctv are usually set the same."},

    {"key": "ctv", "group": "上下文与显存", "kind": "combo",
     "label": "KV cache 类型 V (-ctv)", "label_en": "KV cache type V (-ctv)",
     "aliases": ["-ctv", "--cache-type-v"],
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
     "help": "KV cache 的 V（Value）部分类型。一般与 ctk 设成相同量化。见上方 ctk 说明。",
     "help_en": "Type of the V (Value) part of the KV cache. Usually set the same as ctk. See ctk above."},

    {"key": "flash_attn", "group": "上下文与显存", "kind": "combo",
     "label": "Flash Attention (-fa)", "label_en": "Flash Attention (-fa)",
     "aliases": ["-fa", "--flash-attn"],
     "options": ["auto", "on", "off"],
     "option_help": {
         "auto": "由 llama.cpp 自动判断是否启用（默认，最稳妥）。",
         "on": "强制开启。现代 NVIDIA 显卡开启后更省显存、更快。",
         "off": "关闭。极少数老卡或异常时回退用。",
     },
     "help": "Flash Attention 是一种更高效的注意力计算方式：更快、更省显存。"
             " 现代显卡（如 RTX 40 系）建议 on；不确定就 auto。",
     "help_en": "Flash Attention is a more efficient attention implementation: faster and lower VRAM. "
             "Use 'on' on modern GPUs (e.g. RTX 40 series); 'auto' when unsure."},

    # ---- 并发与吞吐 ----
    {"key": "parallel", "group": "并发与吞吐", "kind": "slider",
     "label": "并发槽数 (-np)", "label_en": "Parallel slots (-np)",
     "aliases": ["-np", "--parallel"],
     "min": 1, "max": 16, "step": 1, "unit": "槽", "unit_en": "slots",
     "default": 1,
     "help": "服务能同时处理的请求『槽位』数。1 = 单用户独占；调大可并发服务多人，但每个槽都占显存/上下文。"
             " 开投机解码(MTP)时会被强制为 1。普通个人使用设 1~4。",
     "help_en": "Number of request slots the server handles concurrently. 1 = single-user exclusive. "
             "More slots serve multiple users but each consumes VRAM/context. "
             "MTP speculative decoding forces this to 1. Use 1-4 for personal use."},

    {"key": "batch_size", "group": "并发与吞吐", "kind": "slider",
     "label": "批大小 (-b)", "label_en": "Batch size (-b)",
     "aliases": ["-b", "--batch-size"],
     "min": 128, "max": 8192, "step": 128, "unit": "tok", "unit_en": "tok",
     "default": 2048,
     "help": "一次处理的最大逻辑 token 批量。影响吞吐（多人/长提示时）。调太大占显存。"
             " 默认 2048 通常够用；若要更高并发可适度上调。",
     "help_en": "Maximum logical token batch processed at once. Affects throughput with concurrent users or long prompts. "
             "Too large costs VRAM. Default 2048 is usually enough; raise it for higher concurrency."},

    {"key": "ubatch_size", "group": "并发与吞吐", "kind": "slider",
     "label": "物理批大小 (-ub)", "label_en": "Physical batch size (-ub)",
     "aliases": ["-ub", "--ubatch-size"],
     "min": 64, "max": 2048, "step": 64, "unit": "tok", "unit_en": "tok",
     "default": 512,
     "help": "物理批大小，配合 batch-size 使用。一般保持为 batch 的约 1/4。默认 512 即可，调参会同时带动吞吐与显存。",
     "help_en": "Physical batch size, used together with batch-size. Usually about 1/4 of the batch size. "
             "Default 512 is fine; changes affect both throughput and VRAM."},

    {"key": "threads", "group": "并发与吞吐", "kind": "slider",
     "label": "CPU 线程 (-t)", "label_en": "CPU threads (-t)",
     "aliases": ["-t", "--threads"],
     "min": 1, "max": max(CPU_THREADS, 8), "step": 1, "unit": "线程", "unit_en": "threads",
     "default": CPU_THREADS,
     "help": "生成时使用的 CPU 线程数。仅在部分计算落到 CPU 时影响速度（如 ngl 没拉满）。"
             " 一般设为本机物理核心数；全 GPU 推理时影响不大。",
     "help_en": "Number of CPU threads used during generation. Only matters when some work stays on the CPU "
             "(e.g. GPU layers not fully offloaded). Usually set to the physical core count; "
             "little effect when fully GPU-accelerated."},

    # ---- 采样（生成质量）----
    {"key": "temperature", "group": "采样", "kind": "slider",
     "label": "温度 (--temp)", "label_en": "Temperature (--temp)",
     "aliases": ["--temp", "--temperature"],
     "min": 0, "max": 2, "step": 0.05, "unit": "",
     "default": 0.8,
     "help": "随机性。低（0.2）= 更确定、更死板；高（1.0+）= 更发散、更有创意但易跑题。"
             " 日常对话 0.7~0.9；代码/事实问答可调低到 0.2~0.5；0 = 贪心（最确定）。",
     "help_en": "Sampling randomness. Low (0.2) = more deterministic and rigid; high (1.0+) = more creative but prone to drift. "
             "Use 0.7-0.9 for chat, 0.2-0.5 for code/factual answers; 0 = greedy (most deterministic)."},

    {"key": "min_p", "group": "采样", "kind": "slider",
     "label": "min-p (--min-p)", "label_en": "min-p (--min-p)",
     "aliases": ["--min-p"],
     "min": 0, "max": 0.5, "step": 0.01, "unit": "",
     "default": 0.05,
     "help": "最低概率阈值：只从累计概率足够高的候选里采样，过滤垃圾 token。"
             " 0.05 是 llama.cpp 默认；调高更『保守』，调 0 关闭。与 temperature 配合控制质量。",
     "help_en": "Minimum probability threshold: samples only from candidates whose cumulative probability is high enough, "
             "filtering bad tokens. 0.05 is the llama.cpp default; higher is more conservative; 0 disables it. "
             "Works with temperature to control quality."},

    {"key": "top_k", "group": "采样", "kind": "slider",
     "label": "top-k (--top-k)", "label_en": "top-k (--top-k)",
     "aliases": ["--top-k"],
     "min": 0, "max": 100, "step": 1, "unit": "", "default": 40,
     "help": "只从概率最高的前 k 个候选里采样。k 越小输出越聚焦、越可预测；k 越大越发散。"
             " 默认 40；设 0 = 关闭 top-k（只看 top-p）。与 top-p 叠加使用，共同限制候选集。",
     "help_en": "Sample only from the top-k highest-probability candidates. Smaller k = more focused and predictable; "
             "larger k = more diverse. Default 40; 0 disables top-k (top-p only). Combined with top-p."},

    {"key": "top_p", "group": "采样", "kind": "slider",
     "label": "top-p (--top-p)", "label_en": "top-p (--top-p)",
     "aliases": ["--top-p"],
     "min": 0, "max": 1, "step": 0.01, "unit": "", "default": 0.95,
     "help": "核采样：只从累计概率达 p 的最小候选集里采样。p 越小越保守（如 0.9 只取覆盖 90% 概率的词），"
             " p=1.0 = 关闭。默认 0.95。与 top-k 配合：先按 top-k 截前 k 个，再在其中按 top-p 截概率。",
     "help_en": "Nucleus sampling: sample only from the smallest candidate set covering cumulative probability p. "
             "Smaller p = more conservative; p=1.0 disables it. Default 0.95. With top-k, candidates are first "
             "cut to k, then by top-p."},

    {"key": "seed", "group": "采样", "kind": "text",
     "label": "随机种子 (-s)", "label_en": "Random seed (-s)",
     "aliases": ["-s", "--seed"],
     "help": "随机种子。固定一个整数可让生成『可复现』（同样输入同样输出）。-1 = 每次随机。调试/评测时设固定值，日常留空或 -1。",
     "help_en": "Random seed. A fixed integer makes generation reproducible (same input, same output). "
             "-1 = random every time. Set a fixed value for debugging/evaluation, otherwise leave empty or -1."},

    {"key": "jinja", "group": "采样", "kind": "check",
     "label": "Jinja 模板 (--jinja)", "label_en": "Jinja template (--jinja)",
     "aliases": ["--jinja"],
     # 官方提供成对开关 `--jinja, --no-jinja`（默认开启）：取消勾选必须显式写
     # --no-jinja，否则「不写任何标志」= 保持默认开启，用户以为关掉了其实没关。
     "off_aliases": ["--no-jinja"],
     "help": "启用服务端 Jinja 聊天模板渲染。参考配置（Qwen 官方示例）均带 --jinja，"
             " 能正确套用模型的对话/思考模板。本服务也应勾上，否则可能用错模板导致格式异常。",
     "help_en": "Enable server-side Jinja chat template rendering. Official Qwen examples include --jinja to apply "
             "the model's chat/thinking template correctly. Keep it enabled, otherwise the wrong template "
             "may cause formatting issues."},

    {"key": "chat_template_kwargs", "group": "采样", "kind": "text",
     "label": "模板参数 (--chat-template-kwargs)", "label_en": "Template args (--chat-template-kwargs)",
     "aliases": ["--chat-template-kwargs"],
     "help": "传给聊天模板的 JSON 参数，控制推理行为。Qwen3.8 常用："
             " 关思考 '{\"enable_thinking\":false}'；调推理强度 '{\"reasoning_effort\":\"low|medium|xhigh\"}'"
             "（默认 xhigh，无 high/max）。需写合法 JSON，含花括号与引号。留空=默认。",
     "help_en": "JSON arguments passed to the chat template to control inference. Common for Qwen3.8: "
             "'{\"enable_thinking\":false}' disables thinking; '{\"reasoning_effort\":\"low|medium|xhigh\"}' "
             "sets reasoning effort (default xhigh; no high/max). Must be valid JSON. Empty = defaults."},

    # ---- 网络 ----
    {"key": "host", "group": "网络", "kind": "combo",
     "label": "监听地址 (--host)", "label_en": "Listen address (--host)",
     "aliases": ["--host"],
     "options": ["127.0.0.1", "0.0.0.0", "localhost"],
     "option_help": {
         "127.0.0.1": "仅本机可访问（最安全，推荐个人使用）。",
         "0.0.0.0": "监听所有网卡，局域网/外网其他机器也能连（注意安全风险，需配 api-key）。",
         "localhost": "等价本机回环。",
     },
     "help": "服务监听哪个网络地址。个人单机用 127.0.0.1 最安全；要让手机/其他电脑访问才用 0.0.0.0（务必同时设 api-key）。",
     "help_en": "Which network address the server listens on. 127.0.0.1 (localhost only) is safest for a single machine; "
             "use 0.0.0.0 only to allow other devices on the LAN (always set an api-key too)."},

    {"key": "port", "group": "网络", "kind": "text",
     "label": "端口 (--port)", "label_en": "Port (--port)",
     "aliases": ["--port"],
     "help": "服务监听的端口。默认 8080。若被占用就改一个（如 8081）。客户端连 http://地址:端口/v1 。",
     "help_en": "Port the server listens on. Default 8080; change it (e.g. 8081) if occupied. "
             "Clients connect to http://address:port/v1."},

    # ---- 高级开关 ----
    {"key": "no_mmap", "group": "高级", "kind": "check",
     "label": "禁用 mmap (--no-mmap)", "label_en": "Disable mmap (--no-mmap)",
     "aliases": ["--no-mmap"],
     "help": "关闭内存映射加载。默认用 mmap 加载更快更省内存；某些特殊环境才需要关掉（会变慢）。一般保持关闭此选项。",
     "help_en": "Disable memory-mapped loading. mmap is faster and uses less memory; only disable in special "
             "environments (it will be slower). Normally leave this unchecked."},

    {"key": "mlock", "group": "高级", "kind": "check",
     "label": "锁定内存 (--mlock)", "label_en": "Lock memory (--mlock)",
     "aliases": ["--mlock"],
     "help": "强制把模型锁在物理内存，避免被系统换页到磁盘导致卡顿。仅在内存充足时有意义；本机显存/GPU 推理一般无需开。",
     "help_en": "Pin the model in physical memory to avoid paging to disk. Only useful with plenty of RAM; "
             "usually unnecessary for GPU inference on this machine."},

    {"key": "no_kv_offload", "group": "高级", "kind": "check",
     "label": "禁用 KV 卸载 (--no-kv-offload)", "label_en": "Disable KV offload (--no-kv-offload)",
     "aliases": ["--no-kv-offload"],
     "help": "不让 KV cache 卸载到 GPU（强制留 CPU）。仅在你明确想压低显存、牺牲速度时启用。常规使用保持关闭。",
     "help_en": "Keep the KV cache on the CPU instead of offloading it to the GPU. Enable only if you deliberately "
             "want lower VRAM usage at the cost of speed. Normally leave unchecked."},

    {"key": "cpu_moe", "group": "高级", "kind": "check",
     "label": "MoE 走 CPU (--cpu-moe)", "label_en": "MoE on CPU (--cpu-moe)",
     "aliases": ["--cpu-moe"],
     "help": "MoE（混合专家）模型把专家权重留在 CPU。仅 MoE 架构模型（如 Qwen-MoE、DeepSeek-MoE）相关；非 MoE 模型忽略。显存不够时可用，但会慢。",
     "help_en": "Keep MoE (mixture-of-experts) expert weights on the CPU. Only relevant for MoE models "
             "(e.g. Qwen-MoE, DeepSeek-MoE); ignored for non-MoE models. Useful when VRAM is tight, but slower."},
]
# 参数分组名 i18n（组头按钮显示；FIELDS 内部仍用中文 key 保证兼容）
GROUP_NAMES = {
    "模型与视觉": "Model & Vision",
    "加速": "Acceleration",
    "上下文与显存": "Context & VRAM",
    "并发与吞吐": "Concurrency",
    "采样": "Sampling",
    "网络": "Network",
    "高级": "Advanced",
}
ALIAS_TO_KEY = {}
for _f in FIELDS:
    for _a in _f["aliases"]:
        ALIAS_TO_KEY[_a] = _f["key"]





# ---------------------------------------------------------------------------
# GUI（CustomTkinter）
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


def _set_appearance(mode):
    """设置 CTk 外观并同步展开调色板（system 解析为实际明暗）。

    返回生效外观名（"light"/"dark"）；C_* 与 _appearance 均以此为单一事实源，
    避免启动与 _restart_ui 各写一套解析逻辑导致反相。
    """
    ctk.set_appearance_mode(
        {"system": "system", "light": "light", "dark": "dark"}.get(mode, "system"))
    # CTk 的 set_appearance_mode("system") 只登记模式，真正的重新检测要等 30ms
    # 轮询（AppearanceModeTracker.update）；紧接着读 get_appearance_mode() 会拿到
    # 上一次手动值，使调色板与 CTk 原生控件反相（主界面停在 light、菜单已翻
    # dark）。这里同步强制一次检测，让两侧立刻一致。显式 light/dark 下该调用
    # 因 appearance_mode_set_by=="user" 为无操作。
    try:
        ctk.AppearanceModeTracker.init_appearance_mode()
    except Exception:  # noqa: BLE001 - 私有 API 缺失时退回轮询时序
        pass
    resolved = "dark" if ctk.get_appearance_mode().lower() == "dark" else "light"
    _apply_palette(resolved)
    ic.set_appearance(resolved)          # 图标缓存按新外观重建
    return resolved


# ---------------------------------------------------------------------------
# 字体令牌（v2 统一字阶，依据 docs/design/font-icon-spec.html）
# ---------------------------------------------------------------------------
# 修掉 v1 的三个结构性问题：
#   1. 卡片标题 / 折叠组头 / 日志开关 三者共用 F_GROUP(12 bold) —— 三个不同角色
#      一个样式，层级消失。现拆为 F_SECTION(卡片) / F_GROUP(组头) / F_BODY(开关)。
#   2. 数值读数 Consolas 12 与文本输入 YaHei 13 行高差 4px，同一行的控件基线不齐。
#      现 F_MONO 取 13（与 F_BODY 同字号），行盒一致。
#   3. 字阶只有 12/13/18 三档且中间没有可用的层级，现为 18/15/13/13/12/11 六档。
#
# Tk 只支持 normal | bold 两种字重（'semibold'/'600' 会抛 TclError），
# 故层级差异只能靠**字号 + 字重**表达，不依赖中间字重。
_UI_FAMILY = "Microsoft YaHei UI"      # 主字体：中文界面最稳，随系统自带
_MONO_FAMILY = "Cascadia Mono"         # 数值/日志：Win11 自带，回退 Consolas

F_DISPLAY = (_UI_FAMILY, 18, "bold")   # 窗口标题
F_SECTION = (_UI_FAMILY, 15, "bold")   # 卡片标题（原与组头同为 12 bold）
F_GROUP = (_UI_FAMILY, 13, "bold")     # 折叠组头（原与卡片标题同为 12 bold）
F_BODY = (_UI_FAMILY, 13)              # 参数标签 / 按钮 / 输入框 / 日志开关
F_SMALL = (_UI_FAMILY, 12)             # 辅助说明
F_MICRO = (_UI_FAMILY, 11)             # 最小层级（状态附属信息）
F_MONO = (_MONO_FAMILY, 13)            # 数值读数（与 F_BODY 同行高，消除 4px 错位）
F_MONO_SM = (_MONO_FAMILY, 11)         # 日志行（等宽、紧凑）

# 兼容别名：旧代码按 F_TITLE 引用窗口标题
F_TITLE = F_DISPLAY


class _HelpTip:
    """问号按钮 hover 提示（D7 延迟 hover + F2 渐隐动效）：

    悬停 300ms 后淡入（200ms ease-out，窗口 alpha 0→1），移开后 0.8s 指数渐隐
    （α=exp(-k·t/τ)，τ=0.2s，每 16ms 一帧，末段 α 阶梯 0.05/0.02/0 后销毁）；
    渐隐期移回立即恢复 α=1；新提示出现时旧提示立即终止并销毁（全局互斥，
    后悬停者优先）。300ms 延迟是交互防误触，不受动效开关影响；淡入/渐隐
    受动效开关控制（关→瞬时显示/瞬时消失）。所有 after 帧回调在窗口销毁
    竞态下吞 TclError（winfo_exists 检查 + try/except）。
    """

    _TAU = 0.2           # 指数渐隐时间常数（P3：2s→0.8s）：0.8s 末 α=exp(-0.8/0.2)≈0.018
    _FADE_MS = 16        # 淡入/渐隐帧间隔（覆盖 Animator 默认帧间隔）
    _FADE_IN_MS = 200    # 淡入时长
    _FADE_OUT_MS = 800   # 渐隐时长（k=1 时 α 到 0.05 约需 τ·ln20≈600ms，留足阶梯余量）
    _active = None       # 当前唯一活动提示实例（全局互斥）
    _hovering = None     # 最近进入悬停的实例（后悬停者优先）

    def __init__(self, widget, text_fn, motion_on=None, anim=None):
        self.widget = widget
        self.text_fn = text_fn          # 延迟取值，内容始终最新
        self.motion_on = motion_on if motion_on is not None else (lambda: True)
        # 动效引擎：默认用控件 after 自建（保持独立可测）；GUI 传入共享实例
        self.anim = anim if anim is not None else Animator(
            schedule=lambda fn, ms: widget.after(ms, fn), frame_ms=_HelpTip._FADE_MS)
        self.win = None
        self._after_id = None           # 延迟显示计时器 token（300ms 防误触）
        self._anim_id = -1              # 当前淡入/渐隐动画 id（-1 = 无）
        self._alpha = 1.0               # 最近写入的窗口 alpha
        self._stage = 0                 # 末段阶梯：0 自然衰减 / 1 定格 0.05 / 2 定格 0.02
        widget.bind("<Enter>", self._enter)
        widget.bind("<Leave>", self._leave)
        widget.bind("<Button-1>", self._hide)   # 万一点击也立即收起

    def _cancel_frame(self):
        """取消在途淡入/渐隐动画（若有）。控件销毁后取消是纯注册表操作，无 TclError。"""
        if self._anim_id > 0:
            self.anim.cancel(self._anim_id)
            self._anim_id = -1

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
        self._anim_id = self.anim.animate(
            self._fade_out_cb, _HelpTip._FADE_OUT_MS,
            on_done=self._fade_out_done, frame_ms=_HelpTip._FADE_MS)
        if self._anim_id <= 0:  # 瞬时/降级：直接销毁
            self._destroy_win()

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
            # 提示窗宽度由 label wraplength 自适应（P1-1：420→520，长 help 文案换行完整；
            # 520+padx24+边框2 ≈ 546px，1440p 屏无碍）
            ctk.CTkLabel(fr, text=text, font=F_SMALL, text_color=C_TXT,
                         justify="left", anchor="w", wraplength=520,
                         padx=12, pady=8).pack()
            x = self.widget.winfo_rootx() + self.widget.winfo_width() + 6
            y = self.widget.winfo_rooty()
            win.geometry(f"+{x}+{y}")
            self.win = win
            _HelpTip._active = self
            if self.motion_on():
                self._alpha = 0.0
                win.attributes("-alpha", 0.0)
                self._anim_id = self.anim.animate(
                    self._fade_in_cb, _HelpTip._FADE_IN_MS,
                    on_done=self._fade_in_done, frame_ms=_HelpTip._FADE_MS)
                if self._anim_id <= 0:  # 瞬时/降级：直接显示
                    win.attributes("-alpha", 1.0)
                    self._alpha = 1.0
            else:
                win.attributes("-alpha", 1.0)  # 动效关：瞬时显示
                self._alpha = 1.0
        except Exception:  # noqa: BLE001 - 定时器晚到且控件已销毁（UI 重建）时静默放弃
            pass

    def _fade_in_cb(self, p):
        """淡入帧：200ms ease-out，α 0→1（p 为线性进度，ease 在回调内做）。"""
        win = self.win
        if win is None:
            return
        try:
            a = ease_out_cubic(p, 1.0)
            win.attributes("-alpha", max(0.0, a))
            self._alpha = a
        except Exception:  # noqa: BLE001 - 销毁竞态下的 TclError 等吞掉
            pass

    def _fade_in_done(self):
        self._anim_id = -1
        win = self.win
        if win is None:
            return
        try:
            win.attributes("-alpha", 1.0)
            self._alpha = 1.0
        except Exception:  # noqa: BLE001
            pass

    def _fade_out_cb(self, p):
        """渐隐帧：α=exp(-k·t/τ)；k 随光标离问号距离加速（加分 1），
        末段 α 按 0.05/0.02 阶梯定格后销毁（加分 2）。t = p × 渐隐时长。"""
        win = self.win
        if win is None:
            return
        try:
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
            t = p * _HelpTip._FADE_OUT_MS / 1000.0
            a = math.exp(-t * k / _HelpTip._TAU)
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
        except Exception:  # noqa: BLE001 - 销毁竞态下的 TclError 等吞掉
            pass

    def _fade_out_done(self):
        """渐隐时长耗尽仍未触发阶梯销毁：兜底销毁（k≥1 时通常已提前销毁）。"""
        self._anim_id = -1
        if self.win is not None:
            self._destroy_win()

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
        _set_appearance(self.settings["appearance"])
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
        # 表单内容当前对应哪个预设（"" = 不对应任何预设，如刚载入服务参数）。
        # 与下拉显示名区分：显示名只是「下次保存会用的名字」，不能用来判定
        # 「能否覆盖这个预设」——否则启动自动选中就会让应用动作覆盖用户
        # 从未碰过的预设。
        self._preset_loaded = ""
        self.var = {}
        self.widgets = {}
        self.val_labels = {}
        self._stop_poll = False
        self._restarting = False     # 重启进行中防重入（do_restart 入口必读，必须显式初始化）
        self._log_q = queue.Queue()
        # 动效引擎：注入 Tk after 作调度器（motion.py 纯数值模块）；
        # 必须在 _build_widgets 之前创建，D4 起的 hover 绑定会用到。
        # frame_ms=66：长驻动效（呼吸循环）降到约 15fps，重绘压力再减半；
        # 100ms 的 hover 过渡此时约 1-2 帧仍可接受（ease-out 末段占大头），
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
        # D8 折叠分组：展开状态（_restart_ui 重建后保留，默认展开前两组）
        self.group_open = {}
        self._log_off = 0  # _poll_log 增量渲染：上次读到的文件偏移
        # 探活 worker（拖拽卡顿修复）：所有同步阻塞的 nssm/sc/urlopen 移出
        # 主线程。请求走 _status_q（主→worker），结果走 _status_r（worker→主）；
        # 两条队列分离，避免 worker 把自己的 result 当请求消费。
        self._status_q = queue.Queue()
        self._status_r = queue.Queue()
        self._status_worker = threading.Thread(target=self._status_worker_loop,
                                               daemon=True)
        # dirty 主线程缓存（worker 线程不能读 Tk 变量）；
        # 表单编辑/载入/写回时置 None 失效，由 worker 重算
        self._dirty_cache = None
        # ---- 官方更新状态（B 方案：ggml-org/llama.cpp）----
        self._upd_release = None      # 最近一次检查到的最新 release 信息
        self._upd_installing = False  # 官方更新安装进行中（关窗守护）
        self._close_after_restart = False  # 用户确认退出后，等重启收尾再关窗
        self._upd_checking = False    # 防重入
        self._upd_build_pending = False  # 本地 build 号后台查询进行中（避免重复 spawn）
        self._upd_worker = None       # 后台检查线程
        self._upd_modal_open = False  # 更新日志弹窗互斥（startup 提示与手动检查）
        self._upd_startup_after = None
        self._prune_startup_after = None  # 启动清理的 after token

        self._build_widgets()
        self.refresh_all()
        self._start_polling()
        # 启动后 1.2s 后台检查官方更新（仅提示，绝不自动安装）
        if self.settings.get("upd_check_on_startup", True):
            self._upd_startup_after = self.after(1200, self._check_updates_startup)
        # 启动后 2.5s 后台清理更新缓存/备份的陈旧目录（各保留最近 N 个）
        self._prune_startup_after = self.after(2500, self._prune_update_dirs)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # 缩放/拖拽防抖：WM_CONFIGURE 高频触发期间挂起 UI 应用与日志渲染，
        # 停止 300ms 后恢复（缩放卡顿修复）。
        self._resizing = False
        self._resize_after = None
        self._last_geometry_snapshot = ""  # 窗口几何快照：区分真实缩放与内部布局重排
        self._layout_mutating = False      # 日志展开/折叠等布局突变期间禁滚动条切换
        # P3 呼吸静止优先：最近交互时刻（<Motion>/<Key> 刷新）；超 30s 无交互
        # 呼吸圆点停帧（停在当前色），用户一动即恢复。
        self._last_interaction = time.monotonic()
        self.bind("<Configure>", self._on_configure)
        self.bind_all("<Motion>", self._note_interaction)
        self.bind_all("<Key>", self._note_interaction)

    # ---- 通用小组件 ----
    def _btn(self, parent, text, cmd, kind="ghost"):
        """kind: primary / ghost / danger-text。

        hover 动效（D4 + 指数渐隐）：native hover_color 固定为底色，颜色过渡完全由
        <Enter>/<Leave> 驱动——进入 100ms ease-out 插到高亮并驻留（不回落）；
        移出 0.8s 指数渐隐（α=exp(-t/τ), τ=0.27s, 每 16ms 一帧, α≤0.05 末帧定格
        80ms 后直跳终态）；渐隐期移回中断渐隐、从当前色续插回高亮。动效关时
        瞬时切换（原生 hover 行为）。禁用态（t5 联动置灰）跳过动效。
        """
        kw = dict(font=F_BODY, corner_radius=8, height=32)
        if kind == "primary":
            base, hover = C_ACC, C_ACCH
        elif kind == "danger":
            base, hover = C_RED, format_hex(lerp(C_RED, C_CARD, 0.85))
        else:
            base, hover = C_TXT, C_BG
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
        # P2 按钮宽度自适应 + 最小宽度（英文溢出修复）：用按钮实际渲染字体
        # （_text_label 已含 DPI/缩放处理）测文本像素宽，替代 CTkButton 默认
        # 固定 140；每侧 14px 内边距 + 2px 边框余量，下限 88 防短词局促。
        # 语言切换经 _restart_ui 重建按钮，宽度随文案自适应。
        try:
            _f = tkfont.Font(font=btn._text_label.cget("font"))
            _tw = _f.measure(text)
        except Exception:  # noqa: BLE001 - 极端环境回退最小宽
            _tw = 0
        btn.configure(width=max(88, _tw + 2 * 14 + 2))

        # hover 动效状态（闭包）：
        #   aid  当前动画 id（进入 tween / 渐隐 / 定格段共用一个槽；-1 = 无）
        hstate = {"aid": -1, "cur": None}
        _FADE_TAU = 0.27   # 指数渐隐时间常数（P3：2s→0.8s）：0.8s 末 α=exp(-0.8/0.27)≈0.052
        _FADE_STOP = 0.05  # α 降到该值 → 定格 _FADE_HOLD 毫秒后直跳终态
        _FADE_HOLD = 80    # 末帧定格时长（ms，生动加分 2）
        _FADE_FRAME = 16   # 渐隐帧间隔（ms，覆盖 Animator 默认）
        # 指数衰减时长：α 从 1 降到 _FADE_STOP 所需时间 t = τ·ln(1/STOP)
        _FADE_DUR = int(round(-_FADE_TAU * 1000.0 * math.log(_FADE_STOP)))

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

        def _cancel_aid():
            """取消本按钮在途动画（进入 tween / 渐隐 / 定格段，若有）。"""
            if hstate["aid"] > 0:
                self.anim.cancel(hstate["aid"])
            hstate["aid"] = -1

        def _fade_enter(hover_col):
            """进入 / 渐隐期移回：取消在途渐隐，从当前色续插回高亮（100ms ease-out）。"""
            _cancel_aid()
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
                try:
                    if btn.cget("state") == "disabled":
                        return  # 中途被置灰（如 t5 轮询）：停止写色，保住禁用外观
                    col = format_hex(lerp(start, hover_col, ease_out_cubic(p, 1)))
                    hstate["cur"] = col
                    btn.configure(fg_color=col)
                except Exception:  # noqa: BLE001 - 销毁竞态吞掉
                    pass

            def _done():
                hstate["aid"] = -1
                try:
                    if btn.cget("state") == "disabled":
                        return
                except Exception:  # noqa: BLE001
                    return
                hstate["cur"] = hover_col

            hstate["aid"] = self.anim.animate(_tick, 100, on_done=_done,
                                              frame_ms=_FADE_FRAME)
            if hstate["aid"] <= 0:  # 瞬时/降级：on_done 已同步执行
                hstate["aid"] = -1

        def _fade_leave(final_col, back_to_transparent=False):
            """移出：指数渐隐 高亮→终态（Animator 驱动，帧间隔 16ms）。

            每帧 α = exp(-t/τ)（t = p·_FADE_DUR），颜色 = lerp(终态, 高亮, α)。
            终态色先按亮度压 2%（生动加分 1：消退更真实），α≤0.05 时定格
            _FADE_HOLD 毫秒再直跳终态。
            """
            _cancel_aid()
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

            # 终态色亮度轻压 2%（浅色向黑、深色向白偏移）
            if final_col == "transparent":
                base_col = _resolve_base()
            else:
                base_col = final_col
            rgb = parse_hex(base_col)
            lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
            anchor = (0, 0, 0) if lum > 128 else (255, 255, 255)
            target = format_hex(lerp(base_col, anchor, 0.02))

            def _finish():
                hstate["aid"] = -1
                try:
                    if btn.cget("state") == "disabled":
                        hstate["cur"] = None
                        return
                    if back_to_transparent:
                        btn.configure(fg_color="transparent")
                        hstate["cur"] = _resolve_base()
                    else:
                        btn.configure(fg_color=final_col)
                        hstate["cur"] = final_col
                except Exception:  # noqa: BLE001 - 销毁竞态吞掉
                    pass

            def _tick(p):
                try:
                    if btn.cget("state") == "disabled":
                        return  # 中途被置灰：停在当前色，保住禁用外观
                    a = math.exp(-(p * _FADE_DUR / 1000.0) / _FADE_TAU)
                    col = format_hex(lerp(target, peak, a))
                    hstate["cur"] = col
                    btn.configure(fg_color=col)
                except Exception:  # noqa: BLE001 - 销毁竞态吞掉
                    pass

            def _hold_start():
                # 末帧定格 _FADE_HOLD 再直跳终态（生动加分 2）
                froze = format_hex(lerp(target, peak, _FADE_STOP))

                def _hold(_p):
                    try:
                        if btn.cget("state") == "disabled":
                            return
                        btn.configure(fg_color=froze)
                    except Exception:  # noqa: BLE001
                        pass

                hstate["aid"] = self.anim.animate(_hold, _FADE_HOLD, on_done=_finish,
                                                  frame_ms=_FADE_FRAME)
                if hstate["aid"] <= 0:  # 瞬时/降级：直接收尾
                    _finish()

            hstate["aid"] = self.anim.animate(_tick, _FADE_DUR, on_done=_hold_start,
                                              frame_ms=_FADE_FRAME)
            if hstate["aid"] <= 0:  # 瞬时/降级：直接收尾
                _finish()

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
            ctk.CTkLabel(inner, text=title, font=F_SECTION, text_color=C_MUT,
                         anchor="w").pack(fill="x", pady=(0, 8))
        # 卡片边框保持 C_BORDER 恒定：已移除 hover 亮边动效（鼠标靠近卡片边缘时
        # <Enter>/<Leave> 高频切换造成边框闪烁），视觉安静无闪烁。
        return inner

    # ---- 布局 ----
    def _first_paint_services(self):
        """首帧下拉值：用上次枚举结果（settings["services"]），无则只放当前服务。

        #3 启动骨架：绝不在首帧同步调用 list_nssm_services()（PowerShell
        _status_worker，结果回灌后刷新下拉（见 _drain_status）。
        """
        cached = [s for s in self.settings.get("services", []) if isinstance(s, str)]
        if self.service in cached:
            return cached
        return [self.service] + cached

    def _build_widgets(self):
        # 头部：标题 + 服务选择
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(14, 2))
        ctk.CTkLabel(head, text=t("app.title"), font=F_TITLE,
                     text_color=C_TXT).pack(side="left")  # P2：标题随语言切换（原硬编码中文，复用 app.title 键）
        svc = ctk.CTkFrame(head, fg_color="transparent")
        svc.pack(side="right")
        ctk.CTkLabel(svc, text=t("svc.label"), font=F_BODY, text_color=C_MUT).pack(side="left", padx=(0, 6))
        self.service_var = tk.StringVar(value=self.service)
        self.cmb_service = ctk.CTkOptionMenu(svc, variable=self.service_var,
                                             values=self._first_paint_services(),
                                             width=220, font=F_BODY,
                                             fg_color=C_CARD, button_color=C_BORDER,
                                             button_hover_color=C_ACC,
                                             text_color=C_TXT,
                                             command=lambda v: self.on_service_change())
        self.cmb_service.pack(side="left")

        # 状态条（单行：状态 + 探活 + 自启 + 控制按钮）
        st = self._card(self)
        row = ctk.CTkFrame(st, fg_color="transparent")
        row.pack(fill="x")
        # 状态点：用图标资产而非字体字符 U+25CF。
        # 旧实现是 text="\u25CF" —— 尺寸由 Microsoft YaHei UI 的字形决定（13px 字号下
        # 实测墨迹 13x23px），与图标网格无关，也不随主题走图标缓存。现改为
        # dot-* glyph + tinted() 运行时着色：形状由 24 单位网格决定，呼吸/闪烁仍按
        # 原逻辑换色（tinted 按量化色缓存，动效帧复用率极高）。
        self.dot_state = ctk.CTkLabel(row, text="", width=16,
                                      image=ic.tinted("dot-run", 14, C_STOP))
        self.dot_state.pack(side="left")
        self.lbl_state = ctk.CTkLabel(row, text=t("state.unknown"), font=F_BODY, text_color=C_MUT)
        self.lbl_state.pack(side="left")
        # P1-3：状态卡完整服务名（长 NSSM 服务名在下拉里仍可能被截，此处全文可见）
        self.lbl_svc = ctk.CTkLabel(row, text=self.service, font=F_SMALL, text_color=C_MUT)
        self.lbl_svc.pack(side="left", padx=(10, 0))
        self.lbl_health = ctk.CTkLabel(row, text=t("health.idle"), font=F_BODY, text_color=C_MUT)
        self.lbl_health.pack(side="left", padx=(12, 0))
        # 自启下拉即状态（菜单值 Auto (boot)/Manual/Disabled 自解释，不再配前缀标签，
        # 为英文界面单行留足宽度）
        self.auto_var = tk.StringVar(value=t("boot.manual"))
        self.opt_auto = ctk.CTkOptionMenu(row, variable=self.auto_var,
                                          values=[t("boot.auto"), t("boot.manual"), t("boot.disabled")],
                                          width=110, height=30, font=F_BODY,
                                          fg_color=C_FIELD, button_color=C_BORDER,
                                          button_hover_color=C_ACC, text_color=C_TXT,
                                          command=lambda v: self.apply_auto())
        self.opt_auto.pack(side="left", padx=(12, 0))
        act = ctk.CTkFrame(row, fg_color="transparent")
        act.pack(side="right")
        self.btn_start = self._btn(act, t("btn.start"), lambda: self.do_action("start"))
        self.btn_start.pack(side="left", padx=2)
        self.btn_stop = self._btn(act, t("btn.stop"), lambda: self.do_action("stop"), kind="danger")
        self.btn_stop.pack(side="left", padx=2)
        self._btn(act, t("btn.restart"), self.do_restart).pack(side="left", padx=2)
        self._btn(act, t("btn.settings"), self.open_settings).pack(side="left", padx=(6, 2))

        # 预设区（单行：标题 + 可编辑下拉 + 删除图标；右侧 应用更改/还原）
        pr = self._card(self)
        prow = ctk.CTkFrame(pr, fg_color="transparent")
        prow.pack(fill="x")
        ctk.CTkLabel(prow, text=t("card.presets"), font=F_SECTION, text_color=C_MUT).pack(side="left")
        self.lbl_dirty = ctk.CTkLabel(prow, text="", font=F_SMALL, text_color=C_ORG)
        self.lbl_dirty.pack(side="left", padx=12)
        self.btn_revert = self._btn(prow, t("btn.revert"), self.load_params)
        self.btn_revert.pack(side="right")
        self.btn_apply = self._btn(prow, t("btn.apply2"), self.apply_changes, kind="primary")
        self.btn_apply.pack(side="right", padx=(0, 8))
        ic_del = ic.glyph("trash", 18)   # 统一图标体系(assets/icons/glyph_trash.png)
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
        ctk.CTkLabel(phead, text=t("card.params"), font=F_SECTION, text_color=C_MUT,
                     anchor="w").pack(side="left")
        self.scroll = ctk.CTkScrollableFrame(pc, fg_color="transparent",
                                             scrollbar_button_color=C_GRAY,
                                             scrollbar_button_hover_color=C_MUT)
        self.scroll.pack(fill="both", expand=True)
        # D8 折叠分组：每个 group 一个可折叠区（头按钮 + 独立 grid 容器，行号各从 0 计）
        # D8 折叠分组：每个 group 一个可折叠区（头按钮 + 独立 grid 容器，行号各从 0 计）
        self._group_containers = {}  # group -> 内容 CTkFrame
        self._group_headers = {}     # group -> 头部按钮
        groups = []
        for fld in FIELDS:
            g = fld.get("group")
            if g not in groups:
                groups.append(g)
        self.group_open = self.group_open or {}  # 历史空字典（升级路径）
        # P1-4：默认展开前两组（模型与视觉 + 加速）；已存在的展开状态
        # （跨 _restart_ui 用户手动开合）原样保留
        for i, g in enumerate(groups):
            self.group_open.setdefault(g, i < 2)
            head = ctk.CTkButton(
                self.scroll, text=self._group_label(g), font=F_GROUP,
                image=ic.chevron(self.group_open[g]),
                text_color=C_ACC if self.group_open[g] else C_MUT,
                fg_color="transparent", hover_color=C_BG,
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
                                     anchor="w", justify="left")  # wraplength 由 _sync_wraplengths 动态设置
        self.lbl_hint.pack(fill="x", pady=(8, 0))

        # 日志（可折叠，默认收起，把空间留给启动参数）
        self._log_open = tk.BooleanVar(value=False)
        lg = ctk.CTkFrame(self, fg_color=C_CARD, corner_radius=14)
        lg.pack(fill="x", padx=12, pady=(6, 0))
        head = ctk.CTkFrame(lg, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(10, 4))
        self.btn_log_toggle = ctk.CTkButton(
            head, text=t("log.collapsed"), font=F_BODY,
            text_color=C_MUT, anchor="w", fg_color="transparent",
            hover_color=C_BG, command=self.toggle_log)
        self.btn_log_toggle.pack(side="left")
        self.txt_log = ctk.CTkTextbox(lg, height=40, font=F_MONO_SM,
                                      fg_color=C_FIELD, border_width=1,
                                      border_color=C_BORDER, text_color=C_TXT,
                                      wrap="none")
        self.txt_log.configure(state="disabled")
        # 新行渐隐高亮 tag（D5）：插入后 ≤200ms 移除背景
        self.txt_log._textbox.tag_configure(
            "flash", background=format_hex(lerp(C_FIELD, C_ORG, 0.30)))
        # 默认不打包日志区，仅头部行
        # 警告行（解析告警）挂在日志折叠条下方
        self.lbl_warn = ctk.CTkLabel(self, text="", font=F_SMALL, text_color=C_ORG,
                                     anchor="w", justify="left")  # wraplength 由 _sync_wraplengths 动态设置
        self.lbl_warn.pack(fill="x", padx=16, pady=(2, 8))
    def _group_label(self, group):
        """组头文案:本地化组名(展开指示改用统一 chevron 图标,见 _toggle_group)。"""
        label = GROUP_NAMES.get(group, group) if strings._current == "en" else group
        return label

    def _toggle_group(self, group):
        """点击组头切换展开/收起（D8）。瞬时切换优先正确性；状态写入
        self.group_open 供 _restart_ui 重建后恢复。"""
        self.group_open[group] = not self.group_open.get(group, False)
        head = self._group_headers[group]
        body = self._group_containers[group]
        head.configure(text=self._group_label(group),
                       image=ic.chevron(self.group_open[group]),
                       text_color=C_ACC if self.group_open[group] else C_MUT)
        if self.group_open[group]:
            body.grid()
        else:
            body.grid_remove()

    def _field_label(self, fld):
        """字段 label 本地化（英文界面取 label_en，缺省回退中文 label）。"""
        if strings._current == "en":
            return fld.get("label_en") or fld["label"]
        return fld["label"]

    def _build_field(self, parent, fld, row):
        key = fld["key"]
        _q = ic.glyph("question", 14)
        btn = ctk.CTkButton(parent, text="" if _q else "?", width=26, height=26,
                            corner_radius=13, font=F_SMALL, fg_color="transparent",
                            border_width=1, border_color=C_BORDER, hover_color=C_BG,
                            text_color=C_MUT, image=_q, cursor="question_arrow")
        btn.grid(row=row, column=0, padx=(0, 8), pady=4)
        _HelpTip(btn, lambda k=key: self._help_text(k), motion_on=self._motion_on,
                     anim=self.anim)

        v = tk.StringVar()
        self.var[key] = v
        self._hook_trace(key, v)

        if fld["kind"] == "slider":
            iv = tk.DoubleVar()
            self.var[key] = iv
            self._hook_trace(key, iv)
            ctk.CTkLabel(parent, text=self._field_label(fld), font=F_BODY, text_color=C_TXT,
                         anchor="w").grid(row=row, column=1, sticky="w", padx=2)
            n_steps = max(int(round((fld["max"] - fld["min"]) / fld["step"])), 1)
            w = ctk.CTkSlider(parent, variable=iv, from_=fld["min"], to=fld["max"],
                              number_of_steps=n_steps, width=300,
                              button_color=C_ACC, button_hover_color=C_ACCH,
                              progress_color=C_ACC,
                              command=lambda val, k=key: self._on_slide(k, val))
            w.grid(row=row, column=2, sticky="w", padx=4, pady=6)
            self.widgets[key] = w
            lbl = ctk.CTkLabel(parent, text="", font=F_MONO, text_color=C_MUT,
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
            ctk.CTkLabel(parent, text=self._field_label(fld), font=F_BODY, text_color=C_TXT,
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
            w = ctk.CTkCheckBox(parent, text=self._field_label(fld), variable=v,
                                onvalue="1", offvalue="", font=F_BODY,
                                text_color=C_TXT, fg_color=C_ACC,
                                hover_color=C_ACCH, border_color=C_BORDER,
                                corner_radius=6)
            w.grid(row=row, column=1, columnspan=2, sticky="w", padx=2, pady=6)
            self.widgets[key] = w
            return row + 1

        if fld["kind"] == "path":
            ctk.CTkLabel(parent, text=self._field_label(fld), font=F_BODY, text_color=C_TXT,
                         anchor="w").grid(row=row, column=1, sticky="w", padx=2)
            # P1-2：Entry 保留 width=430（CTkEntry 透传 xview/xview_scroll，原生
            # ←→ 键滚动可用）；超长路径完整内容由「浏览」按钮 hover 提示展示。
            w = ctk.CTkEntry(parent, textvariable=v, width=430, font=F_BODY,
                             fg_color=C_FIELD, border_color=C_BORDER)
            w.grid(row=row, column=2, sticky="ew", padx=4, pady=6)
            btn_browse = self._btn(parent, t("browse"), lambda k=key: self._browse(k))
            btn_browse.grid(row=row, column=3, sticky="w", padx=4)
            _HelpTip(btn_browse, lambda k=key: self.var[k].get() or "",
                     motion_on=self._motion_on,
                     anim=self.anim)  # 路径超长时 hover 浏览按钮看全文
            self.widgets[key] = w
            return row + 1

        # text
        ctk.CTkLabel(parent, text=self._field_label(fld), font=F_BODY, text_color=C_TXT,
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

    def _unit(self, fld):
        """滑块数值单位本地化（英文界面取 unit_en，缺省回退中文单位）。"""
        if strings._current == "en":
            return fld.get("unit_en") or fld.get("unit", "")
        return fld.get("unit", "")

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
        self.val_labels[key].configure(text=f"{val:g} {self._unit(fld)}".strip())
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
        unit = self._unit(fld)
        self.val_labels[key].configure(text=f"{num:g} {unit}".strip())

    def _update_combo_hint(self, key):
        fld = next(f for f in FIELDS if f["key"] == key)
        shown = self.var[key].get()
        real = self._combo_map.get(key, {}).get(shown, shown)
        hint = fld.get("option_help", {}).get(real, "")
        label = fld.get("label_" + strings._current) or fld["label"]
        self.lbl_hint.configure(text=f"[{label}] {hint}" if hint else "")
        if real != shown:
            self._suppress_trace = True  # 显示名归一化（（空）→""）不触发高亮
            try:
                self.var[key].set(real)
            finally:
                self._suppress_trace = False

    def _help_text(self, key):
        fld = next(f for f in FIELDS if f["key"] == key)
        en = strings._current == "en"
        body = fld.get("help_" + strings._current) or fld.get("help", "（无说明）")
        if fld.get("option_help"):
            body += ("\n\nOptions:\n" if en else "\n\n选项说明：\n") + "\n".join(
                f"  - {k or '（空）'}: {v}" for k, v in fld["option_help"].items())
        if fld["kind"] == "slider":
            if en:
                body += f"\n\nRange: {fld['min']} to {fld['max']} (step {fld['step']}), default {fld.get('default')}"
            else:
                body += f"\n\n范围：{fld['min']} ~ {fld['max']}（步长 {fld['step']}），默认 {fld.get('default')}"
        return body

    def _browse(self, key):
        p = filedialog.askopenfilename(title=t("file.pick"), initialdir=r"F:\AI_Model")
        if p:
            self.var[key].set(p)

    # ---- 状态刷新 ----
    def on_service_change(self):
        """切换服务：若有未应用更改，先确认（可自动备份为预设）。

        确认框问的是「是否切换」：答**否**必须整体中止切换并把下拉显示回滚到
        当前服务，否则 refresh_all() 会用新服务的参数覆盖表单——用户的编辑
        静默消失，而这正是本项目其它路径（切语言/外观）已经修过的同一类缺陷。
        """
        new_name = self.service_var.get()
        if new_name != self.service and self._dirty():
            if not messagebox.askyesno(t("mb.confirm"), fmt("msg.svc.dirty", n=new_name)):
                try:
                    self.service_var.set(self.service)   # 回滚下拉显示
                except Exception:  # noqa: BLE001 - 控件销毁竞态
                    pass
                return
            values, _ = self._collect()
            presets = load_presets()
            presets[fmt("preset.autobackup", t=time.strftime('%m-%d %H:%M:%S'))] = values
            self._save_presets(presets)
            self.refresh_presets()
        self.service = new_name
        # 换了服务：表单即将被新服务参数覆盖，不再对应任何预设
        self._preset_loaded = ""
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

    # ---- 状态圆点（图标资产，形状随状态变化） ----
    _DOT_SIZE = 14

    def _set_dot(self, name, color):
        """按状态换「形状 + 颜色」的圆点。

        v2 起圆点是图标资产而非字体字符：形状本身携带语义
        （运行=实心核+光环 / 停止=方核 / 错误=感叹号 / 未应用=斜线环），
        颜色只作二次强化。tinted() 按量化色缓存，动效逐帧换色不会失控。
        """
        img = ic.tinted(name, self._DOT_SIZE, color)
        if img is not None:
            self.dot_state.configure(image=img)

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

        P3 静止优先（苹果式克制）：超 _BREATH_IDLE_S 秒无交互（_note_interaction
        刷新）则帧跳过、圆点停在当前色，呼吸循环仍在跑——用户一动鼠标即自然
        恢复脉动，无需状态机切换。
        """
        def _frame(p):
            if getattr(self, "_resizing", False):
                return  # 缩放期间跳过帧（颜色停在当前值，缩放结束续跑）
            if (time.monotonic() - getattr(self, "_last_interaction", 0.0)
                    > _BREATH_IDLE_S):
                return  # 静止优先：30s 无交互停帧（圆点停在当前色，动鼠标即恢复）
            amp = 0.12 * (0.5 - 0.5 * math.cos(2 * math.pi * p))
            self._set_dot("dot-run", format_hex(lerp(C_RUN, _breath_peak, amp)))

        _BREATH_IDLE_S = 30  # P3：30s 无交互呼吸停帧（帧内判定，循环不终止）
        if not self._breathing or self._breath_busy:
            return
        _breath_peak = "#ffffff" if _appearance == "light" else "#000000"
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
            self._set_dot("dot-error", C_RED)
            return

        def _frame(p):
            t = ease_out_cubic(p, 1)  # 索引式缓动：i=p, steps=1 → 连续化
            red = math.sin(t * 4 * math.pi) > 0  # 2 轮完整交替：红/原/红/原（2×300ms）
            self._set_dot("dot-error" if red else "dot-run", C_RED if red else C_RUN)

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
            self._set_dot("dot-run", C_RUN)  # 安全回退：闪烁只在 RUNNING 时触发

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
            if state == "STOPPED":
                self._set_dot("dot-stop", C_STOP)
            else:
                # 过渡态（STARTING/STOPPING/未知）：未应用更改的斜线环复用为「中间态」
                self._set_dot("dot-dirty", C_ORG)

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
                    self.val_labels[key].configure(text=f"{num:g} {self._unit(fld)}".strip())
                else:
                    self.var[key].set(val)
        finally:
            self._suppress_trace = False
        if warnings is not None:
            self.lbl_warn.configure(text=" | ".join(warnings) if warnings else "")

    def load_params(self):
        """用服务当前参数覆盖表单。

        表单内容此后来自**服务**而非任何预设，故清掉 _preset_loaded：否则
        下拉若刚好显示同名预设，「应用更改」会把服务参数写进那个预设。
        调用方若确实想让表单对应某预设（如 refresh_all 恢复 last_preset），
        必须在这之后显式重新 load_preset()。
        """
        text = get_app_parameters(self.service)
        values, extras, warnings = parse_params(text, FIELDS)
        self.extras = extras
        self._preset_loaded = ""
        self._apply_values(values, warnings)
        self._dirty_cache = None  # 载入后表单=服务，dirty 缓存失效待重算
    # ---- 偏好落盘（统一处理失败，避免静默）----
    def _persist(self, ok, err, what):
        """配置写入失败的统一处理：每个会话只提示一次，绝不抛进 Tk 事件循环。

        save_settings / save_presets 已约定返回 (ok, err) 而不抛异常（打包是
        console=False，抛出去用户什么都看不到，只表现为「设置看着生效、
        下次启动又变回去」）。这里把失败如实告知一次。
        """
        if ok:
            return True
        if not getattr(self, "_persist_warned", False):
            self._persist_warned = True
            try:
                messagebox.showwarning(
                    t("mb.hint"), fmt("msg.persist.fail", w=what, e=err), parent=self)
            except Exception:  # noqa: BLE001 - 窗口销毁竞态
                pass
        return False

    def _save_settings(self):
        return self._persist(*save_settings(self.settings), what=t("settings.title"))

    def _save_presets(self, presets):
        return self._persist(*save_presets(presets), what=t("card.presets"))

    # ---- 预设 ----
    def refresh_presets(self):
        """刷新下拉候选；**不**把「显示名」当成「已载入的预设」。

        显示名只是「下次写回/另存会用的名字」。真正决定能否覆盖某个预设的是
        self._preset_loaded（表单内容确实来自哪个预设）。二者混为一谈时，
        启动自动选中 names[0] 会让表单（其实是服务参数）在点一次「应用更改」
        后覆盖用户从未碰过的那个预设。
        """
        names = list(load_presets().keys())
        self.cmb_preset.configure(values=names)
        if self._preset_loaded and self._preset_loaded not in names:
            self._preset_loaded = ""      # 该预设已被删除/改名，表单不再对应它
        if self._preset_loaded:
            self.preset_var.set(self._preset_loaded)
        elif names and self.preset_var.get() not in names:
            self.preset_var.set(names[0])

    def _sync_preset_with_form(self):
        """应用成功后同步预设：仅当表单内容**确实来自**同名预设时才覆盖它。

        防漂移（用户改路径/参数后只点应用、忘记另存预设 → 旧预设残留旧
        路径，下次载入会把服务指回坏文件）。但若表单不是从该预设载入的
        （启动自动选中、刚切过服务、预设刚被删），覆盖就是静默破坏用户数据，
        此时不做任何写入。新名字由 _on_preset_committed 负责保存。
        """
        name = self.preset_var.get().strip()
        if not name or name != self._preset_loaded:
            return
        if name not in load_presets():
            return
        values, _ = self._collect()
        presets = load_presets()
        presets[name] = values
        self._save_presets(presets)

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
        self._preset_loaded = name        # 表单内容现在确实来自该预设
        self._flash_preset_highlight()

    def on_preset_selected(self, name):
        """下拉选择：若表单有未应用更改，先把当前表单自动存为新预设，再载入所选。"""
        if self._dirty():
            cur = self.preset_var.get().strip()
            cur_name = cur if (cur and cur != name) else fmt("preset.autobackup", t=time.strftime('%m-%d %H:%M:%S'))
            values, _ = self._collect()
            presets = load_presets()
            presets[cur_name] = values
            self._save_presets(presets)
        self.load_preset(name)

    def _on_preset_committed(self):
        """回车或失去焦点：框内是新名字→把当前参数另存为该预设；是已有名→不动作。"""
        name = self.preset_var.get().strip()
        if not name:
            return
        if name in load_presets():
            self._preset_loaded = name    # 已有名：表单仍对应该预设
            return  # 刚由下拉 command 载入，避免误覆盖
        values, _ = self._collect()
        presets = load_presets()
        presets[name] = values
        self._save_presets(presets)
        self._preset_loaded = name        # 另存后表单即对应该新预设
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
        self._save_presets(presets)
        if self._preset_loaded == name:
            # 表单里的值来自这个已删预设：此后不得再把它写回任何同名预设，
            # 也不该让下拉的自动选中把它算成「当前对应的预设」。
            self._preset_loaded = ""
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
        """表单参数与当前服务是否存在**语义**差异。

        用 semantically_equal 而非文本比较：本工具写回时统一长名、按 FIELDS
        顺序重排、补全滑块默认值、给含引号的值加转义，文本比较会把「等价但
        写法不同」的历史/手写参数误判为改动，一打开就常亮「未应用更改」。
        """
        values, extras = self._collect()
        return not semantically_equal(build_params(values, extras, FIELDS),
                                      get_app_parameters(self.service), FIELDS)

    def apply_changes(self):
        """写回表单参数；服务运行中则确认后自动重启，未运行仅写回。

        注意此处**故意**用文本比较（而非 _dirty 的 semantically_equal）：
        写回是「把服务文本规范化」的动作，只要目标文本与现状不同就值得写——
        例如服务里是历史遗留的 `-c 4096 --ctx-size 131072`，语义虽等价，
        但写回正是修掉该冲突、统一为单一 `--ctx-size` 的时机。
        若这里改成语义比较，用户将永远无法通过本工具规范化旧参数。
        「是否有未应用更改」的提示判定用 _dirty（语义），与写回动作分离。
        """
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
        # 写回成功后，当前下拉若对应已存在预设，同步覆盖该预设，防止表单改动
        # 只写回服务而预设仍留旧路径（下次载入会把服务指回坏文件）。
        #
        # 预设写入是**可选的簿记**动作：它失败绝不能让随后的重启被跳过，
        # 否则参数已落盘、界面已弹过确认，服务却仍在跑旧参数（真实故障形态：
        # presets.json 被 OneDrive/杀软短暂占用）。失败只提示，务必继续往下走。
        try:
            self._sync_preset_with_form()
        except Exception as exc:  # noqa: BLE001
            messagebox.showwarning(t("mb.hint"), fmt("msg.preset.save.fail", e=exc))
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
        try:
            # 停止前健康检查（只提示，不阻断——重启本身就是修复手段）
            if not check_health(host, port)[0]:
                self._log_q.put(t("log.restart.unhealthy"))
            # 已停止的服务不必先停：Windows 的 `sc stop` 对未启动的服务返回
            # 1062（The service has not been started，本机实测退出码 1062）。
            # 旧实现把它当失败直接 return，于是服务停着时点「重启」永远只打印
            # 一行「停止失败」，够不到下面的启动——而那正是用户最需要它的时候。
            if sc_query_state(service) == "STOPPED":
                self._log_q.put(fmt("log.restart.stop", s=service) + t("log.restart.alreadystopped"))
            else:
                self._log_q.put(fmt("log.restart.stop", s=service))
                ok, msg = sc_action("stop", service)
                if not ok and sc_query_state(service) != "STOPPED":
                    self._log_q.put(fmt("log.restart.stopfail", m=msg))
                    return
                stopped = False
                for _ in range(40):
                    if sc_query_state(service) == "STOPPED":
                        stopped = True
                        break
                    time.sleep(0.5)
                if not stopped:
                    self._log_q.put(t("log.restart.stoptimeout"))
                    return
            self._log_q.put("__REFRESH_STATUS__")
            self._log_q.put(t("log.restart.start"))
            ok, msg = sc_action("start", service)
            if not ok:
                # 启动命令本身失败也不再空等 60 秒：直接报错收尾
                self._log_q.put(fmt("log.restart.startfail", m=msg))
                self._log_q.put("__REFRESH_STATUS__")
                return
            for _ in range(120):
                if sc_query_state(service) == "RUNNING":
                    ok, d = check_health(host, port)
                    if ok:
                        self._log_q.put(fmt("log.restart.ready", d=d))
                        break
                time.sleep(0.5)
            self._log_q.put("__REFRESH_STATUS__")
        finally:
            # 无论成败都发收尾哨兵：_drain_log 复位 _restarting，
            # 等待中的 _on_close 也能据此自动销毁窗口
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
        self._layout_mutating = True  # 展开/折叠期间 Configure 不做滚动条切换
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
                self._layout_mutating = False
                return
            self.txt_log.configure(height=40)

            def _open_frame(p):
                t = ease_out_cubic(p, 1)
                self.txt_log.configure(height=int(40 + (170 - 40) * t))

            def _open_done():
                self._log_anim_id = -1
                self._layout_mutating = False
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
                self._layout_mutating = False
                return

            def _close_frame(p):
                t = ease_in_cubic(p, 1)
                self.txt_log.configure(height=int(170 - (170 - 40) * t))

            def _close_done():
                self._log_anim_id = -1
                self._layout_mutating = False
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
        # 等待重启收尾（_on_close 已确认退出）期间必须继续消费队列，
        # __RESTART_DONE__ 到达后由消费分支销毁窗口；正常退出才停链。
        if self._stop_poll and not getattr(self, "_close_after_restart", False):
            return
        while True:
            try:
                text = self._log_q.get_nowait()
            except queue.Empty:
                break
            if text == "__RESTART_DONE__":
                self._restarting = False
                if getattr(self, "_close_after_restart", False):
                    try:
                        self.destroy()
                    except Exception:  # noqa: BLE001 - 已销毁则忽略
                        pass
                    return  # 窗口已销毁，不再碰控件/续调 after
            elif text == "__UPD_DONE__":
                # 安装线程收尾哨兵：复位 _upd_installing，让关窗守护放行
                self._upd_installing = False
            elif text == "__REFRESH_STATUS__":
                self.refresh_status()
            elif isinstance(text, tuple) and text and text[0] == "__UPD_CHECK_DONE__":
                self._check_updates_done(text[1], text[2], text[3], text[4],
                                         text[5] if len(text) > 5 else None)
            elif isinstance(text, tuple) and text and text[0] == "__UPD_BUILD__":
                self._upd_build_pending = False
                self._refresh_upd_status_label(("build", text[1]))
            elif isinstance(text, tuple) and text and text[0] == "__UPD_INSTALL_ERR__":
                messagebox.showerror(t("upd.err.title"),
                                     fmt("upd.err", e=text[1]), parent=self)
            else:
                self._log_line(text)
        # 正常退出（非等待重启）时链已在上方停住；等待重启时 120ms 一轮
        try:
            self.after(120, self._drain_log)
        except Exception:  # noqa: BLE001 - 窗口已销毁时链自然结束
            pass


    def _start_polling(self):
        self._drain_log()
        self._poll_log()
        self._status_worker.start()
        # #3：真实枚举交给 worker（646ms PowerShell），首帧已用缓存渲染
        try:
            self._status_q.put(("services", None, None, None, None))
        except Exception:  # noqa: BLE001
            pass
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
        """新行渐隐收尾：移除 flash 覆盖范围（保留 tag 本身的背景色定义）。

        必须用 tag_remove 而非 tag_delete——Tk 的 tag delete 会连标签的
        background **定义**一起删掉，而下一批日志只做 tag_add 范围、
        不再 tag_configure，于是第二轮起新行高亮静默失效（真实 CTkTextbox
        实测：收尾后 tag_cget('flash','background') 报 tag 未定义）。
        控件销毁后调用会抛 TclError，吞掉。
        """
        try:
            self.txt_log._textbox.tag_remove("flash", "1.0", "end")
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
                            # 与 _dirty() 同一语义判据（文本比较会误报历史/手写参数）
                            dirty = not semantically_equal(
                                build_params(snapshot, self.extras, FIELDS), cur, FIELDS)
                        except Exception:  # noqa: BLE001
                            dirty = None
                    self._status_r.put(("result", state, ok, detail, dirty))
                elif tag == "services":
                    # #3：真实枚举（646ms PowerShell）只在 worker 跑一次
                    try:
                        svcs = list_nssm_services()
                    except Exception:  # noqa: BLE001
                        svcs = []
                    self._status_r.put(("services", svcs, None, None, None))
            except Exception as exc:  # noqa: BLE001 - worker 任何异常不致死循环
                self._status_r.put(("result", "UNKNOWN", False, f"worker 异常: {exc}", None))

    def _sync_wraplengths(self):
        """P2 动态 wraplength：窗口变窄时 hint/warn 行跟随窗口宽度折行。

        滚动条逻辑在 real_resize 分支内，此处放分支外、用 try/except 兜底：
        UI 重建竞态下静默跳过，不干扰 _on_configure 的防抖与滚动条管理。
        """
        try:
            w = strings.wraplength_for(self.winfo_width())
            for lbl in (getattr(self, "lbl_hint", None), getattr(self, "lbl_warn", None)):
                if lbl is not None and lbl.winfo_exists() and lbl.winfo_manager():
                    lbl.configure(wraplength=w)
        except Exception:  # noqa: BLE001 - 重建竞态下静默
            pass

    def _note_interaction(self, _=None):
        """P3 呼吸静止优先：任何鼠标移动/按键都刷新最近交互时刻。

        呼吸循环的帧内判定（超 30s 停帧）据此恢复/暂停——不动状态机，
        只在 _breath_loop 里跳过写色，循环本身不断。
        """
        self._last_interaction = time.monotonic()

    def _on_configure(self, event=None):
        """缩放/拖拽防抖（缩放卡顿修复）：置 _resizing 并重置 300ms 定时器；
        连续 WM_CONFIGURE 期间 _drain_status/_poll_log 跳过 UI 应用。

        滚动条隐藏只在「窗口尺寸真实变化」时执行（event.width/height 与
        上次快照比对）：展开日志面板等内部布局重排虽也触发 Configure，
        但窗口尺寸不变——若在那种情况下隐藏/恢复滚动条，会形成
        「Configure→隐藏→重排→Configure」的振荡循环（日志面板持续抽动的
        根因）。尺寸变化才隐藏，两害兼治。"""
        real_resize = False
        if event is not None:
            w = getattr(event, "width", 0)
            h = getattr(event, "height", 0)
            # 用窗口真实几何字符串（含位置）做快照：展开日志只是内部重排，
            # geometry() 不变；真实缩放/移动 geometry() 一定变化
            try:
                cur = self.geometry()
            except Exception:  # noqa: BLE001
                cur = ""
            if cur and cur != self._last_geometry_snapshot:
                self._last_geometry_snapshot = cur
                real_resize = True
        if getattr(self, "_layout_mutating", False):
            real_resize = False  # 日志面板展开/折叠等内部布局重排：不视为缩放
        if real_resize:
            self._resizing = True
            try:
                sb = getattr(self.scroll, "_scrollbar", None)
                if sb is not None and sb.winfo_manager() == "grid":
                    sb.grid_remove()  # 缩放期间隐藏滚动条：砍掉 CTkScrollbar._draw 重绘热点
            except Exception:  # noqa: BLE001
                pass
        if self._resize_after is not None:
            try:
                self.after_cancel(self._resize_after)
            except Exception:  # noqa: BLE001
                pass
        self._resize_after = self.after(300, self._resize_done)
        # P2：动态 wraplength 放在 real_resize 分支外——仅当尺寸真实变化或
        # 首次建窗时更新，避免内部布局重排反复触发无谓的 configure
        if real_resize or event is None:
            self._sync_wraplengths()

    def _resize_done(self):
        self._resizing = False
        self._resize_after = None
        try:
            sb = getattr(self.scroll, "_scrollbar", None)
            if sb is not None:
                mgr = sb.winfo_manager()
                if mgr == "":        # 被 grid_remove 过：恢复
                    sb.grid(row=1, column=1, sticky="nsew")
                # mgr == "grid" 已是正常态，不动
        except Exception:  # noqa: BLE001
            pass

    def _drain_status(self):
        """主线程消费 _status_r：应用状态/探活/按钮联动/dirty 提示。
        节流合并（一次 drain 处理全部积压）；窗口缩放/拖拽期间（_resizing）
        跳过 UI 应用，避免与 WM_CONFIGURE 高频重排抢主线程。"""
        if self._stop_poll:
            return
        got = None
        svcs = None
        try:
            while True:
                item = self._status_r.get_nowait()
                if not item:
                    continue
                if item[0] == "result":
                    got = item
                elif item[0] == "services":
                    svcs = item[1]
        except queue.Empty:
            pass
        if svcs is not None:
            # #3：worker 枚举回灌——刷新下拉并落盘，下次启动即可首帧命中
            try:
                names = [s for s in svcs if isinstance(s, str)]
                if names and names != self.settings.get("services", []):
                    self.settings["services"] = names
                    self._save_settings()
                if names:
                    self.cmb_service.configure(values=self._first_paint_services())
            except Exception:  # noqa: BLE001
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
                # 服务名变化（on_service_change）立即同步到状态卡完整名 label
                if hasattr(self, "lbl_svc"):
                    cur_svc = self.service_var.get()
                    if self.lbl_svc.cget("text") != cur_svc:
                        self.lbl_svc.configure(text=cur_svc)
                if state == "RUNNING":
                    self.lbl_health.configure(
                        text=(fmt("status.health.ok", d=detail[:26]) if ok else fmt("status.health.bad", d=detail[:26])),
                        text_color=C_RUN if ok else C_RED)
                    self._update_status_dot(state, ok)
                else:
                    self.lbl_health.configure(text=t("health.down"), text_color=C_GRAY)
                    self._update_status_dot(state, True)
                # dirty 由 worker 用表单快照 + nssm 对比回传（主线程永不 spawn nssm）
                if got[4] is not None:
                    self._dirty_cache = got[4]
                dirty = self._dirty_cached()
                self.lbl_dirty.configure(text=t("status.dirty") if dirty else "")
                self.btn_revert.configure(state="normal" if dirty else "disabled")
            except Exception:  # noqa: BLE001 - 控件销毁竞态静默
                pass
        self.after(400, self._drain_status)

    def _on_close(self):
        # 关窗守护（短期清单第 1 条）：重启或更新进行中不得静默退出。
        # 用户确认后：
        # - 安装中：窗口立即销毁，安装线程为非 daemon，主进程会等它把
        #   当前文件替换/回滚步骤跑完，不会留下半更新状态的二进制；
        # - 重启中：窗口保留，_drain_log 持续消费哨兵，重启收尾后自动销毁。
        busy = getattr(self, "_restarting", False) or getattr(self, "_upd_installing", False)
        if busy:
            if not messagebox.askyesno(
                    t("mb.busy"), t("msg.close.busy"), parent=self):
                return
            if not getattr(self, "_upd_installing", False):
                # 等重启完成：保留 drain 链消费 __RESTART_DONE__ 后自动关窗
                self._close_after_restart = True
        self._stop_poll = True
        if self._upd_startup_after is not None:
            try:
                self.after_cancel(self._upd_startup_after)
            except Exception:  # noqa: BLE001
                pass
            self._upd_startup_after = None
        if getattr(self, "_prune_startup_after", None) is not None:
            try:
                self.after_cancel(self._prune_startup_after)
            except Exception:  # noqa: BLE001
                pass
            self._prune_startup_after = None
        self.anim.cancel_all()  # 停掉全部在途动画，帧回调发现不在注册表即自停
        # 按钮/帮助提示渐隐帧由 self.anim 驱动，cancel_all 已统一停掉（F1/#4）
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
            self._save_settings()
        except Exception:  # noqa: BLE001 - 设置保存失败不阻断退出
            pass
        # 等待重启收尾：保留窗口，_drain_log 在 __RESTART_DONE__ 后自动销毁
        if getattr(self, "_close_after_restart", False):
            return
        self.destroy()


    def _motion_on(self):
        """动效总开关（design-guide §五）：关闭后 D3-D7 所有动画直跳终态。"""
        return bool(self.settings.get("motion_enabled", True))

    # ---- 设置窗口 ----
    def open_settings(self):
        win = ctk.CTkToplevel(self)
        win.title(t("settings.title"))
        win.geometry("560x600")  # 含官方更新区：加宽加高
        win.transient(self)
        win.grab_set()
        self._settings_win = win

        ctk.CTkLabel(win, text=t("settings.lang"), font=F_BODY, anchor="w"
                     ).pack(fill="x", padx=20, pady=(20, 4))
        # 用显式变量绑定：取消未应用更改保护时能把下拉显示回滚到实际语言/外观
        self._lang_var = tk.StringVar(
            value="中文" if strings._current == "zh" else "English")
        lang_menu = ctk.CTkOptionMenu(
            win, values=["中文", "English"], width=180, font=F_BODY,
            variable=self._lang_var,
            command=lambda v: self._change_language(v, win))
        lang_menu.pack(anchor="w", padx=20)

        ctk.CTkLabel(win, text=t("settings.appear"), font=F_BODY, anchor="w"
                     ).pack(fill="x", padx=20, pady=(16, 4))
        appear_names = {"system": t("appear.system"), "light": t("appear.light"),
                        "dark": t("appear.dark")}
        rev = {v: k for k, v in appear_names.items()}
        self._appear_var = tk.StringVar(
            value=appear_names.get(self.settings.get("appearance", "system"),
                                   t("appear.system")))
        appear_menu = ctk.CTkOptionMenu(
            win, values=list(appear_names.values()), width=180, font=F_BODY,
            variable=self._appear_var,
            command=lambda v: self._change_appearance(rev[v], win))
        appear_menu.pack(anchor="w", padx=20)

        # 动效总开关（即时生效，无需 _restart_ui）
        self._motion_var = tk.BooleanVar(value=self.settings.get("motion_enabled", True))
        motion_cb = ctk.CTkCheckBox(
            win, text=t("settings.motion"), variable=self._motion_var,
            font=F_BODY, text_color=C_TXT, fg_color=C_ACC,
            hover_color=C_ACCH, border_color=C_BORDER, corner_radius=6,
            command=self._change_motion)
        motion_cb.pack(anchor="w", padx=20, pady=(16, 4))

        # ---- 官方更新区 ----
        sep = ctk.CTkFrame(win, height=1, fg_color=C_BORDER, corner_radius=0)
        sep.pack(fill="x", padx=20, pady=(16, 8))

        ctk.CTkLabel(win, text=t("upd.section"), font=F_GROUP, text_color=C_TXT,
                     anchor="w").pack(fill="x", padx=20)

        # 二进制变体（内部存 channel 键，下拉展示友好名）
        ctk.CTkLabel(win, text=t("upd.channel"), font=F_BODY, text_color=C_MUT,
                     anchor="w").pack(fill="x", padx=20, pady=(10, 4))
        _ch_names = {ch: updater.CHANNELS.get(ch, ch) for ch in updater.CHANNEL_ORDER}
        _ch_keys = {v: k for k, v in _ch_names.items()}
        # 显示值取自 _upd_channel()（已把退役/非法的持久化值回退到默认）。若直接读
        # settings，旧 settings.json 存的退役变体会让下拉显示旧版本、而检查用默认版本，
        # 用户看到「下拉显示 13.4 却报 channel 13.3」的错位，误以为修复没生效。
        self._upd_channel_var = tk.StringVar(value=_ch_names[self._upd_channel()])
        ctk.CTkOptionMenu(
            win, values=list(_ch_names.values()), width=220, font=F_BODY,
            variable=self._upd_channel_var,
            command=lambda shown: self._change_upd_channel(
                _ch_keys.get(shown, shown))
        ).pack(anchor="w", padx=20)

        # 启动自动检查开关
        self._upd_auto_var = tk.BooleanVar(
            value=bool(self.settings.get("upd_check_on_startup", True)))
        ctk.CTkCheckBox(
            win, text=t("upd.auto.label"), variable=self._upd_auto_var,
            font=F_BODY, text_color=C_TXT, fg_color=C_ACC,
            hover_color=C_ACCH, border_color=C_BORDER, corner_radius=6,
            command=self._change_upd_auto).pack(anchor="w", padx=20, pady=(14, 4))

        # 版本状态 + 立即检查
        self._upd_status_lbl = ctk.CTkLabel(
            win, text="", font=F_SMALL, text_color=C_MUT, anchor="w",
            justify="left", wraplength=480)
        self._upd_status_lbl.pack(fill="x", padx=20, pady=(8, 4))
        self._upd_check_btn = self._btn(win, t("upd.check"), self._check_updates_manual)
        self._upd_check_btn.pack(anchor="w", padx=20)
        self._refresh_upd_status_label()

        ctk.CTkLabel(win, text=t("settings.note"), font=F_SMALL, text_color=C_MUT,
                     wraplength=480, justify="left").pack(fill="x", padx=20, pady=(14, 0))
        self._btn(win, t("settings.close"), win.destroy).pack(pady=(14, 12))

    def _change_language(self, shown, win=None):
        if not self._confirm_rebuild_dirty():
            self._restore_setting_widgets()   # 取消：下拉显示回滚到实际语言
            return
        self.settings["language"] = "zh" if shown == "中文" else "en"
        strings.set_lang(self.settings["language"])
        self._save_settings()
        self._restart_ui()

    def _change_appearance(self, mode, win=None):
        if not self._confirm_rebuild_dirty():
            self._restore_setting_widgets()   # 取消：下拉显示回滚到实际外观
            return
        self.settings["appearance"] = mode
        self._save_settings()
        self._restart_ui()

    def _restore_setting_widgets(self):
        """把设置页语言/外观下拉的显示回滚到实际生效值（取消保护后调用）。

        _lang_var/_appear_var 是 tk.StringVar——**没有** winfo_exists()。旧实现
        对它们调用 winfo_exists() 抛 AttributeError，被 except 吞掉，于是整个
        回滚是死代码：用户点「取消」后下拉仍显示被拒的语言/外观，与实跑不符。
        只对控件（有 winfo_exists 的）做存在性检查，变量直接 set。
        """
        for attr, value in (
                ("_lang_var", "中文" if strings._current == "zh" else "English"),
                ("_appear_var", {"system": t("appear.system"),
                                 "light": t("appear.light"),
                                 "dark": t("appear.dark")}.get(
                                     self.settings.get("appearance", "system"),
                                     t("appear.system")))):
            var = getattr(self, attr, None)
            if var is None:
                continue
            try:
                var.set(value)
            except Exception:  # noqa: BLE001 - 控件已销毁/变量失效
                pass

    def _confirm_rebuild_dirty(self):
        """切换语言/外观前的未应用更改保护（_restart_ui 会重建界面并丢弃表单）。

        _restart_ui → refresh_all → load_params 会用服务当前值覆盖表单，
        因此若不设防，用户改完参数没点「应用更改」就切语言，编辑会静默消失。
        与切服务/切预设同策略：确认后自动备份为新预设，取消则整体中止
        （调用方在弹确认前就返回，既不重建 UI 也不写 settings）。

        返回 True = 可以继续；False = 用户取消，调用方必须原样返回。
        """
        try:
            dirty = self._dirty()
        except Exception:  # noqa: BLE001 - 读取失败不阻断设置切换（保守放行）
            return True
        if not dirty:
            return True
        if not messagebox.askyesno(t("mb.confirm"), t("msg.rebuild.dirty"), parent=self):
            return False
        values, _ = self._collect()
        presets = load_presets()
        presets[fmt("preset.autobackup", t=time.strftime('%m-%d %H:%M:%S'))] = values
        self._save_presets(presets)
        self.refresh_presets()
        return True

    def _change_motion(self):
        """动效开关回调：写设置并落盘，即时生效，不重启 UI。"""
        self.settings["motion_enabled"] = bool(self._motion_var.get())
        self._save_settings()

    # ---- 官方更新（llama.cpp） ----
    def _upd_channel(self):
        """当前选择的官方二进制变体（优先设置值，非法回退默认）。"""
        ch = self.settings.get("upd_channel", updater.DEFAULT_CHANNEL)
        return ch if ch in updater.CHANNELS else updater.DEFAULT_CHANNEL

    def _upd_target_dir(self):
        """替换目标：优先按当前服务 NSSM AppDirectory 推导，失败回退 LLAMA_DIR。"""
        try:
            d = app_directory(self.service)
            if d and os.path.isdir(d):
                return d
        except Exception:  # noqa: BLE001
            pass
        return LLAMA_DIR

    # 更新缓存/备份的保留份数（每次安装新增一个 tag/时间戳目录，长期堆积可达 GB 级）
    PRUNE_KEEP = 3

    def _prune_update_dirs(self):
        """启动后台清理 downloads/{tag} 与 backup/{tag}/{时间戳} 的陈旧目录。

        放后台线程：目录可达 GB 级，rmtree 不应占主线程。任何异常一律静默
        吞掉——清理失败绝不能弹窗或阻断启动；确有删除时经 _log_q 写一行日志
        （_log_q 是线程安全入口，UI 由 _drain_log 在主线程渲染）。
        """
        self._prune_startup_after = None

        def _work():
            # downloads/{tag}/ 是「tag 目录里放文件」，backup/{tag}/{时间戳}/ 是
            # 「tag 目录里再套时间戳目录」——后者必须逐 tag 下钻清理，否则同一
            # tag 反复安装会让备份无限堆积（每次约 1.3GB）。
            for root, nested in ((UPD_DOWNLOAD_DIR, False),
                                 (UPD_BACKUP_ROOT, True)):
                try:
                    prune = (updater.prune_nested_subdirs if nested
                             else updater.prune_old_subdirs)
                    removed = prune(root, keep=self.PRUNE_KEEP)
                except Exception:  # noqa: BLE001 - 清理失败绝不打扰用户
                    continue
                if removed:
                    try:
                        self._log_q.put(fmt("upd.prune", n=len(removed), d=root))
                    except Exception:  # noqa: BLE001
                        pass

        try:
            threading.Thread(target=_work, daemon=True).start()
        except Exception:  # noqa: BLE001 - 线程创建失败不阻断启动
            pass

    def _upd_server_exe(self):
        return os.path.join(self._upd_target_dir(), "llama-server.exe")

    def _change_upd_channel(self, channel):
        """切换二进制变体：写盘并清掉旧检查结果（状态标签跟随语言实时刷新）。"""
        if channel not in updater.CHANNELS:
            channel = updater.DEFAULT_CHANNEL
        self.settings["upd_channel"] = channel
        self._save_settings()
        self._upd_release = None
        self._refresh_upd_status_label()

    def _change_upd_auto(self):
        self.settings["upd_check_on_startup"] = bool(self._upd_auto_var.get())
        self._save_settings()

    def _installed_build(self):
        """本地 build 号（查 llama-server.exe --version；异常返回 None）。"""
        try:
            return updater.get_installed_build(self._upd_server_exe())
        except Exception:  # noqa: BLE001
            return None

    def _refresh_upd_status_label(self, status=None):
        """更新设置页状态行；status 优先（'checking' / ('done', tag) / ('fail', msg)）。

        默认分支要读本地 build 号，而那是 spawn llama-server.exe --version
        （冷盘/杀软扫描下可达数秒，实现里 timeout=20）。文件其它同步阻塞调用
        都已被移进 worker，唯独这里在主线程——打开设置窗会白屏冻结。故默认
        分支改为**先显示占位、再后台取版本**，拿到后经 _log_q 回主线程刷新。
        """
        lbl = getattr(self, "_upd_status_lbl", None)
        if lbl is None or not lbl.winfo_exists():
            return
        if status == "checking":
            lbl.configure(text=t("upd.checking"))
            return
        if isinstance(status, tuple) and status and status[0] == "done":
            lbl.configure(text=fmt("upd.check.done", t=status[1]))
            return
        if isinstance(status, tuple) and status and status[0] == "fail":
            lbl.configure(text=fmt("upd.check.fail", e=status[1]))
            return
        if isinstance(status, tuple) and status and status[0] == "build":
            b = status[1]
            lbl.configure(text=fmt("upd.status.now", b="b%d" % b) if b is not None
                          else t("upd.status.unknown"))
            return
        if self._upd_build_pending:
            lbl.configure(text=t("upd.status.checking"))
            return
        self._upd_build_pending = True
        lbl.configure(text=t("upd.status.checking"))

        def _work():
            b = self._installed_build()      # 阻塞调用只在 worker 里
            try:
                self._log_q.put(("__UPD_BUILD__", b))
            except Exception:  # noqa: BLE001
                pass

        try:
            threading.Thread(target=_work, daemon=True).start()
        except Exception:  # noqa: BLE001 - 线程创建失败则保持占位文案
            pass

    def _upd_assets_names(self):
        return [a.get("name") or "?" for a in (self._upd_release or {}).get("assets", [])]

    def _check_updates_startup(self):
        """启动自动检查：后台跑，有新版本时弹「更新日志」窗口（仅提示）。"""
        self._upd_startup_after = None
        self._check_updates_worker(interactive=False)

    def _check_updates_manual(self):
        """设置页「立即检查」：后台跑，完成后强制弹更新日志窗口。"""
        self._check_updates_worker(interactive=True)

    def _upd_check_btn_set(self, state, text):
        """设置「立即检查」按钮状态；控件已销毁时静默跳过。

        getattr 拿到的是**引用**而非活性：语言/外观重建会销毁设置窗，而
        _upd_check_btn 仍指向旧控件，直接 configure 会抛 TclError。该异常发生在
        _upd_checking 置 True 之后，会把防重入标志永久卡在 True——此后所有更新
        检查都在入口静默 return（表现为「检查按钮从此没反应」）。故必须不抛。
        """
        btn = getattr(self, "_upd_check_btn", None)
        if btn is None:
            return
        try:
            if not btn.winfo_exists():
                return
            btn.configure(state=state, text=text)
        except Exception:  # noqa: BLE001 - 控件销毁竞态
            pass

    def _check_updates_worker(self, interactive):
        """后台检查线程：worker 只碰 updater/网络，结果经 after 回主线程。"""
        if self._upd_checking:
            return
        self._upd_checking = True
        channel = self._upd_channel()
        try:
            self._refresh_upd_status_label("checking")
            self._upd_check_btn_set("disabled", t("upd.checking"))
        except Exception:  # noqa: BLE001 - 状态刷新失败不得阻断检查本身
            pass

        def _work():
            err = None
            rel = None
            cur = None
            try:
                rel = updater.find_latest_release(channel)
            except Exception as exc:  # noqa: BLE001 - 网络/解析错误统一回传
                err = str(exc)
            if rel is not None:
                # 本地 build 号也在 worker 里取：它是 spawn llama-server.exe
                # --version，主线程绝不能做（冷盘/杀软下可达数秒）。
                cur = self._installed_build()
            # Tk 的 after 只能从创建 Tcl 解释器的线程（主线程）调用；worker 线程
            # 一律经 _log_q 派发哨兵回主线程（项目内 NSSM 状态 worker 同模式）。
            self._log_q.put(("__UPD_CHECK_DONE__", rel, err, interactive,
                             channel, cur))

        self._upd_worker = threading.Thread(target=_work, daemon=True)
        self._upd_worker.start()

    def _check_updates_done(self, rel, err, interactive, checked_channel=None,
                            cur=None):
        try:
            alive = bool(self.winfo_exists())
        except Exception:  # noqa: BLE001
            alive = False
        if not alive:
            return
        self._upd_checking = False
        self._upd_check_btn_set("normal", t("upd.check"))
        # 用户在检查期间切换了二进制版本：丢弃过期结果
        if checked_channel is not None and checked_channel != self._upd_channel():
            self._refresh_upd_status_label()
            return
        if err:
            self._upd_release = None
            self._refresh_upd_status_label(("fail", err))
            if interactive:
                messagebox.showerror(t("upd.check.fail"),
                                     fmt("upd.check.fail", e=err), parent=self)
            return
        if not rel or not rel.get("assets"):
            self._upd_release = None
            self._refresh_upd_status_label(("fail", t("upd.required")))
            if interactive:
                messagebox.showerror(t("upd.check.fail"), t("upd.required"),
                                     parent=self)
            return
        self._upd_release = rel
        if cur is None:
            cur = self._installed_build()   # 兼容旧的 4 元组调用（无 worker 预取）
        self._refresh_upd_status_label(("done", rel["tag"]))
        if cur is not None and rel.get("build") and rel["build"] <= cur:
            if interactive:
                messagebox.showinfo(t("upd.uptodate"),
                                    fmt("upd.uptodate.msg", cur=cur,
                                        new=rel["build"]), parent=self)
            return
        # 有新版本（或本地版本未知）：弹更新日志窗口
        self._show_changelog(rel, cur)

    def _upd_install(self, top):
        """「立即更新」：二次确认（停服务 + 备份路径）→ 启动后台安装线程。"""
        rel = self._upd_release
        if not rel or not rel.get("assets"):
            return
        stamp = time.strftime("%Y%m%d_%H%M%S")
        bak = os.path.join(UPD_BACKUP_ROOT, rel["tag"], stamp)
        try:
            top.grab_release()
        except Exception:  # noqa: BLE001
            pass
        if not messagebox.askyesno(
                t("mb.confirm"),
                fmt("upd.install.confirm", s=self.service, d=bak), parent=top):
            try:
                top.grab_set()
            except Exception:  # noqa: BLE001
                pass
            return
        try:
            top.destroy()
        except Exception:  # noqa: BLE001
            pass
        self._upd_modal_open = False
        # 主线程快照：worker 期间 UI 切换服务/目录也不影响本次安装
        service = self.service
        target = self._upd_target_dir()
        # 关窗守护：安装进行中禁止直接退出（daemon 线程会被强杀）。
        # 安装线程改为非 daemon，即使窗口被强行销毁，线程也会把
        # 当前文件替换/回滚步骤跑完，不会留下半更新状态的二进制。
        self._upd_installing = True
        self._log_q.put(t("upd.installing"))

        def _work():
            try:
                self._do_update_worker(rel, service, target, bak)
            except Exception as exc:  # noqa: BLE001
                # 回滚与尽力重启已由 installer.install 内部完成，这里只汇报错误
                self._log_q.put(fmt("upd.err", e=exc))
                self._log_q.put(("__UPD_INSTALL_ERR__", str(exc)))
            finally:
                self._log_q.put("__REFRESH_STATUS__")
                # 哨兵在主线程消费：复位 _upd_installing，让关窗守护放行
                self._log_q.put("__UPD_DONE__")

        threading.Thread(target=_work, daemon=False).start()

    def _do_update_worker(self, rel, service, target, bak):
        """后台安装序列：薄包装 installer.install（实现见 installer 深模块）。

        事务保障（短期清单第 2 条）：备份失败即中止且未替换任何文件；
        任一步失败按 replaced 精确回滚；失败收尾尽力重启服务。
        """
        installer.install(rel, service, target, bak,
                          sink=self._log_q.put, download_dir=UPD_DOWNLOAD_DIR)


    def _show_changelog(self, rel, cur):
        """更新日志弹窗（模态）：提示/可滚动日志/下载清单/立即更新。"""
        if self._upd_modal_open:
            return
        self._upd_modal_open = True
        top = ctk.CTkToplevel(self)
        top.title(fmt("upd.title", t=rel["tag"]))
        top.geometry("680x560")
        top.transient(self)
        try:
            top.grab_set()
        except Exception:  # noqa: BLE001 - 主窗口/设置窗已有 grab 时降级为普通窗口
            pass
        try:
            top.lift()
        except Exception:  # noqa: BLE001
            pass

        def _close():
            self._upd_modal_open = False
            try:
                top.destroy()
            except Exception:  # noqa: BLE001
                pass

        head = fmt("upd.prompt", n=rel.get("build") or rel["tag"],
                   c=("b%d" % cur) if cur else "?")
        ctk.CTkLabel(top, text=head, font=F_BODY, text_color=C_TXT, anchor="w",
                     justify="left", wraplength=620
                     ).pack(fill="x", padx=24, pady=(20, 10))

        # 官方 nightly 发布**没有**更新说明（实测 release 页面 markdown-body 命中 0 处），
        # 旧实现恒传空 body，于是这里永远显示「还未检查过更新」占位文案，用户
        # 以为日志加载失败。改为如实说明「官方 nightly 不提供说明」并给出资产与
        # 构建号，不再假装日志缺失是异常。
        ctk.CTkLabel(top, text=t("upd.changelog"), font=F_GROUP, text_color=C_MUT,
                     anchor="w").pack(fill="x", padx=24)
        frame = ctk.CTkFrame(top, fg_color=C_BG, border_width=1,
                             border_color=C_BORDER, corner_radius=8)
        frame.pack(fill="both", expand=True, padx=24, pady=(6, 10))
        body = rel.get("body") or fmt(
            "upd.no.changelog",
            t=rel.get("tag") or "?", b=rel.get("build") or "?")
        txt = ctk.CTkTextbox(frame, font=F_SMALL, text_color=C_TXT,
                             fg_color=C_BG, border_width=0, wrap="word")
        txt.pack(fill="both", expand=True, padx=8, pady=8)
        txt.insert("1.0", body)
        txt.configure(state="disabled")

        ctk.CTkLabel(top, text=fmt("upd.assets", a=", ".join(self._upd_assets_names())),
                     font=F_SMALL, text_color=C_MUT, anchor="w", wraplength=620,
                     justify="left").pack(fill="x", padx=24, pady=(0, 12))

        btnrow = ctk.CTkFrame(top, fg_color="transparent")
        btnrow.pack(fill="x", padx=24, pady=(0, 20))
        self._btn(btnrow, t("settings.close"), _close).pack(side="right")
        self._btn(btnrow, t("upd.install"), lambda: self._upd_install(top),
                  kind="primary").pack(side="right", padx=(0, 10))
        top.protocol("WM_DELETE_WINDOW", _close)
        try:
            top.grab_set()
        except Exception:  # noqa: BLE001 - 降级为普通窗口
            pass

    def _restart_ui(self):
        """销毁并按新语言/调色板重建全部部件（设置即时生效）。"""
        _set_appearance(self.settings.get("appearance", "system"))
        for w in self.winfo_children():
            w.destroy()
        self._upd_modal_open = False  # 语言/外观重建会销毁更新日志弹窗，复位互斥
        self.var.clear()
        self.widgets.clear()
        self.val_labels.clear()
        # 状态圆点动效复位：新控件未知，取消在途动画并重置全部 id/守卫
        self.anim.cancel_all()
        self._log_anim_id = -1
        # 字段高亮计时器全部失效（旧控件已销毁），清空即可（D7）
        self._field_flash_after.clear()
        self._suppress_trace = False
        # F1 按钮/帮助提示渐隐帧：旧控件已随上方 destroy 销毁，动画帧由共享
        # Animator 驱动，cancel_all 已在上方停掉，帧回调兜底 winfo_exists 无 TclError。
        # D8 折叠分组展开状态保留（group_open 在 _build_widgets 里按存量恢复）
        self._breathing = False
        self._breath_id = -1
        self._flash_id = -1
        self._breath_resume = False
        self._flash_armed = True
        self.title(t("app.title"))
        self.configure(fg_color=C_BG)
        self._build_widgets()
        # P2：重建后 hint/warn 是全新控件，wraplength 归零——重建末重调一次
        # 动态折行（无窗口尺寸变化的语言切换也会走到这里；真实缩放仍由
        # _on_configure 的 real_resize 分支驱动）
        self._sync_wraplengths()
        self.refresh_all()


def main():
    app = ControlGUI()
    app.mainloop()


if __name__ == "__main__":
    main()

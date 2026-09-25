#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""presets.py — 命名参数组合持久化（llama_ctl）

与 settings.py 同模式：固定路径、原子写、损坏回退空字典。
"""

import json
import os

# 预设文件：存命名参数组合（含全部字段 values），独立于具体服务。
# 路径可用环境变量 LLAMA_CTL_PRESETS 覆盖（便于跨机器部署）；
# 默认保持本机固定路径，exe 在 dist\ 下运行也读写同一份，
# 避免「exe 换目录/升级后预设丢失」与双副本分裂。
PRESETS_FILE = os.environ.get("LLAMA_CTL_PRESETS") or r"F:\llama_ctl\presets.json"


def load_presets():
    """读取预设字典 {name: {key: value}}。文件不存在/损坏/非字典返回空字典。

    每次真实读盘：文件是本工具与用户手工编辑共用的落点，任何基于
    mtime+size 的进程内缓存都会漏判「同一时间戳刻度内等长改写」
    （NTFS 时间戳粒度约 15.6 ms），把外部改动静默吞掉。整份读 + json.load
    约 47 µs，一次预设点击至多 2-3 次，不值得为它冒数据不一致的风险。
    """
    try:
        with open(PRESETS_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)
    except Exception:  # noqa: BLE001
        return {}
    return loaded if isinstance(loaded, dict) else {}


def save_presets(presets):
    """写回预设字典到 PRESETS_FILE（原子写：先临时文件再替换）。"""
    tmp = PRESETS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(presets, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PRESETS_FILE)

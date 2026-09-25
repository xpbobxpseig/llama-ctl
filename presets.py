#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""presets.py — 命名参数组合持久化（llama_ctl）

与 settings.py 同模式：固定路径、原子写、损坏回退空字典；外加进程内 cache。

此前 load_presets() 每次调用都 open + json.load 整份文件，一次预设点击会触发
2-3 次整文件读 + 1 次写。cache 让重复 load 只剩一次 os.stat 校验，接口仍是
load_presets()/save_presets()，调用点零改动。
"""

import json
import os

# 预设文件：存命名参数组合（含全部字段 values），独立于具体服务。
# 统一固定到 F:\llama_ctl\presets.json：exe 在 dist\ 下运行也读写同一份，
# 避免「exe 换目录/升级后预设丢失」与双副本分裂。
PRESETS_FILE = r"F:\llama_ctl\presets.json"

# 进程内 cache：_cache 为上次解析出的字典，_cache_sig 为读入时的文件签名。
# ponytail: 签名用 (st_mtime_ns, st_size)。NTFS 时间戳 100ns 粒度，理论上
# 外部写入者若在同一 tick 内写入同尺寸内容会被漏判；升级路径是加上 inode/
# 内容哈希。本工具只有单进程写，够用。
_cache = None
_cache_sig = None


def _signature():
    """当前文件签名；文件不存在返回 None。"""
    try:
        st = os.stat(PRESETS_FILE)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def load_presets():
    """读取预设字典 {name: {key: value}}。文件不存在/损坏返回空字典。

    文件签名未变则复用上次解析结果（省掉重复 json.load）；文件被外部改写、
    删除或新建时会自动失效重读。返回浅拷贝，调用方可自由增删改。
    """
    global _cache, _cache_sig
    sig = _signature()
    if _cache is not None and sig == _cache_sig:
        return dict(_cache)
    data = {}
    if sig is not None:
        try:
            with open(PRESETS_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data = loaded
        except Exception:  # noqa: BLE001
            data = {}
    _cache, _cache_sig = data, sig
    return dict(data)


def save_presets(presets):
    """写回预设字典到 PRESETS_FILE（原子写：先临时文件再替换），并刷新 cache。"""
    global _cache, _cache_sig
    tmp = PRESETS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(presets, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PRESETS_FILE)
    _cache, _cache_sig = dict(presets), _signature()

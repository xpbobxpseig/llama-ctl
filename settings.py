#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
settings.py — 工具偏好持久化（llama_ctl）

语言/外观/窗口几何/最后预设名。与 presets.json 同模式：固定路径、原子写、
损坏回退默认值。
"""

import json
import os

SETTINGS_FILE = r"F:\llama_ctl\settings.json"

DEFAULTS = {
    "language": "zh",        # "zh" | "en"
    "appearance": "system",  # "system" | "light" | "dark"
    "geometry": None,        # "WxH+X+Y" 字符串，None = 系统默认
    "last_preset": "",       # 最后选中的预设名
}


def load_settings():
    """读取设置；缺文件/损坏/类型不符的键逐项回退默认。"""
    merged = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for k in DEFAULTS:
                if k in data and isinstance(data[k], type(DEFAULTS[k]) if DEFAULTS[k] is not None else str):
                    merged[k] = data[k]
    except FileNotFoundError:
        pass
    except Exception:  # noqa: BLE001
        pass
    return merged


def save_settings(settings):
    """写回设置（原子写：先临时文件再替换）。未知键忽略。"""
    out = {k: settings.get(k, DEFAULTS[k]) for k in DEFAULTS}
    tmp = SETTINGS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    os.replace(tmp, SETTINGS_FILE)

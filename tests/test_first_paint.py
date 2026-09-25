# -*- coding: utf-8 -*-
"""#3 启动骨架：首帧服务列表装配顺序的纯逻辑单测。

不 import tkinter——直接以假 self 调用未绑定的 ControlGUI._first_paint_services，
只验证「缓存优先 + 缓存缺失时换入当前服务」这条非平凡分支。
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import llama_ctl_gui as g


def _call(service, cached):
    fake = types.SimpleNamespace(service=service, settings={"services": cached})
    return g.ControlGUI._first_paint_services(fake)


def test_empty_cache_returns_current_only():
    assert _call("Svc", []) == ["Svc"]


def test_cache_hit_preserves_order():
    assert _call("B", ["A", "B", "C"]) == ["A", "B", "C"]


def test_cache_miss_prepends_current():
    # 当前服务不在缓存里（新装/改名）：换到首位，缓存其余保留
    assert _call("Z", ["A", "B"]) == ["Z", "A", "B"]


def test_non_str_entries_dropped():
    assert _call("Svc", [1, "A", None]) == ["Svc", "A"]

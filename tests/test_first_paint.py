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


def test_upd_channel_falls_back_when_persisted_value_is_retired():
    """旧 settings.json 存的退役变体必须回退到默认。

    根因回归：官方停发 13.3 后 CHANNELS 里删掉了该键，但用户本地 settings.json
    仍存着 "win-cuda-13.3-x64"。若 _upd_channel() 原样返回它，每次检查都会请求
    一个官方不再产出的 channel，报「未找到匹配资产」。
    """
    def ch(stored):
        fake = types.SimpleNamespace(settings={"upd_channel": stored})
        return g.ControlGUI._upd_channel(fake)

    assert ch("win-cuda-13.3-x64") == g.updater.DEFAULT_CHANNEL
    assert ch("win-cuda-12.4-x64") == "win-cuda-12.4-x64"   # 合法值原样保留
    assert ch("bogus-channel") == g.updater.DEFAULT_CHANNEL
    assert ch("") == g.updater.DEFAULT_CHANNEL
    assert ch(None) == g.updater.DEFAULT_CHANNEL


def test_every_offered_channel_is_a_known_channel():
    """下拉里能选到的每个值都必须能被 _upd_channel() 原样保留（显示 = 实际检查）。"""
    for channel in g.updater.CHANNEL_ORDER:
        fake = types.SimpleNamespace(settings={"upd_channel": channel})
        assert g.ControlGUI._upd_channel(fake) == channel


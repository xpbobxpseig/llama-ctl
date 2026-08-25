# -*- coding: utf-8 -*-
"""strings.py 单测：i18n 文案卫生 + P2 动态 wraplength 公式。纯数据模块，不 import tkinter。

覆盖：
- zh/en 键集合一致（语言切换零缺键）
- en 文案人工审稿落地：无超长（按钮/状态行 ≤ 屏宽裕量，messagebox 自动换行除外）
- fmt 占位符两端一致（zh/en 用同一组 {kw}，语言切换不 KeyError）
- wraplength_for 公式：宽窗口直减、窄窗口下限 400、类型健壮
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import strings


# ---------------------------------------------------------------------------
# 键集合一致性
# ---------------------------------------------------------------------------

def test_every_key_has_both_languages():
    for key, entry in strings.STRINGS.items():
        assert "zh" in entry and "en" in entry, f"{key} 缺语言"
        assert entry["zh"] and entry["en"], f"{key} 有空文案"


def test_t_and_fmt_roundtrip():
    for key in strings.STRINGS:
        for lang in ("zh", "en"):
            strings.set_lang(lang)
            assert strings.t(key), key
    strings.set_lang("zh")
    assert strings.fmt("msg.preset.miss", n="x") == "预设「x」不存在。"


# ---------------------------------------------------------------------------
# 按钮/状态行 en 长度人工审稿（P2 验收：无超长）
# 阈值依据：F_BODY=13px @144DPI，中文≈16.3px/字，拉丁≈8.2px/字；
# 状态行可用 ≈840px，按最坏情况（全宽字符）约 51 字。
# ---------------------------------------------------------------------------

STATUS_KEYS = [
    "svc.label", "state.unknown", "health.idle", "health.down",
    "boot.label", "boot.auto", "boot.manual", "boot.disabled",
    "status.dirty",
]


def test_status_row_en_lengths():
    for key in STATUS_KEYS:
        en = strings.STRINGS[key]["en"]
        assert len(en) <= 50, f"{key} en 超长: {en!r}"


def test_button_en_lengths():
    for key in ("btn.start", "btn.stop", "btn.restart", "btn.revert",
                "btn.apply2", "btn.settings", "preset.delete", "browse"):
        en = strings.STRINGS[key]["en"]
        assert len(en) <= 28, f"{key} en 超长: {en!r}"


def test_log_toggle_en_length():
    for key in ("log.collapsed", "log.expanded"):
        en = strings.STRINGS[key]["en"]
        assert len(en) <= 45, f"{key} en 超长: {en!r}"


def test_settings_label_en_length():
    en = strings.STRINGS["settings.lang"]["en"]
    assert len(en) <= 45, f"settings.lang en 超长: {en!r}"


# ---------------------------------------------------------------------------
# fmt 占位符一致（缺 kw 时 en/zh 同报错，绝不静默丢参）
# ---------------------------------------------------------------------------

def test_fmt_placeholders_identical():
    import re
    for key, entry in strings.STRINGS.items():
        zh_ph = set(re.findall(r"\{([a-z_]+)\}", entry["zh"]))
        en_ph = set(re.findall(r"\{([a-z_]+)\}", entry["en"]))
        assert zh_ph == en_ph, f"{key} 占位符不一致: zh={zh_ph} en={en_ph}"


# ---------------------------------------------------------------------------
# 动态 wraplength 公式（P2：lbl_hint/lbl_warn 跟随窗口宽度）
# ---------------------------------------------------------------------------

def test_wraplength_scales_with_width():
    assert strings.wraplength_for(1000) == 840
    assert strings.wraplength_for(920) == 760


def test_wraplength_floor_at_400():
    # 最小窗 920 宽 → 760；更窄也不低于 400，防折行过碎
    assert strings.wraplength_for(500) == 400
    assert strings.wraplength_for(0) == 400
    assert strings.wraplength_for(-50) == 400


def test_wraplength_robust_to_non_int():
    assert strings.wraplength_for("1000") == 840
    assert strings.wraplength_for(None) == 400

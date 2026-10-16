# -*- coding: utf-8 -*-
"""字体令牌单测：守住 v2 统一字阶的契约，防止回退到 v1 的三个问题。

不 import tkinter —— 直接从 llama_ctl_gui 的模块级常量与源码文本断言。
覆盖：
- 六个语义层级齐备，且字号严格递减（层级可分辨）
- 卡片标题 / 折叠组头 / 日志开关 三个角色**不再共用一个令牌**
- 数值读数与正文同字号（消除行高错位）
- 不再出现裸字体字面量（必须走令牌）
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import llama_ctl_gui as g

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "llama_ctl_gui.py"), encoding="utf-8").read()


# ---------------------------------------------------------------------------
# 令牌本身
# ---------------------------------------------------------------------------

def test_all_tokens_defined():
    for name in ("F_DISPLAY", "F_SECTION", "F_GROUP", "F_BODY",
                 "F_SMALL", "F_MICRO", "F_MONO", "F_MONO_SM"):
        val = getattr(g, name, None)
        assert val is not None, f"缺字体令牌 {name}"
        assert isinstance(val, tuple) and len(val) >= 2, f"{name} 结构错: {val}"


def test_ui_tokens_share_one_family():
    """界面文字必须同一家族 —— 混家族是「不统一」的第一来源。"""
    fams = {getattr(g, n)[0] for n in
            ("F_DISPLAY", "F_SECTION", "F_GROUP", "F_BODY", "F_SMALL", "F_MICRO")}
    assert len(fams) == 1, f"界面令牌出现多家族: {fams}"


def test_mono_tokens_share_one_family():
    fams = {getattr(g, n)[0] for n in ("F_MONO", "F_MONO_SM")}
    assert len(fams) == 1, f"等宽令牌出现多家族: {fams}"


# ---------------------------------------------------------------------------
# 层级可分辨（v1 的核心缺陷）
# ---------------------------------------------------------------------------

def test_semantic_layers_are_strictly_distinct():
    """显示 > 卡片 > 组头 必须逐级变小，不能像 v1 那样组头与卡片同级。"""
    d = int(g.F_DISPLAY[1])
    s = int(g.F_SECTION[1])
    gr = int(g.F_GROUP[1])
    assert d > s > gr, f"层级未拉开的字号: display={d} section={s} group={gr}"


def test_group_header_is_bold_but_section_is_larger():
    """卡片与组头都用 bold，靠字号区分 —— 字号必须不同。"""
    assert g.F_SECTION[1] != g.F_GROUP[1], \
        "卡片标题与折叠组头仍同字号（v1 缺陷：两者都是 12 bold）"


def test_colliding_roles_now_use_different_tokens():
    """卡片标题 / 折叠组头 / 日志开关 三者在 v1 共用 F_GROUP，现必须分开。"""
    assert "font=F_SECTION" in SRC, "卡片标题未用 F_SECTION"
    assert re.search(r"text=self\._group_label\(g\),\s*font=F_GROUP", SRC), \
        "折叠组头未用 F_GROUP"
    assert 'text=t("log.collapsed"), font=F_BODY' in SRC, \
        "日志开关未脱离 F_GROUP"


def test_mono_matches_body_size():
    """数值读数与正文同字号 —— 修掉 v1 的 4px 行高错位。"""
    assert g.F_MONO[1] == g.F_BODY[1], \
        f"数值字号 {g.F_MONO[1]} != 正文字号 {g.F_BODY[1]}，行盒会错位"


def test_micro_is_smallest_ui_step():
    sizes = [g.F_DISPLAY[1], g.F_SECTION[1], g.F_GROUP[1], g.F_BODY[1],
             g.F_SMALL[1], g.F_MICRO[1]]
    assert sizes == sorted(sizes, reverse=True), f"字阶未单调递减: {sizes}"


# ---------------------------------------------------------------------------
# 无裸字面量（防绕开令牌）
# ---------------------------------------------------------------------------

def test_no_bare_font_literals():
    """font=( ... ) 里不得再出现裸字体名 —— 一律走令牌。"""
    bare = re.findall(r'font=\(\s*"[A-Za-z]', SRC)
    assert not bare, f"发现裸字体字面量 {len(bare)} 处，应改用令牌"


def test_mono_literal_family_is_declared_via_constant():
    assert '_MONO_FAMILY = "' in SRC, "等宽家族未经常量声明"


def test_status_dot_is_an_icon_not_a_font_character():
    """状态点必须是图标资产 —— v1 用字体字符 U+25CF，尺寸随字号漂移。"""
    assert "ic.tinted(" in SRC, "状态点未接入图标资产"
    assert 'text="' + chr(0x25CF) + '"' not in SRC, "状态点仍在用字体字符"

# -*- coding: utf-8 -*-
"""界面图标资产与装载测试。

守护三层:
  1. 资产层:每个 GLYPHS 名字都有 assets/icons/glyph_<name>.png,
     且为 72x144 双帧(左浅右深)、非空 alpha
  2. 装载层:icon.glyph() 按 (name,size,appearance) 返回 CTkImage 且缓存命中;
     chevron(open) 随开合切换;主题切换后缓存重建
  3. 接入层:llama_ctl_gui.py 必须引用 icon 模块(防误删),
     且不再使用 ▾/▸ 文字指示符
"""
import importlib
import importlib.util
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import make_icons as mk

ROOT = mk.ROOT


# ---------------------------------------------------------------------------
# 资产层
# ---------------------------------------------------------------------------
def test_all_glyph_assets_exist():
    from PIL import Image
    for name in mk.GLYPHS:
        p = os.path.join(mk.OUT_DIR, f"glyph_{name}.png")
        assert os.path.exists(p), f"缺资产 {p},跑 python make_icons.py 生成"
        im = Image.open(p)
        assert im.size == (144, 72), f"{name} 双帧尺寸错: {im.size}"


@pytest.mark.parametrize("name", sorted(mk.GLYPHS))
def test_both_frames_have_ink(name):
    """左右两帧都有内容,且颜色对应各自主题语义色。"""
    from PIL import Image
    import icon as ic
    light, dark = ic._load(name)
    for tag, fr in (("light", light), ("dark", dark)):
        a = fr.split()[3]
        assert a.getbbox() is not None, f"{name} {tag} 帧全透明"


def test_frames_differ_between_themes():
    """双主题色值不同的 glyph(如 dot-run 用 RUN 同色则跳过)至少 chevron/question 必须不同帧。"""
    from PIL import Image
    import icon as ic
    for name in ("chevron-down", "question", "trash"):
        light, dark = ic._load(name)
        lb, db = light.tobytes(), dark.tobytes()
        assert lb != db, f"{name} 浅深两帧相同,双主题色没生效"


# ---------------------------------------------------------------------------
# 装载层(需要 Tk 环境,仅 Windows 本机跑)
# ---------------------------------------------------------------------------
def _tk_available():
    try:
        import tkinter
        tkinter.Tk().destroy()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _tk_available(), reason="无显示环境")
def test_glyph_cache_and_theme_switch():
    import tkinter as tk
    import customtkinter as ctk
    import icon as ic

    root = ctk.CTk()
    root.withdraw()
    try:
        ic.set_appearance("light")
        a = ic.glyph("chevron-down", 14)
        assert a is not None and isinstance(a, ctk.CTkImage)
        assert ic.glyph("chevron-down", 14) is a, "缓存未命中"

        b = ic.glyph("chevron-down", 18)
        assert b is not a, "不同尺寸应返回不同实例"

        ic.set_appearance("dark")
        c = ic.glyph("chevron-down", 14)
        assert c is not None and c is not a, "主题切换后应重建"

        dn = ic.chevron(True)
        up = ic.chevron(False)
        assert dn is not None and up is not None
    finally:
        root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="无显示环境")
def test_missing_glyph_returns_none():
    import icon as ic
    assert ic.glyph("no-such-glyph", 14) is None


# ---------------------------------------------------------------------------
# 接入层
# ---------------------------------------------------------------------------
def _gui_src():
    return open(os.path.join(ROOT, "llama_ctl_gui.py"), encoding="utf-8").read()


def test_gui_imports_icon_module():
    src = _gui_src()
    assert "import icon as ic" in src


def test_gui_no_text_chevrons_left():
    """▾/▸ 文字指示符必须已被图标替换。"""
    src = _gui_src()
    assert "0x25BE" not in src and "0x25B8" not in src


def test_gui_group_button_uses_chevron_image():
    src = _gui_src()
    assert "image=ic.chevron(" in src, "组头按钮未接入 chevron 图标"


def test_gui_help_button_uses_question_glyph():
    src = _gui_src()
    assert 'ic.glyph("question"' in src, "? 帮助按钮未接入 question 图标"


def test_gui_trash_uses_glyph():
    src = _gui_src()
    assert 'ic.glyph("trash"' in src, "删除按钮未接入 trash 图标"


def test_gui_appearance_hook_calls_icon():
    src = _gui_src()
    assert "ic.set_appearance(resolved)" in src, "主题切换未同步图标缓存"


def test_spec_packs_icon_assets():
    """onefile 打包必须带上 assets/icons。"""
    spec = open(os.path.join(ROOT, "llama_ctl.spec"), encoding="utf-8").read()
    assert "assets/icons" in spec

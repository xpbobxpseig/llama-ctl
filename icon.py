# -*- coding: utf-8 -*-
"""运行时图标装载 —— 双主题双帧 PNG -> CTkImage。

资源约定(由 make_icons.py 生成,tests/test_icons_assets.py 守护):
assets/icons/glyph_<name>.png,72x144 RGBA,左 72x72 = 浅色主题帧,
右 72x72 = 深色主题帧,颜色为对应主题的语义色。

用法:
    from icon import glyph
    lbl = ctk.CTkLabel(parent, image=glyph("chevron-down", 14), text="")

    # 需要运行时换色的（状态点呼吸/闪烁）用 tinted：
    lbl.configure(image=tinted("dot-run", 14, "#0f7b3d"))

缓存按 (name, size, appearance) 记忆;主题切换经 set_appearance() 重建缓存。
tinted() 另有按 (name, size, 量化色) 的独立缓存 —— 状态点动效每帧换色，
不量化会让缓存无限增长。
"""
import os
import sys

import customtkinter as ctk
from PIL import Image


def _base():
    """资源基目录:frozen 时为 PyInstaller 解包目录,开发时为本文件目录。"""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return meipass
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


DIR = os.path.join(_base(), "assets", "icons")
FRAME = 72                      # 单帧边长(源 4x 超采样)
_cache = {}
_appearance = "light"
# tinted() 专用缓存：键含量化色，避免呼吸动效每帧产生新条目
_tint_cache = {}
_TINT_MAX = 64                  # 上限；超出即整体清空（动效帧复用率极高，抖动可忽略）


def _load(name):
    """读双帧 PNG -> (light_img, dark_img)。缺失返回 (None, None)。"""
    path = os.path.join(DIR, "glyph_%s.png" % name)
    if not os.path.exists(path):
        return None, None
    im = Image.open(path).convert("RGBA")
    if im.width != FRAME * 2 or im.height != FRAME:
        return None, None
    return (im.crop((0, 0, FRAME, FRAME)),
            im.crop((FRAME, 0, FRAME * 2, FRAME)))


def set_appearance(mode):
    """主题切换时调用:清缓存并记住当前外观("light"/"dark")。"""
    global _appearance
    _appearance = "dark" if str(mode).lower() == "dark" else "light"
    _cache.clear()
    _tint_cache.clear()


def appearance():
    return _appearance


def glyph(name, size):
    """取指定逻辑尺寸的 CTkImage(按当前外观选帧)。缺失时返回 None。"""
    key = (name, size, _appearance)
    hit = _cache.get(key)
    if hit is not None:
        return hit
    light, dark = _load(name)
    frame = dark if _appearance == "dark" else light
    if frame is None:
        return None
    img = ctk.CTkImage(light_image=frame, dark_image=frame, size=(size, size))
    _cache[key] = img
    return img


def _quantize(color):
    """把颜色量化到 5 位/通道 —— 动效插值的相邻帧会大量命中同一档。"""
    if isinstance(color, str):
        h = color.lstrip("#")
        rgb = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    else:
        rgb = tuple(color[:3])
    return tuple((c >> 3) << 3 for c in rgb)


def tinted(name, size, color):
    """按指定颜色重绘单色 glyph。

    用左帧(浅色主题帧)只取**形状与 alpha**，整色替换为目标色 ——
    故与当前主题无关，只取决于调用方给的颜色（状态点语义色由状态决定）。
    """
    if len(_tint_cache) > _TINT_MAX:
        _tint_cache.clear()
    key = (name, size, _quantize(color))
    hit = _tint_cache.get(key)
    if hit is not None:
        return hit
    light, _dark = _load(name)
    if light is None:
        return None
    if isinstance(color, str):
        h = color.lstrip("#")
        rgb = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    else:
        rgb = tuple(color[:3])
    # 以原帧 alpha 为蒙版，整体填充目标色（保留抗锯齿边缘与半透明外环）
    solid = Image.new("RGBA", light.size, rgb + (255,))
    solid.putalpha(light.split()[3])
    img = ctk.CTkImage(light_image=solid, dark_image=solid, size=(size, size))
    _tint_cache[key] = img
    return img


def chevron(open_):
    """组头展开指示:展开=chevron-down,收起=chevron-right。"""
    return glyph("chevron-down" if open_ else "chevron-right", 13)

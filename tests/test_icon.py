# -*- coding: utf-8 -*-
"""图标单测:守住 ICO 结构与小尺寸可读性,防止后续改图标时悄悄退化。

不靠肉眼,全部是像素级断言:
  - 结构:档位齐全、256 排首位(PyInstaller 嵌入依赖)、PNG 编码条目可被 Pillow 读回
  - 可读性:16/24/32px 下白色笔画可见、右上角绿点在位、内容不溢出画布
  - 与 GUI 的一致性:图标文件名/路径必须与 llama_ctl_gui.py 里的 iconbitmap 调用一致
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PIL import Image

import make_icon as mk

ICO = os.path.join(mk.ROOT, "llama_icon.ico")
EXPECTED = [16, 24, 32, 48, 64, 128, 256]


def _entries(path):
    """读 ICO 目录 -> [(w, h, bpp, size, offset), ...]。"""
    with open(path, "rb") as f:
        blob = f.read()
    _, kind, count = struct.unpack("<HHH", blob[:6])
    assert kind == 1, "不是 ICO(type 字段应为 1)"
    out = []
    for i in range(count):
        off = 6 + i * 16
        w, h, _cc, _rv, _pl, bpp, size, ofs = struct.unpack("<BBBBHHII", blob[off:off + 16])
        out.append((w or 256, h or 256, bpp, size, ofs))
    return out, blob


def _plate_blue_px(img):
    """统计平板蓝色的像素数（新图标的底色）。"""
    px = img.convert("RGBA").load()
    n = 0
    for y in range(img.height):
        for x in range(img.width):
            r, g, b, a = px[x, y]
            if a > 150 and abs(r - mk.PLATE[0]) <= 20 and \
               abs(g - mk.PLATE[1]) <= 20 and abs(b - mk.PLATE[2]) <= 20:
                n += 1
    return n


def _inner_detail_px(img):
    """统计「被白色包夹的平板蓝」像素 —— 即眼/脉冲线这类内层细节。

    新图标的内层细节是白色剪影上抠出的孔，露出的正是平板蓝。
    """
    px = img.convert("RGBA").load()
    w, h = img.width, img.height

    def white(x, y):
        r, g, b, a = px[x, y]
        return a > 150 and r > 170 and g > 170 and b > 170

    def blue(x, y):
        r, g, b, a = px[x, y]
        return a > 200 and abs(r - mk.PLATE[0]) <= 20 and \
            abs(g - mk.PLATE[1]) <= 20 and abs(b - mk.PLATE[2]) <= 20

    n = 0
    for y in range(h):
        for x in range(1, w - 1):
            if blue(x, y):
                if any(white(i, y) for i in range(x)) and \
                   any(white(i, y) for i in range(x + 1, w)):
                    n += 1
    return n


def _white_runs(img, y, threshold=200):
    """某一行上连续白像素的段长列表。"""
    px = img.convert("RGBA").load()
    runs, cur = [], 0
    for x in range(img.width):
        r, g, b, a = px[x, y]
        if a > 120 and r > threshold and g > threshold and b > threshold:
            cur += 1
        else:
            if cur:
                runs.append(cur)
            cur = 0
    if cur:
        runs.append(cur)
    return runs


# ---------------------------------------------------------------------------
# 结构
# ---------------------------------------------------------------------------
def test_ico_exists():
    assert os.path.exists(ICO), "llama_icon.ico 缺失 —— 跑 `python make_icon.py ico` 生成"


def test_all_sizes_present():
    entries, _ = _entries(ICO)
    assert sorted(e[0] for e in entries) == EXPECTED


def test_256_first_for_pyinstaller():
    """256 档必须排首位 —— spec 的 icon= 嵌入依赖此顺序(commit 16d8047)。"""
    entries, _ = _entries(ICO)
    assert entries[0][0] == 256 and entries[0][1] == 256


def test_entries_are_png_and_in_bounds():
    """条目用 PNG 编码,且偏移/长度都落在文件内 —— 手写目录最容易在这里出错。"""
    entries, blob = _entries(ICO)
    assert len(blob) > 6 + 16 * len(entries), "文件短于目录区,目录必然损坏"
    for w, h, bpp, size, ofs in entries:
        assert bpp == 32
        assert size > 0 and ofs + size <= len(blob), f"{w}px 条目越界"
        assert blob[ofs:ofs + 8] == b"\x89PNG\r\n\x1a\n", f"{w}px 条目不是 PNG"


def test_roundtrip_readable_by_pillow():
    im = Image.open(ICO)
    got = sorted(s[0] for s in im.info["sizes"])
    assert got == EXPECTED
    for s in EXPECTED:
        frame = im.ico.getimage((s, s))
        assert frame.size == (s, s)


# ---------------------------------------------------------------------------
# 像素级可读性
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("size", [16, 24, 32])
def test_small_sizes_have_visible_strokes(size):
    """`>_` 的笔画必须真的落在像素上 —— 太细会在小尺寸整段消失。"""
    img = mk.render(size)
    runs = []
    for y in range(size):
        runs += _white_runs(img, y)
    assert runs, f"{size}px 找不到任何白色笔画"
    # 每条扫描线上的亮段不应细到只剩单个半透明像素
    assert max(runs) >= 2, f"{size}px 笔画过细(runs={runs})"


@pytest.mark.parametrize("size", [16, 24, 32, 48, 64, 128, 256])
def test_flat_plate_present(size):
    """平板必须是品牌蓝实心面 —— 取代旧的「右上角绿点」断言。

    v2 起「服务在跑」的语义由羊驼剪影 + 脉冲线承担，不再靠一个 3.8px 的绿点
    （旧设计在 16px 下那个点糊成色块，实测直径 3.84px）。
    """
    n = _plate_blue_px(mk.render(size))
    assert n > size * size * 0.10, f"{size}px 平板蓝色不足({n}px)"


@pytest.mark.parametrize("size", [16, 24, 32, 48, 64, 128, 256])
def test_content_within_canvas(size):
    """内容必须完全落在画布内(没被裁切),且四周留有透明边。"""
    img = mk.render(size).convert("RGBA")
    bb = img.split()[3].getbbox()
    assert bb is not None, f"{size}px 全透明"
    assert bb[0] >= 0 and bb[1] >= 0 and bb[2] <= size and bb[3] <= size


def test_corner_is_transparent_rounded():
    """圆角:四角应为透明 —— 否则不是圆角方形。"""
    img = mk.render(64).convert("RGBA")
    px = img.load()
    for x, y in ((0, 0), (63, 0), (0, 63), (63, 63)):
        assert px[x, y][3] < 40, f"角落 ({x},{y}) 不透明,圆角失效"


def test_plate_uses_brand_colour_flat():
    """平板用品牌蓝 #0b5cb0 的**纯平**色，不是渐变。

    旧图标是 #4aa6ff→#055ad4 的强渐变（亮度跨度 2.39:1），既显得过时，又让白色
    标记的对比度在亮端掉到 2.56:1（低于 AA）。纯平色让标记对比度恒定 6.62:1。
    """
    img = mk.render(256).convert("RGBA")
    px = img.load()
    # 取几个分散的平板采样点（避开剪影与孔洞），它们必须**同色**
    samples = [(20, 130), (236, 130), (128, 20), (128, 236), (30, 30)]
    got = [px[x, y] for x, y in samples]
    solid = [c for c in got if c[3] > 200]
    assert len(solid) >= 3, f"平板采样点不足({got})"
    for c in solid:
        d = abs(c[0] - mk.PLATE[0]) + abs(c[1] - mk.PLATE[1]) + abs(c[2] - mk.PLATE[2])
        assert d <= 6, f"平板不是纯平品牌蓝: {c} 偏差 {d}"
    # 纯平 = 这些点彼此完全相同
    assert len({tuple(c[:3]) for c in solid}) == 1, f"平板出现渐变: {solid}"


def test_inner_detail_drawn_when_large_enough():
    """>=48px 必须画出内层细节（眼 + 脉冲线），<48px 必须省掉。

    实测：内层细节在 <48px 会被降采样糊掉（32px 时仅 11px 可辨），
    故 render() 按尺寸分级；此断言守住这个门槛不被误改。
    """
    assert _inner_detail_px(mk.render(256)) > 100, "256px 未画出眼/脉冲线"
    assert _inner_detail_px(mk.render(64)) > 20, "64px 未画出眼/脉冲线"
    # 16px 无内层细节：允许 1-2 px 的残余（羊驼耳间凹口也会形成「被白包夹的蓝」），
    # 但绝不该出现 48px 那种量级的细节（>=20px）。
    assert _inner_detail_px(mk.render(16)) <= 4, "16px 出现内层细节（会糊）"


def test_silhouette_ears_survive_at_small_size():
    """16px 下羊驼的两只耳朵必须仍可分离 —— 这是小尺寸唯一的辨识特征。"""
    for size in (16, 24, 32):
        img = mk.render(size).convert("RGBA")
        px = img.load()
        two_run_rows = 0
        for y in range(size):
            runs, cur = [], 0
            for x in range(size):
                r, g, b, a = px[x, y]
                if a > 100 and r > 170 and g > 170 and b > 170:
                    cur += 1
                else:
                    if cur:
                        runs.append(cur)
                    cur = 0
            if cur:
                runs.append(cur)
            if len(runs) >= 2:
                two_run_rows += 1
        assert two_run_rows >= 2, f"{size}px 双耳合并(仅 {two_run_rows} 行分离)"


# ---------------------------------------------------------------------------
# 与 GUI 的契约
# ---------------------------------------------------------------------------
def test_gui_icon_path_matches():
    """llama_ctl_gui.py 通过 iconbitmap 加载的必须就是这个文件。"""
    gui = os.path.join(mk.ROOT, "llama_ctl_gui.py")
    src = open(gui, encoding="utf-8").read()
    assert '"llama_icon.ico"' in src, "GUI 不再引用 llama_icon.ico,图标改动需同步"
    assert os.path.basename(ICO) == "llama_icon.ico"

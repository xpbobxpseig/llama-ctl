# -*- coding: utf-8 -*-
"""llama_ctl 界面图标生成器 —— OD 图标库（Phosphor）双主题双帧输出。

规范 v3（依据 docs/design/icon-replacement-plan.md 已确认口径）:
  - 形状来源 = **Phosphor Icons**（OD 图标库数据源）**bold** 字重
    vendored 于 assets/phosphor/bold/，MIT 许可（assets/phosphor/LICENSE.txt）
  - 输出格式不变：72x144 双帧 PNG（左帧浅色主题色 / 右帧深色主题色）
  - 网格口径统一到 Phosphor 的 256 viewBox，缩放到本项目的 72px 帧
  - 状态点策略 B：dot-run / dot-stop 保留自绘（纯几何形状，非图标家族成员）；
    dot-error → warning-circle、dot-dirty → circle-dashed 改用 Phosphor

为什么选 bold（实测）:
  现有自绘 glyph 的墨迹覆盖率 ≈ Phosphor bold（当前/bold = 1.18×，
  当前/regular = 1.50×）；本项目渲染尺寸 13/14/18px 低于 regular 的设计意图区间
  （OD 示例多为 20–24px）。故 bold 才能保持现有清晰度。

用法:
    python make_icons.py            # 输出 assets/icons/*.png
    python make_icons.py preview    # 额外输出 Temp/icon-preview/glyphs_*.png

改图标:调 GLYPHS 的 (来源, 颜色键) 映射;tests/test_icons_assets.py 会守住
双帧结构、双帧有墨迹、浅深两帧色值不同。
"""
import os
import re
import sys

from PIL import Image, ImageDraw

import svgpath

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(ROOT, "assets", "icons")
PHOSPHOR_DIR = os.path.join(ROOT, "assets", "phosphor", "bold")
PREVIEW = os.path.join(ROOT, "Temp", "icon-preview")

# 双主题语义色（与 llama_ctl_gui.PALETTES 的可访问色值一致）
THEME = {
    "light": {"TXT": "#18181b", "MUT": "#5f5f66", "ACC": "#0b5cb0",
              "RED": "#c2261c", "ORG": "#9a5b00", "RUN": "#0f7b3d",
              "STOP": "#5f5f66"},
    "dark": {"TXT": "#f4f4f5", "MUT": "#8e8e97", "ACC": "#4da3ff",
             "RED": "#ff6b61", "ORG": "#fbbf24", "RUN": "#4ade80",
             "STOP": "#8e8e97"},
}

FRAME = 72          # 输出帧边长（px）
SS = 8              # 栅格化超采样倍数
VIEW = 256.0        # Phosphor viewBox 边长

# 尺寸口径：**不做逐图标归一化**，直接用 Phosphor 自己的 viewBox 比例渲染。
# 实测（14 槽位对比）Phosphor bold 的原生光学尺寸已与旧自绘图标吻合到几个百分点：
#   question 84.4% vs 旧 83.3%、trash 85.9% vs 80.6%、arrow-right 78.1% vs 76.4%、
#   restart 84.4% vs 86.1%、dot-error 84.4% vs 83.3%。
# 若强行归一到统一比例（曾试 TARGET_INK=0.72），反而会把 question/restart/dot-error
# 缩小 8–14%，破坏原有观感。故保留库的原生留白，只对齐「同一行相邻」的两处：
#   1) 两个自绘状态点跟上 Phosphor 圆形的 84.4% 外径（四个状态点同排，必须等大）；
#   2) caret 系列彼此同族，天然等大。
DOT_INK = 0.844     # 自绘状态点外径占帧比例（对齐 Phosphor 圆形的原生外接尺寸）
DOT_RING_ALPHA = 0.38   # 光环透明度（沿用旧观感）


def _hx(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


# ---------------------------------------------------------------- Phosphor 读取
_svg_cache = {}


def load_phosphor(name):
    """读 assets/phosphor/bold/<name>-bold.svg 的 path d。缺失返回 None。"""
    if name in _svg_cache:
        return _svg_cache[name]
    path = os.path.join(PHOSPHOR_DIR, f"{name}-bold.svg")
    d = None
    if os.path.exists(path):
        m = re.search(r'd="([^"]+)"', open(path, encoding="utf-8").read())
        d = m.group(1) if m else None
    _svg_cache[name] = d
    return d


def _render_phosphor(d, size, ss=SS):
    """把 Phosphor path 按库原生 viewBox 比例栅格化为 size×size 蒙版。

    不做归一化：scale = size/view、offset = 0，即照搬 Phosphor 在 256 网格里的
    原生留白与视觉重心（理由见文件头 DOT_INK 处的实测说明）。
    """
    if not svgpath.parse_path(d):
        return Image.new("L", (size, size), 0)
    return svgpath.render_mask(d, size, ss=ss, view=VIEW)


# ---------------------------------------------------------------- 自绘状态点（策略 B 保留）
def _dot_run(mask_draw, size, ss):
    """运行中：实心核 + 半透明光环（保留自绘，理由见模块 docstring）。"""
    k = size * ss
    ink = DOT_INK
    cx = cy = k / 2.0
    r_core = (ink * 0.30) * k
    r_ring = (ink * 0.50) * k
    w_ring = (ink * 0.145) * k
    mask_draw.ellipse([cx - r_core, cy - r_core, cx + r_core, cy + r_core], fill=255)
    a = int(round(255 * DOT_RING_ALPHA))
    mask_draw.ellipse([cx - r_ring, cy - r_ring, cx + r_ring, cy + r_ring],
                      outline=a, width=max(1, int(round(w_ring))))


def _dot_stop(mask_draw, size, ss):
    """已停止：方核 + 方环（保留自绘）。"""
    k = size * ss
    ink = DOT_INK
    cx = cy = k / 2.0
    half_core = (ink * 0.21) * k
    half_ring = (ink * 0.50) * k
    w_ring = (ink * 0.145) * k
    mask_draw.rounded_rectangle(
        [cx - half_core, cy - half_core, cx + half_core, cy + half_core],
        radius=(ink * 0.06) * k, fill=255)
    a = int(round(255 * DOT_RING_ALPHA))
    mask_draw.rounded_rectangle(
        [cx - half_ring, cy - half_ring, cx + half_ring, cy + half_ring],
        radius=(ink * 0.10) * k, outline=a, width=max(1, int(round(w_ring))))


# ---------------------------------------------------------------- glyph 定义
# 值 = ("ph", phosphor 名, 颜色键)  或  ("draw", 绘制函数, 颜色键)
GLYPHS = {
    # --- 原 4 个功能图标 → Phosphor bold ---
    "chevron-down":  ("ph", "caret-down",    "MUT"),
    "chevron-right": ("ph", "caret-right",   "MUT"),
    "chevron-up":    ("ph", "caret-up",      "MUT"),
    "question":      ("ph", "question",      "MUT"),
    "trash":         ("ph", "trash",         "RED"),
    # --- 原死资源 6 个 → Phosphor bold（保持资源名不变）---
    "close":         ("ph", "x",             "TXT"),
    "arrow-right":   ("ph", "arrow-right",   "TXT"),
    "play":          ("ph", "play",          "RUN"),
    "stop":          ("ph", "stop",          "RED"),
    "restart":       ("ph", "arrow-clockwise", "ACC"),
    # --- 状态点：策略 B ---
    "dot-error":     ("ph", "warning-circle", "RED"),
    "dot-dirty":     ("ph", "circle-dashed",  "ORG"),
    "dot-run":       ("draw", _dot_run,       "RUN"),
    "dot-stop":      ("draw", _dot_stop,      "STOP"),
}


def render_glyph(name, theme):
    """渲染单帧（FRAME px）的 RGBA 图：形状取自蒙版，整体填充主题色。"""
    spec = GLYPHS[name]
    color = _hx(THEME[theme][spec[2]])
    if spec[0] == "ph":
        d = load_phosphor(spec[1])
        if d is None:
            return None
        mask = _render_phosphor(d, FRAME, ss=SS)
    else:
        n = FRAME * SS
        mask = Image.new("L", (n, n), 0)
        spec[1](ImageDraw.Draw(mask), FRAME, SS)
        mask = mask.resize((FRAME, FRAME), Image.BOX)
    out = Image.new("RGBA", (FRAME, FRAME), color + (255,))
    out.putalpha(mask)
    return out


def save_dual(name):
    """输出 72x144 双帧 PNG：左浅右深。"""
    light = render_glyph(name, "light")
    dark = render_glyph(name, "dark")
    if light is None or dark is None:
        raise RuntimeError(f"glyph {name} 无法渲染（缺 Phosphor 源文件？）")
    out = Image.new("RGBA", (FRAME * 2, FRAME), (0, 0, 0, 0))
    out.paste(light, (0, 0))
    out.paste(dark, (FRAME, 0))
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"glyph_{name}.png")
    out.save(path)
    return path


def _preview():
    os.makedirs(PREVIEW, exist_ok=True)
    names = sorted(GLYPHS)
    row, pad = FRAME + 26, 26
    W = pad * 2 + FRAME * 2 + 190
    H = pad * 2 + row * len(names)
    sheet = Image.new("RGB", (W, H), (245, 245, 247))
    y = pad
    for n in names:
        img = render_glyph(n, "light")
        sheet.paste(img, (pad, y + 3), img)
        img = render_glyph(n, "dark")
        sheet.paste(img, (pad + FRAME + 12, y + 3), img)
        x = pad + FRAME * 2 + 26
        for sz in (14, 18, 24):
            sm = render_glyph(n, "light").resize((sz, sz), Image.LANCZOS)
            sheet.paste(sm, (x, y + 3 + (24 - sz)), sm)
            x += sz + 10
        y += row
    sheet.save(os.path.join(PREVIEW, "glyphs_light.png"))

    sheet2 = Image.new("RGB", (W, H), (30, 30, 32))
    y = pad
    for n in names:
        img = render_glyph(n, "dark")
        sheet2.paste(img, (pad, y + 3), img)
        x = pad + FRAME + 26
        for sz in (14, 18, 24):
            sm = render_glyph(n, "dark").resize((sz, sz), Image.LANCZOS)
            sheet2.paste(sm, (x, y + 3 + (24 - sz)), sm)
            x += sz + 10
        y += row
    sheet2.save(os.path.join(PREVIEW, "glyphs_dark.png"))
    print("preview ->", PREVIEW)


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else ""
    for n in GLYPHS:
        save_dual(n)
    if what == "preview":
        _preview()


if __name__ == "__main__":
    main()

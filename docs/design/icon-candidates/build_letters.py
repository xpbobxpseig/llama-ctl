#!/usr/bin/env python3
"""Letter-mark icon candidates — drafts only, nothing lands in the app.

The mark is built from the KEY LETTERS of "llama.cpp", and the color
proportions follow the interface: ink tile >= 85%, paper letterform <= 13%,
forest-green accent <= 5% (the UI is monochrome with tiny green accents —
never a green field).

Outputs:
  docs/design/icon-candidates/<id>-*.svg      master vector per candidate
  <viz-dir>/icon-candidates.html              preview fragment

Run:  python docs/design/icon-candidates/build_letters.py
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
CAND_DIR = Path(__file__).resolve().parent
VIZ = Path(r"C:\Users\Administrator\.zcode\v2\visualizations\4cee31a4be9881f89ae7ffc6450cac8e621add652ae43a96a97386fe216f8b71")

INK = "#1B1917"
PAPER = "#F6F3EE"
FOREST = "#1F6B58"
MINT = "#6EC9A8"
RGB = {"#1B1917": (27, 25, 23), "#F6F3EE": (246, 243, 238), "#1F6B58": (31, 107, 88), "#6EC9A8": (110, 201, 168)}

TILE_R = 56
SS = 8


# ── shared Pillow helpers (draw at 8x, downscale) ────────────────────────────

def canvas():
    big = 256 * SS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img), big / 256


def rr(d, k, box, radius, fill):
    x0, y0, x1, y1 = [v * k for v in box]
    d.rounded_rectangle((x0, y0, x1, y1), radius=radius * k, fill=fill)


def circle(d, k, cx, cy, r, fill):
    d.ellipse(((cx - r) * k, (cy - r) * k, (cx + r) * k, (cy + r) * k), fill=fill)


def bez(p0, p1, p2, p3, n=32):
    pts = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        pts.append(
            (
                u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0],
                u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1],
            )
        )
    return pts


def stroke_path(d, k, segs, color, width):
    pts = []
    for s in segs:
        pts.extend(bez(*s)[1:] if pts else bez(*s))
    d.line([(x * k, y * k) for x, y in pts], fill=color, width=int(width * k), joint="curve")
    for cap in (pts[0], pts[-1]):  # round caps
        circle(d, k, cap[0], cap[1], width / 2, color)


# ── the five candidates ──────────────────────────────────────────────────────

# ℓ: leg up, loop left, back to the leg — one calligraphic stroke.
ELL_SEGMENTS = [
    ((168, 196), (154, 150), (142, 100), (136, 64)),
    ((136, 64), (132, 44), (112, 34), (96, 44)),
    ((96, 44), (80, 54), (84, 76), (104, 80)),
    ((104, 80), (114, 82), (124, 74), (130, 60)),
]
ELL_EYE = (113, 61, 7)
ELL_SVG = (
    "M168,196 C154,150 142,100 136,64 "
    "C132,44 112,34 96,44 "
    "C80,54 84,76 104,80 "
    "C114,82 124,74 130,60"
)
# lc: the c opens right and cradles nothing; the green l stands in its mouth.
C_ARC = dict(cx=118, cy=128, r=74, a0=42, a1=318)


def cand_ll():
    def draw():
        img, d, k = canvas()
        rr(d, k, (0, 0, 256, 256), TILE_R, RGB[INK])
        rr(d, k, (54, 60, 98, 196), 22, RGB[PAPER])
        rr(d, k, (118, 60, 162, 196), 22, RGB[PAPER])
        circle(d, k, 196, 180, 16, RGB[FOREST])
        return img

    svg = (
        f'<rect width="256" height="256" rx="{TILE_R}" fill="{INK}"/>'
        '<rect x="54" y="60" width="44" height="136" rx="22" fill="' + PAPER + '"/>'
        '<rect x="118" y="60" width="44" height="136" rx="22" fill="' + PAPER + '"/>'
        f'<circle cx="196" cy="180" r="16" fill="{FOREST}"/>'
    )
    return draw, svg


def cand_ell():
    ex, ey, er = ELL_EYE
    def draw():
        img, d, k = canvas()
        rr(d, k, (0, 0, 256, 256), TILE_R, RGB[INK])
        stroke_path(d, k, ELL_SEGMENTS, RGB[PAPER], 20)
        circle(d, k, ex, ey, er, RGB[MINT])
        return img

    svg = (
        f'<rect width="256" height="256" rx="{TILE_R}" fill="{INK}"/>'
        f'<path d="{ELL_SVG}" fill="none" stroke="{PAPER}" stroke-width="20" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="{ex}" cy="{ey}" r="{er}" fill="{MINT}"/>'
    )
    return draw, svg


def cand_la():
    def draw():
        img, d, k = canvas()
        rr(d, k, (0, 0, 256, 256), TILE_R, RGB[INK])
        rr(d, k, (74, 52, 110, 196), 18, RGB[PAPER])
        # bowl: ring centered on r=30, stroke 32 → outer 110..202, counter r14
        circle(d, k, 156, 150, 46, RGB[PAPER])
        circle(d, k, 156, 150, 14, RGB[INK])
        circle(d, k, 156, 150, 7, RGB[FOREST])
        return img

    # SVG: ring via stroked circle (no evenodd needed).
    svg = (
        f'<rect width="256" height="256" rx="{TILE_R}" fill="{INK}"/>'
        f'<rect x="74" y="52" width="36" height="144" rx="18" fill="{PAPER}"/>'
        f'<circle cx="156" cy="150" r="30" fill="none" stroke="{PAPER}" stroke-width="32"/>'
        f'<circle cx="156" cy="150" r="7" fill="{FOREST}"/>'
    )
    return draw, svg


def cand_lc():
    import math

    def draw():
        img, d, k = canvas()
        rr(d, k, (0, 0, 256, 256), TILE_R, RGB[PAPER])
        d.rounded_rectangle((5 * k, 5 * k, 251 * k, 251 * k), radius=(TILE_R - 5) * k, outline=(27, 25, 23, 70), width=int(5 * k))
        cx, cy, r, w = C_ARC["cx"], C_ARC["cy"], C_ARC["r"], 40
        # Pillow draws the arc band inward from the bbox; give it the OUTER
        # radius so the check matches the SVG (stroke centered on r).
        ro = r + w / 2
        d.arc(((cx - ro) * k, (cy - ro) * k, (cx + ro) * k, (cy + ro) * k), start=C_ARC["a0"], end=C_ARC["a1"], fill=RGB[INK], width=int(w * k))
        for a in (C_ARC["a0"], C_ARC["a1"]):
            px = cx + r * math.cos(math.radians(a))
            py = cy + r * math.sin(math.radians(a))
            circle(d, k, px, py, w / 2, RGB[INK])
        rr(d, k, (204, 84, 232, 172), 14, RGB[FOREST])
        return img

    x0 = round(C_ARC["cx"] + C_ARC["r"] * 0.7431448254773942, 1)  # cos 42°
    y0 = round(C_ARC["cy"] - C_ARC["r"] * 0.6691306063522576, 1)  # sin 42°
    y1 = round(C_ARC["cy"] + C_ARC["r"] * 0.6691306063522576, 1)
    svg = (
        f'<rect width="256" height="256" rx="{TILE_R}" fill="{PAPER}"/>'
        f'<rect x="5" y="5" width="246" height="246" rx="{TILE_R - 5}" fill="none" '
        f'stroke="{INK}" stroke-opacity="0.28" stroke-width="5"/>'
        f'<path d="M{x0},{y0} A{C_ARC["r"]},{C_ARC["r"]} 0 1 0 {x0},{y1}" fill="none" '
        f'stroke="{INK}" stroke-width="40" stroke-linecap="round"/>'
        f'<rect x="204" y="84" width="28" height="88" rx="14" fill="{FOREST}"/>'
    )
    return draw, svg


def cand_l_slider():
    def draw():
        img, d, k = canvas()
        rr(d, k, (0, 0, 256, 256), TILE_R, RGB[INK])
        rr(d, k, (70, 56, 112, 196), 21, RGB[PAPER])
        rr(d, k, (70, 154, 186, 196), 21, RGB[PAPER])
        circle(d, k, 150, 175, 15, RGB[FOREST])
        return img

    svg = (
        f'<rect width="256" height="256" rx="{TILE_R}" fill="{INK}"/>'
        '<rect x="70" y="56" width="42" height="140" rx="21" fill="' + PAPER + '"/>'
        '<rect x="70" y="154" width="116" height="42" rx="21" fill="' + PAPER + '"/>'
        f'<circle cx="150" cy="175" r="15" fill="{FOREST}"/>'
    )
    return draw, svg


CANDIDATES = [
    ("a", "ll. 双柱", "llama 的压缩：双 l 柱 + 基线绿点——点既是 llama.cpp 的分隔点，也是界面的状态点。", cand_ll),
    ("b", "ℓ 单笔", "script-l 的颈项轮廓，一笔写成；环眼里一颗薄荷绿点，是颈部与头的暗示。", cand_ell),
    ("c", "la 合字", "llama 的头两个字母连成一字：长杆加 a 环，环心一颗绿点。", cand_la),
    ("d", "lc 环抱", "纸砖上墨色 c（console / cpp）环抱森林绿的 l（llama）——控制台托管服务。浅色主题比例。", cand_lc),
    ("e", "L 滑轨", "L 的横笔是一根滑轨、绿点是滑块——字母即界面本身的参数滑杆。", cand_l_slider),
]


# ── ASCII check ──────────────────────────────────────────────────────────────

def ascii_check(img, size=64):
    im = img.resize((size, size), Image.LANCZOS)
    px = im.load()
    rows = []
    for y in range(size):
        row = ""
        for x in range(size):
            r, g, b, a = px[x, y]
            if a < 128:
                row += "."
                continue
            l = 0.2126 * r + 0.7152 * g + 0.0722 * b
            if l > 200:
                row += "#"
            elif g > 120 and g > r + 40:  # greenish
                row += "G"
            elif l < 60:
                row += "@"
            else:
                row += "+"
        rows.append(row)
    return rows


# ── page ─────────────────────────────────────────────────────────────────────

PAGE = """<div id="icon-candidates">
<style>
#icon-candidates { font-size: var(--font-size-base); color: var(--foreground); }
#icon-candidates .cand { margin: 0 0 4px; }
#icon-candidates .cand-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin: 14px 0 8px; }
#icon-candidates .tag {
  display: inline-flex; align-items: center; justify-content: center;
  width: 22px; height: 22px; border-radius: 6px; flex: none;
  background: var(--primary); color: var(--primary-foreground);
  font-size: 12px; font-weight: 500; align-self: center;
}
#icon-candidates .why { color: var(--muted-foreground); }
#icon-candidates .ratio { color: var(--muted-foreground); font-size: 12px; }
#icon-candidates .strips { display: flex; flex-wrap: wrap; gap: 10px; }
#icon-candidates .strip {
  display: flex; align-items: center; gap: 18px;
  padding: 14px 18px; border-radius: 10px; flex: 1 1 260px; min-height: 128px;
}
#icon-candidates .strip.light { background: #F3F3F3; }
#icon-candidates .strip.dark { background: #202020; }
#icon-candidates .strip svg { display: block; }
#icon-candidates .strip .main { width: 96px; height: 96px; }
#icon-candidates .hint { color: var(--muted-foreground); margin-top: 14px; }
</style>
<h1>字母图案候选 · llama-ctl</h1>
<p class="text-muted">关键字母构成图案；配色比例照界面：墨色砖面 ≥ 85%，纸色字形 ≤ 13%，森林绿只做 ≤ 5% 的点睛（界面正是墨纸为主、绿只点缀）。定稿前不落地。回复编号或组合修改意见。</p>
<!--SECTIONS-->
<p class="hint">每条候选在浅色 / 深色两种任务栏底色上各显示 96 / 32 / 16 px。矢量稿在 docs/design/icon-candidates/。</p>
</div>"""

SECTION = """<section class="cand">
  <div class="cand-head"><span class="tag">{id}</span><b>{name}</b><span class="why">{why}</span></div>
  <div class="strips">
    <div class="strip light">{light}</div>
    <div class="strip dark">{dark}</div>
  </div>
</section>"""


def sized(svg: str) -> str:
    main = svg.replace("<svg ", '<svg width="96" height="96" ', 1)
    out = ['<span class="main">' + main + "</span>"]
    for s in (32, 16):
        out.append(svg.replace("<svg ", f'<svg width="{s}" height="{s}" ', 1))
    return "".join(out)


def main() -> None:
    CAND_DIR.mkdir(parents=True, exist_ok=True)
    sections = []
    for cid, name, why, factory in CANDIDATES:
        draw, svg_body = factory()
        # ASCII check before anything ships to the page.
        rows = ascii_check(draw())
        print(f"--- {cid} {name} ---")
        for r in rows:
            print(r)
        doc = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">{svg_body}</svg>'
        (CAND_DIR / f"{cid}-{name.split(' ')[0]}.svg").write_text(doc, encoding="utf-8")
        sections.append(SECTION.format(id=cid.upper(), name=name, why=why, light=sized(doc), dark=sized(doc)))
    VIZ.mkdir(parents=True, exist_ok=True)
    (VIZ / "icon-candidates.html").write_text(
        PAGE.replace("<!--SECTIONS-->", "".join(sections)), encoding="utf-8"
    )
    print("preview ->", VIZ / "icon-candidates.html")


if __name__ == "__main__":
    main()

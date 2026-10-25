#!/usr/bin/env python3
"""Generate the llama-ctl app icon — the user's final design.

The mark (authored by the user as SVG, this script is its raster half):

  tile    #18181B rounded square (inset 16, rx 52) with a #27272A hairline
  bracket 1  #A1A1AA — abstract left ear / back bracket
  bracket 2  #F4F4F5 — abstract right ear / face bracket

WITH_PLUSES adds the rose-gradient C++ double-plus node pair. Default OFF:
the user's reference render does not show them (the original SVG's
objectBoundingBox gradient is undefined on zero-area <line> elements, so
their viewer dropped the group). When enabled, the gradient is applied
cluster-wide (userSpaceOnUse, 102,136 → 130,160) so every renderer paints it.

Outputs (one geometry, no drift):

  src-tauri/icons/llama_icon.ico   256/128/64/48/32/24/16 (PNG-compressed)
  llama_icon.ico                   root copy (retired spec keeps matching)
  docs/design/app-icon.svg         master vector
  docs/design/app-icon-preview.png light/dark rows across sizes

Small entries (≤32 px) widen the strokes slightly — 14/256 is sub-pixel at
16 px and would smear; the design intent is unchanged at ≥48 px.

Run:  python scripts/make_icon.py
Requires: Pillow.
"""

from __future__ import annotations

import base64
import io
import struct
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]

WITH_PLUSES = False

TILE_FILL = (24, 24, 27, 255)      # #18181B
TILE_EDGE = (39, 39, 42, 255)      # #27272A
BRACKET_DIM = (161, 161, 170, 255)  # #A1A1AA
BRACKET_LIT = (244, 244, 245, 255)  # #F4F4F5
GRAD_A = (244, 63, 94, 255)        # #F43F5E
GRAD_B = (251, 113, 133, 255)      # #FB7185

SS = 8
# The plusses' gradient axis = their cluster bbox, userSpaceOnUse.
G0 = (102.0, 136.0)
G1 = (130.0, 160.0)

LEFT_BRACKET = [(104, 62), (80, 110), (80, 190)]
RIGHT_BRACKET = [(142, 52), (122, 104), (168, 128), (168, 152), (138, 152), (138, 190)]
PLUS_LINES = [
    ((102, 142), (114, 142)),
    ((108, 136), (108, 148)),
    ((118, 154), (130, 154)),
    ((124, 148), (124, 160)),
]


def grad_color(t: float):
    t = max(0.0, min(1.0, t))
    return tuple(round(a + (b - a) * t) for a, b in zip(GRAD_A, GRAD_B))


def render(size: int, stroke: float, plus: float) -> Image.Image:
    """One icon bitmap at `size` (drawn at SSx, LANCZOS down)."""
    big = size * SS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    k = big / 256.0

    d.rounded_rectangle(
        (16 * k, 16 * k, 240 * k, 240 * k),
        radius=52 * k,
        fill=TILE_FILL,
        outline=TILE_EDGE,
        width=max(1, round(2 * k)),
    )

    def polyline(points, color, w):
        pts = [(x * k, y * k) for x, y in points]
        d.line(pts, fill=color, width=max(1, round(w * k)), joint="curve")
        r = w / 2
        for cx, cy in (points[0], points[-1]):
            d.ellipse(((cx - r) * k, (cy - r) * k, (cx + r) * k, (cy + r) * k), fill=color)

    polyline(LEFT_BRACKET, BRACKET_DIM, stroke)
    polyline(RIGHT_BRACKET, BRACKET_LIT, stroke)

    if WITH_PLUSES:
        dx, dy = G1[0] - G0[0], G1[1] - G0[1]
        axis_len = dx * dx + dy * dy
        for p0, p1 in PLUS_LINES:
            n = 24
            for i in range(n):
                t0, t1 = i / n, (i + 1) / n
                seg = [
                    (p0[0] + (p1[0] - p0[0]) * t0, p0[1] + (p1[1] - p0[1]) * t0),
                    (p0[0] + (p1[0] - p0[0]) * t1, p0[1] + (p1[1] - p0[1]) * t1),
                ]
                mid = ((seg[0][0] + seg[1][0]) / 2 - G0[0], (seg[0][1] + seg[1][1]) / 2 - G0[1])
                t = (mid[0] * dx + mid[1] * dy) / axis_len
                color = grad_color(t)
                pts = [(x * k, y * k) for x, y in seg]
                d.line(pts, fill=color, width=max(1, round(plus * k)))
                r = plus / 2
                for cx, cy in seg:
                    d.ellipse(((cx - r) * k, (cy - r) * k, (cx + r) * k, (cy + r) * k), fill=color)

    return img.resize((size, size), Image.LANCZOS)


# ── ICO (PNG-compressed entries, Vista+) ─────────────────────────────────────

def write_ico(path: Path, images: list[Image.Image]) -> None:
    pngs = []
    for im in images:
        buf = io.BytesIO()
        im.save(buf, format="PNG", optimize=True)
        pngs.append(buf.getvalue())

    out = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    for im, png in zip(images, pngs):
        w, h = im.size
        out += struct.pack("<BBBBHHII", w % 256, h % 256, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
    out += b"".join(pngs)
    path.write_bytes(out)


# ── master SVG (user's design; plus group only when WITH_PLUSES) ─────────────

MASTER_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">
  <rect x="16" y="16" width="224" height="224" rx="52" fill="#18181B" stroke="#27272A" stroke-width="2" />

  <!-- 抽象左耳 / 躯干后背括号 -->
  <path d="M 104 62 L 80 110 L 80 190" fill="none" stroke="#A1A1AA" stroke-width="14" stroke-linecap="round" stroke-linejoin="round" />

  <!-- 抽象右耳 / 面部前导括号 -->
  <path d="M 142 52 L 122 104 L 168 128 L 168 152 L 138 152 L 138 190" fill="none" stroke="#F4F4F5" stroke-width="14" stroke-linecap="round" stroke-linejoin="round" />
{plus_block}</svg>
"""

PLUS_BLOCK = """
  <!-- C++ 并行算力标识（可选）：渐变必须 userSpaceOnUse——objectBoundingBox
       在零面积的 <line> 上未定义，多数渲染器会整组丢弃。 -->
  <defs>
    <linearGradient id="tokenGrad" gradientUnits="userSpaceOnUse" x1="102" y1="136" x2="130" y2="160">
      <stop offset="0%" stop-color="#F43F5E" />
      <stop offset="100%" stop-color="#FB7185" />
    </linearGradient>
  </defs>
  <g stroke="url(#tokenGrad)" stroke-width="5" stroke-linecap="round">
    <line x1="102" y1="142" x2="114" y2="142" />
    <line x1="108" y1="136" x2="108" y2="148" />
    <line x1="118" y1="154" x2="130" y2="154" />
    <line x1="124" y1="148" x2="124" y2="160" />
  </g>
"""


def favicon_uri() -> str:
    master = MASTER_SVG.replace("{plus_block}", PLUS_BLOCK if WITH_PLUSES else "")
    return "data:image/svg+xml;base64," + base64.b64encode(master.encode()).decode()


def preview_sheet(images: dict[int, Image.Image]) -> Image.Image:
    sizes = [256, 64, 48, 32, 16]
    cell, pad = 268, 28
    W = pad + sum(s + (40 if s != 256 else 0) + 18 for s in sizes) + pad
    H = (cell + pad) * 2 + pad
    sheet = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(sheet)
    for row, bg in enumerate(((243, 243, 243, 255), (32, 32, 32, 255))):
        y = pad + row * (cell + pad)
        d.rectangle((0, y - 4, W, y + cell + 4), fill=bg)
        x = pad
        for s in sizes:
            sheet.alpha_composite(images[s], (x, y + (cell - s) // 2))
            x += s + (40 if s != 256 else 0) + 18
    return sheet.convert("RGB")


def main() -> None:
    # ≥48 px: the authored strokes. Smaller entries widen them so the
    # brackets survive a 16 px taskbar slot.
    spec = [(256, 14, 5), (128, 14, 5), (64, 14, 5), (48, 14, 5), (32, 17, 7), (24, 20, 9), (16, 24, 11)]
    images = {s: render(s, st, pl) for s, st, pl in spec}

    write_ico(ROOT / "src-tauri" / "icons" / "llama_icon.ico", [images[s] for s, _, _ in spec])
    write_ico(ROOT / "llama_icon.ico", [images[s] for s, _, _ in spec])
    master = MASTER_SVG.replace("{plus_block}", PLUS_BLOCK if WITH_PLUSES else "")
    (ROOT / "docs" / "design" / "app-icon.svg").write_text(master, encoding="utf-8")
    preview_sheet(images).save(ROOT / "docs" / "design" / "app-icon-preview.png")

    print("pluses:", "on" if WITH_PLUSES else "off")
    print("favicon uri:")
    print(favicon_uri())
    print("done — ico (x2), master svg, preview sheet")


if __name__ == "__main__":
    main()

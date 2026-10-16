# -*- coding: utf-8 -*-
"""llama_ctl 应用图标生成器 —— 羊驼 + 健康脉冲（Flat 平板）。

设计（依据 docs/design/app-icon-concepts.html 推荐方案 A）:
  平板圆角方形（品牌蓝 #0b5cb0，纯平，不用渐变）+ 白色羊驼剪影
  + 抠空的内置细节（眼 + 健康脉冲线）。

为什么这样画（修掉旧图标的三个问题）:
  - 旧图标是强渐变平板（#4aa6ff→#055ad4，2.39:1 亮度跨度）—— 过时且让白色
    标记的对比度在平板亮端掉到 2.56:1（低于 AA）。新图标改纯平色，标记对比度
    恒定 6.6:1（#0b5cb0 上白字），小尺寸下不再一边糊一边清。
  - 旧标记 `>_` 语义只是「终端」，任何命令行工具都能用。新标记是羊驼（llama.cpp
    的字面指涉）+ 脉冲线（服务健康），用途一眼可读。
  - 旧图标靠右上角 3.84px 的绿点表达运行态，16px 下糊成一个点。新图标把
    「在跑」交给脉冲线本身，不再依赖一个装不下的小色块。

小尺寸分级（实测结论，见 scratch 验证）:
  内层细节（眼 + 脉冲线）在 <48px 会被降采样糊掉。故:
    >=48px : 完整细节（眼 + 脉冲线）
    < 48px : 去掉眼与脉冲线，只留羊驼剪影 —— 剪影在 16px 仍有 4 行双耳分离，
             是唯一可辨认的特征，必须保住。

用法:
    python make_icon.py preview    # 输出预览图到 Temp/icon-preview
    python make_icon.py ico        # 写出 llama_icon.ico

改图标:调下面的常量;tests/test_icon.py 会守住结构（档位齐全、256 排首位）
与小尺寸可读性（16/24/32px 笔画可见、剪影在画布内）。
"""
import os
import sys

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.abspath(__file__))
PREVIEW = os.path.join(ROOT, "Temp", "icon-preview")
ICO = os.path.join(ROOT, "llama_icon.ico")
SIZES = [16, 24, 32, 48, 64, 128, 256]
# 目录顺序:本仓库要求 256 档排首位(PyInstaller 嵌入依赖此顺序,见 commit 16d8047)
ORDER = (256, 16, 24, 32, 48, 64, 128)

# 配色（与 docs/design/font-icon-spec.html 的令牌一致）
PLATE = (0x0b, 0x5c, 0xb0)          # 品牌蓝 #0b5cb0（纯平）
WHITE = (255, 255, 255)

DETAIL_MIN = 48      # 低于此尺寸只画剪影（内层细节会糊）

# 羊驼剪影：256 单位画布上的绝对三次贝塞尔控制点。
# 取自 OD 方案 A 的 SVG path，等价展开为 (起点, [控制点x3]...) 序列。
_LLAMA_SEGS = [
    ("M", 62, 210),
    ("C", 66, 171, 72, 136, 77, 105),
    ("L", 84, 69),
    ("L", 109, 93),
    ("L", 128, 54),
    ("L", 149, 88),
    ("C", 177, 94, 194, 115, 197, 142),
    ("L", 204, 178),
    ("C", 207, 193, 197, 206, 182, 206),
    ("L", 147, 206),
    ("C", 131, 206, 117, 196, 111, 181),
    ("L", 100, 155),
    ("L", 89, 210),
]

_PULSE = [(119, 180), (136, 180), (146, 162), (158, 196), (168, 174), (191, 174)]
_EYE = (157, 137, 8)


def _flatten(segs, steps=48):
    """把绝对 M/L/C 段展开为多边形顶点（贝塞尔按 steps 细分）。"""
    pts = []
    for seg in segs:
        if seg[0] == "M":
            pts.append((seg[1], seg[2]))
        elif seg[0] == "L":
            pts.append((seg[1], seg[2]))
        elif seg[0] == "C":
            x0, y0 = pts[-1]
            x1, y1, x2, y2, x3, y3 = seg[1:]
            for i in range(1, steps + 1):
                t = i / steps
                mt = 1 - t
                pts.append((
                    mt ** 3 * x0 + 3 * mt ** 2 * t * x1 + 3 * mt * t ** 2 * x2 + t ** 3 * x3,
                    mt ** 3 * y0 + 3 * mt ** 2 * t * y1 + 3 * mt * t ** 2 * y2 + t ** 3 * y3))
    return pts


_LLAMA_POLY = _flatten(_LLAMA_SEGS)


def _params(size):
    """按尺寸微调。圆角与平板内缩按图标惯例外推。"""
    # Windows 应用图标惯例:平板四周留 ~3% 透明边(8/256)
    margin = 0.031
    if size <= 20:
        return dict(margin=margin, radius=0.203, detail=False)
    if size <= 36:
        return dict(margin=margin, radius=0.203, detail=False)
    if size < DETAIL_MIN:
        return dict(margin=margin, radius=0.203, detail=False)
    return dict(margin=margin, radius=0.203, detail=True)


def render(size):
    """渲染一枚 size x size 的应用图标。

    先在 8 倍母版（上限 2048）绘制再 LANCZOS 降采样 -> 抗锯齿。
    """
    p = _params(size)
    m = max(512, min(2048, size * 8))
    k = m / 256.0

    # 平板：纯平色 + 圆角（8/256 透明边）
    ins = 8 * k
    mask = Image.new("L", (m, m), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [ins, ins, m - ins, m - ins], radius=p["radius"] * 256 * k, fill=255)

    base = Image.new("RGBA", (m, m), PLATE + (255,))
    base.putalpha(mask)

    layer = Image.new("RGBA", (m, m), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.polygon([(x * k, y * k) for x, y in _LLAMA_POLY], fill=WHITE + (255,))

    if p["detail"]:
        # 眼 + 脉冲线：在白色剪影上以透明抠空（PIL RGBA 绘制=替换）
        ex, ey, er = _EYE
        d.ellipse([(ex - er) * k, (ey - er) * k, (ex + er) * k, (ey + er) * k],
                  fill=(0, 0, 0, 0))
        w = max(1, int(round(10 * k)))
        d.line([(x * k, y * k) for x, y in _PULSE], fill=(0, 0, 0, 0),
               width=w, joint="curve")
        for x, y in _PULSE:
            r = w / 2
            d.ellipse([x * k - r, y * k - r, x * k + r, y * k + r], fill=(0, 0, 0, 0))

    out = Image.alpha_composite(base, layer)
    a = out.split()[3]
    out.putalpha(Image.composite(a, Image.new("L", (m, m), 0), mask))
    return out.resize((size, size), Image.LANCZOS)


def save_ico(path=ICO, sizes=SIZES, order=ORDER):
    """手写 ICO 目录。

    Pillow 的 ICO 写出按尺寸升序排列,而本仓库要求 256 档排首位,
    故自己拼目录。条目用 PNG 编码(Vista+ 支持)。
    """
    import io
    import struct
    blobs = {}
    for s in sizes:
        buf = io.BytesIO()
        render(s).save(buf, format="PNG", optimize=True)
        blobs[s] = buf.getvalue()

    order = [s for s in order if s in blobs]
    head = bytearray(struct.pack("<HHH", 0, 1, len(order)))
    body = bytearray()
    offset = 6 + 16 * len(order)
    for s in order:
        data = blobs[s]
        dim = 0 if s >= 256 else s            # 256 在目录里记为 0
        head += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        body += data
        offset += len(data)
    with open(path, "wb") as f:
        f.write(bytes(head) + bytes(body))


def _preview():
    os.makedirs(PREVIEW, exist_ok=True)
    for bg_name, bg in (("light", (245, 245, 247)), ("dark", (32, 32, 34))):
        gap, pad, row_h = 18, 22, 256 + 26
        W = pad * 2 + sum(SIZES) + gap * (len(SIZES) - 1)
        sheet = Image.new("RGB", (W, pad * 2 + row_h), bg)
        x = pad
        for s in SIZES:
            im = render(s)
            sheet.paste(im, (x, pad + (256 - s) // 2), im)
            x += s + gap
        sheet.save(os.path.join(PREVIEW, f"icon_{bg_name}.png"))

    # 真尺寸行：16/24/32/48 + 各自 8x 放大，便于人眼核对
    truth = Image.new("RGB", (420, 150), (240, 240, 243))
    x = 12
    for s in (16, 24, 32, 48):
        im = render(s)
        truth.paste(im, (x, 60 - s // 2), im)
        x += s + 14
    x = 12
    for s in (16, 24, 32, 48):
        im = render(s).resize((s * 3, s * 3), Image.NEAREST)
        truth.paste(im, (x, 96), im)
        x += s * 3 + 10
    truth.save(os.path.join(PREVIEW, "icon_truth_size.png"))
    print("preview ->", PREVIEW)


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "preview"
    if what == "ico":
        save_ico()
        print("wrote", ICO)
    else:
        _preview()


if __name__ == "__main__":
    main()

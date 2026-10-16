# -*- coding: utf-8 -*-
"""svgpath.py — 最小 SVG 路径解析 + 非零环绕栅格化。

为什么需要它：
  Phosphor 的图标是「填充路径」（fill），不是描边，而且带孔洞
  （多个子路径，靠环绕方向挖空，例如 warning-circle 的圆环、trash 的桶身）。
  PIL 的 ImageDraw.polygon 对每个子路径独立填充，无法挖孔，
  故这里自己实现 **非零环绕（nonzero winding）** 扫描线填充。

支持的命令：M m L l H h V v C c S s Q q T t A a Z z
  （本项目 vendored 的 12 个 Phosphor bold 图标只用到除 Q/T 外的部分；
   Q/T 一并实现，以免日后换图标时静默产出空白图。）

输出：指定尺寸的 alpha 蒙版（PIL "L" 图），已在内部按 SS 倍超采样后降采样，
      故边缘带抗锯齿。

用法:
    from svgpath import render_mask
    mask = render_mask(path_d, size=72, ss=8)
"""

import math
import re

__all__ = ["parse_path", "render_mask", "path_bbox"]

_NUM = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
# 每个命令需要的参数个数（None = 可变/特殊）
_ARGC = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2,
         "A": 7, "Z": 0}


def _tokens(d):
    """把 path 串切成 (命令, [参数...]) 序列，处理隐式重复（M 后跟多组 = L）。"""
    out = []
    i, n = 0, len(d)
    cmd = None
    while i < n:
        ch = d[i]
        if ch in "MmLlHhVvCcSsQqTtAaZz":
            cmd = ch
            i += 1
        elif ch in " \t\r\n,":
            i += 1
            continue
        else:
            # 隐式重复：沿用上一个命令（M→L, m→l）。
            # 非「数字/正负号/小数点」的字符一律报错 —— 否则遇到未实现的命令
            # （曾漏掉 Q/T）会静默沿用上一条命令，产出看似正常的错误图形。
            if cmd is None:
                raise ValueError("路径未以命令开头: %r" % d[:20])
            if ch not in "0123456789+-.":
                raise ValueError("不支持的路径命令 %r（位于 %r）" % (ch, d[max(0, i-10):i+10]))
            if cmd == "M":
                cmd = "L"
            elif cmd == "m":
                cmd = "l"
        if cmd in "Zz":
            out.append(("Z", []))
            continue
        need = _ARGC[cmd.upper()]
        args = []
        while len(args) < need:
            m = _NUM.match(d, i)
            if not m:
                break
            args.append(float(m.group(0)))
            i = m.end()
            # 跳过分隔符
            while i < n and d[i] in " \t\r\n,":
                i += 1
        if len(args) < need:
            # 参数不足 = 路径串损坏或被截断。静默 break 会丢掉尾部命令，
            # 让调用方拿到「少一块」但看似正常的图形；这里直接报错。
            raise ValueError("命令 %r 参数不足：需要 %d 个，实得 %d 个（%r 结尾）"
                             % (cmd, need, len(args), d[max(0, i-10):i+10]))
        out.append((cmd, args))
    return out


def _arc_to_points(x1, y1, rx, ry, phi_deg, large, sweep, x2, y2):
    """SVG 椭圆弧 → 采样点列表（不含起点）。标准 endpoint→center 参数化。"""
    if rx == 0 or ry == 0:
        return [(x2, y2)]
    rx, ry = abs(rx), abs(ry)
    phi = math.radians(phi_deg)
    cosp, sinp = math.cos(phi), math.sin(phi)
    dx2, dy2 = (x1 - x2) / 2.0, (y1 - y2) / 2.0
    x1p = cosp * dx2 + sinp * dy2
    y1p = -sinp * dx2 + cosp * dy2
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1:
        s = math.sqrt(lam)
        rx *= s
        ry *= s
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = 0.0 if den == 0 else math.sqrt(max(0.0, num / den))
    if bool(large) == bool(sweep):
        coef = -coef
    cxp = coef * rx * y1p / ry
    cyp = -coef * ry * x1p / rx
    cx = cosp * cxp - sinp * cyp + (x1 + x2) / 2.0
    cy = sinp * cxp + cosp * cyp + (y1 + y2) / 2.0

    def ang(ux, uy, vx, vy):
        dot = ux * vx + uy * vy
        norm = math.hypot(ux, uy) * math.hypot(vx, vy)
        if norm == 0:
            return 0.0
        a = math.acos(max(-1.0, min(1.0, dot / norm)))
        return -a if (ux * vy - uy * vx) < 0 else a

    theta1 = ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dtheta = ang((x1p - cxp) / rx, (y1p - cyp) / ry,
                 (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dtheta > 0:
        dtheta -= 2 * math.pi
    elif sweep and dtheta < 0:
        dtheta += 2 * math.pi

    steps = max(2, int(math.ceil(abs(dtheta) / (math.pi / 24))))
    pts = []
    for k in range(1, steps + 1):
        t = theta1 + dtheta * k / steps
        xt, yt = rx * math.cos(t), ry * math.sin(t)
        pts.append((cosp * xt - sinp * yt + cx, sinp * xt + cosp * yt + cy))
    pts[-1] = (x2, y2)          # 端点精确收口，避免累积误差
    return pts


def parse_path(d):
    """解析为子路径列表；每个子路径是 [(x, y), ...] 的折线点列。"""
    subs = []
    cur = []
    x = y = 0.0          # 当前点
    sx = sy = 0.0        # 子路径起点
    prev_c2 = None       # 上一段三次贝塞尔第二控制点（S/s 用）
    prev_q = None        # 上一段二次贝塞尔控制点（T/t 用）

    def flush(close):
        nonlocal cur
        if len(cur) >= 2:
            if close:
                cur.append((sx, sy))
            subs.append(cur)
        cur = []

    prev_up = None       # 上一条命令（T/t 仅在紧跟 Q/q/T/t 时才反射控制点）
    for cmd, a in _tokens(d):
        up = cmd.upper()
        was_quad = prev_up in ("Q", "T")
        prev_up = up
        rel = cmd.islower()
        if up == "M":
            flush(False)
            x, y = (x + a[0], y + a[1]) if rel else (a[0], a[1])
            sx, sy = x, y
            cur = [(x, y)]
            prev_c2 = None
            prev_q = None
        elif up == "L":
            x, y = (x + a[0], y + a[1]) if rel else (a[0], a[1])
            cur.append((x, y))
            prev_c2 = None
            prev_q = None
        elif up == "H":
            x = x + a[0] if rel else a[0]
            cur.append((x, y))
            prev_c2 = None
            prev_q = None
        elif up == "V":
            y = y + a[0] if rel else a[0]
            cur.append((x, y))
            prev_c2 = None
            prev_q = None
        elif up == "C" or up == "S":
            if up == "C":
                p1 = (x + a[0], y + a[1]) if rel else (a[0], a[1])
                p2 = (x + a[2], y + a[3]) if rel else (a[2], a[3])
                p3 = (x + a[4], y + a[5]) if rel else (a[4], a[5])
            else:
                p1 = (2 * x - prev_c2[0], 2 * y - prev_c2[1]) if prev_c2 else (x, y)
                p2 = (x + a[0], y + a[1]) if rel else (a[0], a[1])
                p3 = (x + a[2], y + a[3]) if rel else (a[2], a[3])
            # 三次贝塞尔采样：步数按控制多边形长度自适应
            approx = (math.dist((x, y), p1) + math.dist(p1, p2) + math.dist(p2, p3))
            steps = max(2, min(64, int(approx / 6) + 2))
            for k in range(1, steps + 1):
                t = k / steps
                mt = 1 - t
                bx = (mt ** 3 * x + 3 * mt ** 2 * t * p1[0]
                      + 3 * mt * t ** 2 * p2[0] + t ** 3 * p3[0])
                by = (mt ** 3 * y + 3 * mt ** 2 * t * p1[1]
                      + 3 * mt * t ** 2 * p2[1] + t ** 3 * p3[1])
                cur.append((bx, by))
            prev_c2 = p2
            prev_q = None
            x, y = p3
        elif up == "Q" or up == "T":
            if up == "Q":
                qp = (x + a[0], y + a[1]) if rel else (a[0], a[1])
                p3 = (x + a[2], y + a[3]) if rel else (a[2], a[3])
            else:
                # T/t：控制点 = 上一控制点关于当前点的反射；前面不是 Q/T 时取当前点
                qp = (2 * x - prev_q[0], 2 * y - prev_q[1]) if (was_quad and prev_q) else (x, y)
                p3 = (x + a[0], y + a[1]) if rel else (a[0], a[1])
            approx = math.dist((x, y), qp) + math.dist(qp, p3)
            steps = max(2, min(64, int(approx / 6) + 2))
            for k in range(1, steps + 1):
                t = k / steps
                mt = 1 - t
                cur.append((mt * mt * x + 2 * mt * t * qp[0] + t * t * p3[0],
                            mt * mt * y + 2 * mt * t * qp[1] + t * t * p3[1]))
            prev_q = qp
            x, y = p3
        elif up == "A":
            rx, ry, rot, large, sweep = a[0], a[1], a[2], int(a[3]), int(a[4])
            ex, ey = (x + a[5], y + a[6]) if rel else (a[5], a[6])
            cur.extend(_arc_to_points(x, y, rx, ry, rot, large, sweep, ex, ey))
            x, y = ex, ey
            prev_c2 = None
            prev_q = None
        elif up == "Z":
            if cur:
                cur.append((sx, sy))
                flush(False)
            x, y = sx, sy
            prev_c2 = None
            prev_q = None
    flush(False)
    return subs


def path_bbox(subs):
    xs = [p[0] for s in subs for p in s]
    ys = [p[1] for s in subs for p in s]
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def render_mask(d, size, ss=8, view=256.0, scale=None, offset=(0.0, 0.0)):
    """把 SVG path 栅格化为 size×size 的 alpha 蒙版（PIL "L"）。

    ss     —— 超采样倍数（内部按 size*ss 栅格化后盒式降采样 → 抗锯齿）
    view   —— SVG viewBox 边长（Phosphor = 256）
    scale  —— viewBox 单位 → 输出像素的缩放；默认 size/view
    offset —— 在缩放后的坐标上平移（像素，输出尺度）
    非零环绕：跨越边界的绕数 != 0 才填充，故子路径反向即为孔洞。
    """
    from PIL import Image

    subs = parse_path(d)
    if not subs:
        return Image.new("L", (size, size), 0)

    k = (size * ss) / view if scale is None else scale * ss
    ox, oy = offset[0] * ss, offset[1] * ss
    polys = [[(px * k + ox, py * k + oy) for (px, py) in s] for s in subs]

    N = size * ss
    mask = Image.new("L", (N, N), 0)
    px = mask.load()

    # 收集边（含方向），供逐行扫描
    edges = []
    for poly in polys:
        m = len(poly)
        for i in range(m):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % m]
            if y1 != y2:
                edges.append((x1, y1, x2, y2))

    for row in range(N):
        yc = row + 0.5
        xs = []
        for (x1, y1, x2, y2) in edges:
            if (y1 <= yc < y2) or (y2 <= yc < y1):
                t = (yc - y1) / (y2 - y1)
                xs.append((x1 + t * (x2 - x1), 1 if y2 > y1 else -1))
        if not xs:
            continue
        xs.sort()
        wind = 0
        for i in range(len(xs) - 1):
            wind += xs[i][1]
            if wind != 0:
                a = int(math.floor(xs[i][0] + 0.5))
                b = int(math.floor(xs[i + 1][0] + 0.5))
                if b <= 0 or a >= N:
                    continue
                a = max(0, a)
                b = min(N, b)
                for c in range(a, b):
                    px[c, row] = 255

    return mask.resize((size, size), Image.BOX)


def _ink(mask):
    """蒙版墨迹像素数（histogram 取 >128 的档位，避免 getdata 弃用告警）。"""
    return sum(mask.histogram()[129:])


if __name__ == "__main__":
    # 自检：方形单子路径 / 环形挖孔 / 弧线 —— 三者都必须正确
    m = render_mask("M0,0 H256 V256 H0 Z", 32, ss=4)
    assert _ink(m) == 32 * 32, _ink(m)

    # 外方 + 反向内方 = 中空（非零环绕的挖孔语义）
    m2 = render_mask("M0,0 H256 V256 H0 Z M64,64 V192 H192 V64 Z", 32, ss=4)
    assert m2.getpixel((16, 16)) == 0, m2.getpixel((16, 16))

    # 圆弧：整圆应接近满圆面积
    m3 = render_mask("M128,16 A112,112 0 1 0 128,240 A112,112 0 1 0 128,16 Z", 64, ss=4)
    area = math.pi * (112 / 256 * 64) ** 2
    assert abs(_ink(m3) - area) / area < 0.05, (_ink(m3), area)

    # 二次贝塞尔 Q 与反射 T：漏实现曾静默产出空白图，故在此锁死
    # 容差 0.1：曲线按自适应步数离散采样，顶点 t=0.5 未必正好落在采样点上
    q = path_bbox(parse_path("M0,0 Q50,50 100,0"))
    assert q and abs(q[3] - 25) < 0.1 and abs(q[2] - 100) < 0.1, q   # 顶点 y = 50/2
    t = path_bbox(parse_path("M0,0 Q50,50 100,0 T200,0"))
    assert t and abs(t[1] + 25) < 0.1 and abs(t[2] - 200) < 0.1, t   # 反射后顶点 y = -25
    # T 前面不是 Q/T 时不反射（控制点取当前点），且不得抛错
    t2 = path_bbox(parse_path("M0,0 L40,0 T80,0"))
    assert t2 and abs(t2[2] - 80) < 0.1, t2
    # 未实现的命令必须显式报错，而不是静默沿用上一条命令
    for bad in ("M0,0 Zq" , "M0,0 K5,5"):
        try:
            parse_path(bad)
            raise AssertionError("未拒绝不支持的路径命令: %r" % bad)
        except ValueError:
            pass
    print("svgpath self-check OK")

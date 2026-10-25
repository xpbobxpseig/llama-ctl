#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
params.py — AppParameters 解析 / 重建（llama_ctl）

NSSM AppParameters 文本 ↔ 字段值字典 的双向映射，纯函数、零系统依赖、可独立单测。
本模块不 import FIELDS：字段定义（UI 呈现配置）留在 GUI 层，经参数显式传入。
依赖的字段结构契约：key / aliases / kind（slider 另需 min/max/step/default；
check 型可另给 off_aliases，表示「该开关默认开启，关闭时输出否定形式」）。
"""

import math

# ---------------------------------------------------------------------------
# 参数切分
# ---------------------------------------------------------------------------
def split_args(text):
    """按 Windows CRT 规则切分命令行（与 CommandLineToArgvW 逐字节一致）。

    AppParameters 是**原始命令行字符串**，最终由 Windows 切分后交给
    llama-server.exe，所以判定标准只能是 CommandLineToArgvW，不能是本工具
    自己的直觉。不用 shlex：posix=False 不处理引号（含空格 JSON 会崩），
    posix=True 会把 Windows 路径的 \\ 当转义。

    规则（CRT 现行版本）：
      - 空白分隔参数（引号内除外）；引号成对包裹一段内容；
      - 反斜杠**仅当紧邻引号时**才有特殊含义：
          偶数个 + 引号 → 输出一半数量的反斜杠，引号是分隔符；
          奇数个 + 引号 → 输出一半数量的反斜杠，引号是字面量；
        其余位置一律字面量（这正是 \\\\NAS\\... 的 UNC 前缀不能被吃掉的原因）。
      - 引号闭合后紧跟非空白字符时，后续字符继续并入同一参数。
    未闭合引号吞到串尾——与 CommandLineToArgvW 行为一致，不另行"修复"。
    """
    out = []
    i, n = 0, len(text or "")
    while i < n:
        while i < n and text[i] in " \t":
            i += 1
        if i >= n:
            break
        buf = []
        in_quotes = False
        while i < n:
            c = text[i]
            if c == "\\":
                k = 0
                while i < n and text[i] == "\\":
                    k += 1
                    i += 1
                if i < n and text[i] == '"':
                    buf.append("\\" * (k // 2))
                    if k % 2:
                        buf.append('"')    # 转义引号：字面量
                    else:
                        in_quotes = not in_quotes
                    i += 1
                    continue
                buf.append("\\" * k)       # 不紧邻引号：全部字面量
                continue
            if c == '"':
                in_quotes = not in_quotes
                i += 1
                continue
            if c in " \t" and not in_quotes:
                break
            buf.append(c)
            i += 1
        out.append("".join(buf))
    return out


def _alias_to_key(fields):
    m = {}
    for f in fields:
        for a in f["aliases"]:
            m[a] = f["key"]
    return m


def _is_number(s):
    """有限数值才算数：float("nan")/("inf") 能通过 float()，但 int(nan) 会抛，
    会让整条参数加载路径崩掉（`--ctx-size nan` 实测 ValueError）。"""
    try:
        return math.isfinite(float(s))
    except (TypeError, ValueError):
        return False


def _is_neg_number(t):
    """形如 -1 / -0.05 / -1.5 的负数值（排除 "-"、"--foo"、"---" 等 flag）。"""
    return (t.startswith("-") and not t.startswith("--")
            and len(t) > 1 and _is_number(t[1:]))


def parse_params(text, fields):
    """解析 NSSM AppParameters 为 (values: dict, extras: list, warnings: list)。

    -c 与 --ctx-size 冲突：保留最后一项并告警；滑块型数值缺失则取 default。
    check 型（如 --no-mmap）无值，记为值 "1"；若官方提供否定形式
    （字段声明 off_aliases，如 --jinja / --no-jinja），命中否定形式记为 ""。

    extras 保持原样（不改元素类型与顺序）：否定形式经 off_aliases 识别后
    根本不会落进 extras，从源头避免「把否定的那个挪到末尾 → 反转最后生效」。
    """
    alias_map = _alias_to_key(fields)
    off_map = {}
    for f in fields:
        for a in f.get("off_aliases") or []:
            off_map[a] = f["key"]
    values = {f["key"]: "" for f in fields}
    extras = []
    warnings = []
    tokens = split_args(text) if text else []
    i, n = 0, len(tokens)
    ctx_seen = []
    seen = set()
    while i < n:
        tok = tokens[i]
        if tok in off_map:
            # 否定形式：显式关闭该 check 开关（如 --no-jinja）
            values[off_map[tok]] = ""
            seen.add(off_map[tok])
            i += 1
            continue
        if tok in alias_map:
            key = alias_map[tok]
            fld = next(f for f in fields if f["key"] == key)
            if fld["kind"] == "check":
                values[key] = "1"
                seen.add(key)
                i += 1
                continue
            if i + 1 < n and (not tokens[i + 1].startswith("-")
                                or _is_neg_number(tokens[i + 1])):
                val = tokens[i + 1]
                i += 2
            else:
                val = ""
                i += 1
            if key == "ctx_size":
                ctx_seen.append(val)
            values[key] = val
            seen.add(key)
        else:
            extras.append(tok)
            i += 1
    # 声明了 off_aliases 的开关「默认开启」（llama.cpp 对 --jinja 的既有默认）：
    # 两种形式都没出现时按开启处理，避免「取消勾选后不写任何标志 = 仍是开」。
    for fld in fields:
        if fld["kind"] == "check" and fld.get("off_aliases") and fld["key"] not in seen:
            values[fld["key"]] = "1"
    # 滑块默认值回填（解析到的若为空或越界则用 default）；整数 step 字段规范化去 .0
    for fld in fields:
        if fld["kind"] == "slider":
            v = values[fld["key"]].strip()
            int_step = float(fld["step"]).is_integer()
            if v == "" or not _is_number(v):
                dflt = fld.get("default", fld["min"])
                values[fld["key"]] = str(int(dflt)) if int_step else str(dflt)
            else:
                num = float(v)
                lo, hi = fld["min"], fld["max"]
                if num < lo or num > hi:
                    warnings.append(f"{fld['label']} 值 {v} 超出范围[{lo},{hi}]，已回退默认。")
                    dflt = fld.get("default", lo)
                    values[fld["key"]] = str(int(dflt)) if int_step else str(dflt)
                else:
                    values[fld["key"]] = str(int(num)) if int_step else str(num)
    if len(ctx_seen) > 1:
        warnings.append(
            f"检测到冲突：-c 与 --ctx-size 同时出现 {len(ctx_seen)} 次，"
            f"已保留最后一项 '{ctx_seen[-1]}'（llama.cpp 以最后为准）。"
        )
    return values, extras, warnings


def build_params(values, extras, fields):
    """由字段字典 + extras 重建 AppParameters。

    顺序：fields 顺序输出有值字段（统一长名）。check 型仅当值为真输出标志名；
    声明 off_aliases 的开关（默认开启型，如 --jinja）为假时输出否定形式，
    否则「取消勾选」在实跑里等于没关（llama.cpp 默认开启，缺省即开）。
    滑块/数值/文本为空则跳过。combo 空字符串跳过。
    """
    out = []
    st = (values.get("spec_type") or "").strip()
    for fld in fields:
        key = fld["key"]
        v = (values.get(key) or "").strip()
        # 草稿相关字段仅在投机解码（draft-*）模式下输出，避免普通/ngram 模式带无效参数
        if key.startswith("spec_draft") and not st.startswith("draft"):
            continue
        if fld["kind"] == "check":
            on = v in ("1", "true", "on", "yes")
            off_aliases = fld.get("off_aliases") or []
            if on:
                out.append(fld["aliases"][-1])
            elif off_aliases:
                out.append(off_aliases[-1])
            continue
        if not v:
            continue
        if fld["kind"] == "combo" and v == "":
            continue
        primary = max(fld["aliases"], key=len)
        out.append(primary)
        out.append(v)
    out.extend(extras)

    def _quote(t):
        """按 CRT 规则给值加引号，使 CommandLineToArgvW 能原样还原。

        规则：反斜杠只在「紧邻引号」时才有特殊含义，所以
          - 值内部的 \\ 全部原样保留（UNC 前缀 \\\\NAS 正是靠这一点存活）；
          - 只在值内的 " 之前、以及结尾处，把反斜杠翻倍。
        旧实现把值内所有 \\ 都翻倍，导致写回后 Windows 实际收到双反斜杠路径
        （\\\\NAS\\share 被折叠后侥幸可用，但 UNC 前缀语义已变、且与
        split_args 不再互逆）。
        """
        out = ['"']
        n_bs = 0
        for ch in t:
            if ch == "\\":
                n_bs += 1
                continue
            if ch == '"':
                out.append("\\" * (n_bs * 2 + 1))   # 转义引号：先翻倍再补一个
                out.append('"')
                n_bs = 0
                continue
            if n_bs:
                out.append("\\" * n_bs)             # 不紧邻引号：原样保留
                n_bs = 0
            out.append(ch)
        if n_bs:
            out.append("\\" * (n_bs * 2))           # 结尾反斜杠必须翻倍，否则会吃掉收尾引号
        out.append('"')
        return "".join(out)

    def _needs_quotes(t):
        return any(ch in t for ch in (' ', '\t', '"'))

    return " ".join(_quote(t) if _needs_quotes(t) else t for t in out)


def semantically_equal(a, b, fields):
    """两条 AppParameters 文本在**语义**上是否等价（而非文本相同）。

    用途：GUI 的「未应用更改」判定。直接比较文本会把「等价但写法不同」当成
    改动而误报——本工具写回时统一长名、按 FIELDS 顺序重排、补全滑块默认值、
    给含引号的值加转义，于是任何不是本工具亲手写回的参数（历史遗留 / 手写 /
    其他工具生成）一打开就常亮「未应用更改」。

    判据：两侧各自 parse_params 后比较 (values, extras)。
      - 别名（-ngl vs --n-gpu-layers）、顺序、滑块默认值缺省、引号/转义差异
        → 解析结果相同 → 等价；
      - 数值真差异、check 开关增删、extras 增删 → 不等价。

    extras 按**列表顺序**比较：extras 相对已识别字段的位置无关紧要
    （build_params 统一把它们追加到末尾），但它们彼此的相对次序可能携带
    语义（如 `--override-tensor A=B` 这类成对参数），故不做排序归一。

    解析异常时返回 False（无法证明等价即视为有改动，宁可多提示不可漏提示）。
    """
    try:
        va, ea, _ = parse_params(a, fields)
        vb, eb, _ = parse_params(b, fields)
    except Exception:  # noqa: BLE001 - 字段契约损坏/解析异常：保守判为不同
        return False
    return va == vb and ea == eb

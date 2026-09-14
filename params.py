#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
params.py — AppParameters 解析 / 重建（llama_ctl）

NSSM AppParameters 文本 ↔ 字段值字典 的双向映射，纯函数、零系统依赖、可独立单测。
本模块不 import FIELDS：字段定义（UI 呈现配置）留在 GUI 层，经参数显式传入。
依赖的字段结构契约：key / aliases / kind（slider 另需 min/max/step/default）。
"""

# ---------------------------------------------------------------------------
# 参数切分
# ---------------------------------------------------------------------------
def split_args(text):
    """按空格切分参数，正确处理双引号包裹（支持 \\" 转义）。

    不用 shlex：shlex posix=False 不处理引号（含空格 JSON 会崩），
    posix=True 又会把 Windows 路径的 \\ 当转义。自研切分兼顾两者。
    """
    out, i, n = [], 0, len(text or "")
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c == '"':
            j, buf = i + 1, ""
            while j < n:
                if text[j] == "\\" and j + 1 < n and text[j + 1] in ("\\", '"'):
                    # Windows 引号规则：反斜杠仅转义后随的 \ 或 "；其他字符保留字面量
                    buf += text[j + 1]
                    j += 2
                    continue
                if text[j] == '"':
                    break
                buf += text[j]
                j += 1
            out.append(buf)
            i = j + 1
        else:
            j = i
            while j < n and not text[j].isspace():
                j += 1
            out.append(text[i:j])
            i = j
    return out


def _alias_to_key(fields):
    m = {}
    for f in fields:
        for a in f["aliases"]:
            m[a] = f["key"]
    return m


def _is_number(s):
    try:
        float(s)
        return True
    except ValueError:
        return False


def _is_neg_number(t):
    """形如 -1 / -0.05 / -1.5 的负数值（排除 "-"、"--foo"、"---" 等 flag）。"""
    return (t.startswith("-") and not t.startswith("--")
            and len(t) > 1 and _is_number(t[1:]))


def parse_params(text, fields):
    """解析 NSSM AppParameters 为 (values: dict, extras: list, warnings: list)。

    -c 与 --ctx-size 冲突：保留最后一项并告警；滑块型数值缺失则取 default。
    check 型（如 --no-mmap）无值，记为值 "1"。
    """
    alias_map = _alias_to_key(fields)
    values = {f["key"]: "" for f in fields}
    extras = []
    warnings = []
    tokens = split_args(text) if text else []
    i, n = 0, len(tokens)
    ctx_seen = []
    while i < n:
        tok = tokens[i]
        if tok in alias_map:
            key = alias_map[tok]
            fld = next(f for f in fields if f["key"] == key)
            if fld["kind"] == "check":
                values[key] = "1"
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
        else:
            extras.append(tok)
            i += 1
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

    顺序：fields 顺序输出有值字段（统一长名）。check 型仅当值为真输出标志名。
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
            if v in ("1", "true", "on", "yes"):
                out.append(fld["aliases"][-1])
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
        # 含空格/引号/花括号的值才用双引号包裹（Windows 路径含 \ 但不含这些，不包裹）
        # 包裹时若内部含 \ 或 " 再转义，保证 JSON 等可往返
        if any(ch in t for ch in (' ', '"', '{', '}')):
            return '"' + t.replace("\\", "\\\\").replace('"', '\\"') + '"'
        return t

    return " ".join(_quote(t) for t in out)


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

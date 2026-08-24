# -*- coding: utf-8 -*-
"""params.py 单测：冲突修复 / 别名归并 / extras 保留 / KV 类型透传 / roundtrip。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from params import parse_params, build_params, split_args


def _fields():
    """最小 fields 契约（key/aliases/kind + slider 数值域），不 import GUI。"""
    return [
        {"key": "model", "kind": "path", "aliases": ["-m", "--model"]},
        {"key": "ctx_size", "kind": "slider", "aliases": ["--ctx-size", "-c"],
         "min": 512, "max": 1048576, "step": 512, "default": 131072,
         "label": "上下文长度"},
        {"key": "ctk", "kind": "combo", "aliases": ["--cache-type-k", "-ctk"]},
        {"key": "jinja", "kind": "check", "aliases": ["--jinja"]},
        {"key": "no_mmap", "kind": "check", "aliases": ["--no-mmap"]},
        {"key": "spec_type", "kind": "combo", "aliases": ["--spec-type"]},
        {"key": "spec_draft_model", "kind": "path", "aliases": ["--spec-draft-model"]},
    ]


F = _fields()

# --- 冲突修复（ADR-0003 记录的真实 bug）---

def test_ctx_conflict_keeps_last_with_warning():
    vals, extras, warns = parse_params("--ctx-size 131072 -c 4096", F)
    assert vals["ctx_size"] == "4096"
    assert len(warns) == 1 and "冲突" in warns[0]


def test_single_ctx_no_warning():
    vals, extras, warns = parse_params("--ctx-size 65536", F)
    assert vals["ctx_size"] == "65536"
    assert warns == []


# --- 别名归并 ---

def test_alias_merge_short_and_long():
    vals, _, _ = parse_params("-m a.gguf --model b.gguf", F)
    # 后出现者覆盖（llama.cpp 以最后为准），无告警要求
    assert vals["model"] == "b.gguf"


# --- check 型 ---

def test_check_flag_sets_1_and_rebuilds_flag():
    vals, _, _ = parse_params("--jinja --no-mmap", F)
    assert vals["jinja"] == "1" and vals["no_mmap"] == "1"
    out = build_params(vals, [], F)
    assert "--jinja" in out and "--no-mmap" in out


def test_unchecked_flag_omitted_on_build():
    vals = {f["key"]: "" for f in F}
    assert "--jinja" not in build_params(vals, [], F)


# --- extras 保留（未识别参数不丢失）---

def test_extras_preserved_roundtrip():
    text = "--model a.gguf --some-future-flag 42"
    vals, extras, _ = parse_params(text, F)
    assert extras == ["--some-future-flag", "42"]
    assert build_params(vals, extras, F).endswith("--some-future-flag 42")


# --- 滑块回填与规范化 ---

def test_slider_missing_fills_default_int_step():
    vals, _, warns = parse_params("", F)
    assert vals["ctx_size"] == "131072" and warns == []


def test_slider_out_of_range_falls_back():
    vals, _, warns = parse_params("--ctx-size 99999999", F)
    assert vals["ctx_size"] == "131072" and len(warns) == 1


# --- KV 类型透传 ---

def test_kv_type_passthrough():
    for t in ("f16", "q8_0", "q4_0", "iq4_nl"):
        vals, _, _ = parse_params(f"--cache-type-k {t}", F)
        assert vals["ctk"] == t


# --- 草稿字段门控 ---

def test_draft_fields_only_in_draft_mode():
    vals = {f["key"]: "" for f in F}
    vals["spec_type"] = "draft-mtp"
    vals["spec_draft_model"] = "d.gguf"
    assert "--spec-draft-model d.gguf" in build_params(vals, [], F)
    vals["spec_type"] = "none"
    assert "--spec-draft-model" not in build_params(vals, [], F)


# --- 引号与 roundtrip ---

def test_split_args_handles_quoted_json():
    # 裸 JSON 含空格会被切开（生产行为如此）；build 时 _quote 会给含空格值加引号
    assert split_args('{"a b":1}') == ['{"a', 'b":1}']
    # 带引号的 JSON 完整往返
    assert split_args('"{\\"a b\\":1}"') == ['{"a b":1}']


def test_full_roundtrip_stable():
    # 含空格目录 + 反斜杠的真实路径：T1/T2 修复后必须真正无损（不再“错误自洽”）
    path = 'C:\\Models\\My Model\\qwen.gguf'  # 单反斜杠路径
    text = '--model "%s" --ctx-size 131072 --cache-type-k q8_0 --jinja' % path
    vals, extras, _ = parse_params(text, F)
    assert vals["model"] == path  # 解析侧反斜杠无损
    rebuilt = build_params(vals, extras, F)
    assert 'My Model' in rebuilt  # 空格目录保留
    assert path.replace("\\", "\\\\") in rebuilt  # 转义形式：完整路径在重建文本中
    v2, e2, _ = parse_params(rebuilt, F)
    assert v2 == vals and e2 == extras  # 二次解析稳定
    assert v2["model"] == path  # 单反斜杠真正无损往返


def _neg_fields():
    """T2 用最小 fields：seed 文本型 + min_p 滑块（min 取负值，避免范围回退掩盖取值断言）。"""
    return [
        {"key": "seed", "kind": "text", "aliases": ["-s", "--seed"]},
        {"key": "min_p", "kind": "slider", "aliases": ["--min-p"],
         "min": -1.0, "max": 1.0, "step": 0.01, "default": 0.05, "label": "min-p"},
    ]


# --- 负数值当值不当 flag（T2 / P0-2）---

def test_negative_value_not_flag():
    N = _neg_fields()
    vals, extras, _ = parse_params("-s -1", N)
    assert vals["seed"] == "-1"
    assert extras == []
    out = build_params(vals, extras, N)
    # build_params 统一输出最长别名（--seed），-1 必须作为值保留在重建文本中
    assert "--seed -1" in out


def test_negative_float_value():
    vals, _, warns = parse_params("--min-p -0.05", _neg_fields())
    assert vals["min_p"] == "-0.05"
    assert warns == []


# --- 反斜杠路径（T1 / P0-1）---

def test_split_args_preserves_backslash_paths():
    # Windows 引号规则：反斜杠只对后随 \ 或 " 起转义作用，其余保留字面量
    assert split_args('"F:\\AI_Model\\Qwen.gguf"') == ['F:\\AI_Model\\Qwen.gguf']
    assert split_args('--model "C:\\Models\\My Model\\qwen.gguf"') == \
        ['--model', 'C:\\Models\\My Model\\qwen.gguf']


def test_mixed_escaped_quote_and_literal_backslashes():
    # 引号内 \" 转义 + 非引号反斜杠字面量混合（T3 边界）
    text = '--prompt "say \\"hi\\" C:\\tmp\\note" --ctx-size 8192'
    toks = split_args(text)
    assert toks[1] == 'say "hi" C:\\tmp\\note'


def test_negative_seed_full_roundtrip_three_pass():
    # 负整数 seed：parse→build→parse 三次稳定（T3 边界）
    N = _neg_fields()
    text = "-s -1"
    vals, extras, _ = parse_params(text, N)
    assert vals["seed"] == "-1" and extras == []
    r1 = build_params(vals, extras, N)
    v2, e2, _ = parse_params(r1, N)
    assert v2 == vals and e2 == extras
    r2 = build_params(v2, e2, N)
    v3, e3, _ = parse_params(r2, N)
    assert v3 == vals and e3 == extras


def test_unterminated_quote_and_empty_input_no_crash():
    # 未闭合引号：吞到串尾不抛异常；空串 → []；None → 全默认（T3 边界）
    assert split_args('"abc') == ['abc']
    assert split_args('--model "unclosed') == ['--model', 'unclosed']
    assert split_args("") == []
    vals, extras, warns = parse_params(None, F)
    assert vals["ctx_size"] == "131072" and extras == [] and warns == []
    vals2, extras2, warns2 = parse_params("", F)
    assert vals2 == vals and extras2 == [] and warns2 == []


def test_quoted_path_roundtrip():
    text = '--model "C:\\Models\\My Model\\qwen.gguf" --ctx-size 131072'
    vals, extras, _ = parse_params(text, F)
    assert vals["model"] == 'C:\\Models\\My Model\\qwen.gguf'
    rebuilt = build_params(vals, extras, F)
    # build 对含空格值加引号并转义反斜杠，重建文本应包含完整路径（转义形式）
    assert 'C:\\\\Models\\\\My Model\\\\qwen.gguf' in rebuilt
    v2, e2, _ = parse_params(rebuilt, F)
    assert v2 == vals and e2 == extras

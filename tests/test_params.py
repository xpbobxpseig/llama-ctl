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
    text = r'--model "F:\AI_Model\Qwen3.8-27B-CRACK-Q4_K_M.gguf" --ctx-size 131072 --cache-type-k q8_0 --jinja'
    vals, extras, _ = parse_params(text, F)
    rebuilt = build_params(vals, extras, F)
    v2, e2, _ = parse_params(rebuilt, F)
    assert v2 == vals and e2 == extras

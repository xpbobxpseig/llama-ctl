# -*- coding: utf-8 -*-
"""presets.py 单测：cache 命中/失效/写回。纯文件模块，不 import tkinter。

覆盖候选 #5 的非平凡逻辑：
- 签名未变时复用 cache（不重复解析）——用读文件次数计数证明
- 文件被外部改写/删除/新建时 cache 自动失效
- save_presets 原子写回并同步刷新 cache
- 损坏/非字典内容回退空字典，且不影响后续恢复
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import presets


class _CountingOpen:
    """包住内建 open：统计对目标文件的读次数，其余透传。"""

    def __init__(self, path):
        self.path = path
        self.reads = 0
        self._real = open

    def __call__(self, file, *a, **kw):
        if os.path.abspath(str(file)) == os.path.abspath(self.path) and "r" in (a[0] if a else kw.get("mode", "r")):
            self.reads += 1
        return self._real(file, *a, **kw)


def _isolate(tmp_path, monkeypatch):
    """把 PRESETS_FILE 指到临时文件并清空模块级 cache。"""
    target = str(tmp_path / "presets.json")
    monkeypatch.setattr(presets, "PRESETS_FILE", target)
    monkeypatch.setattr(presets, "_cache", None)
    monkeypatch.setattr(presets, "_cache_sig", None)
    return target


def test_missing_file_returns_empty(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert presets.load_presets() == {}


def test_cache_hit_skips_reparse(tmp_path, monkeypatch):
    target = _isolate(tmp_path, monkeypatch)
    with open(target, "w", encoding="utf-8") as f:
        json.dump({"a": {"n": "1"}}, f)

    counter = _CountingOpen(target)
    monkeypatch.setattr("builtins.open", counter)
    first = presets.load_presets()
    second = presets.load_presets()
    third = presets.load_presets()
    assert first == {"a": {"n": "1"}} and second == first and third == first
    assert counter.reads == 1, "签名未变时只应解析一次"


def test_external_rewrite_invalidates_cache(tmp_path, monkeypatch):
    target = _isolate(tmp_path, monkeypatch)
    with open(target, "w", encoding="utf-8") as f:
        json.dump({"a": {"n": "1"}}, f)
    assert presets.load_presets() == {"a": {"n": "1"}}
    # 外部写入（尺寸变化，签名必变）
    with open(target, "w", encoding="utf-8") as f:
        json.dump({"b": {"n": "22"}}, f)
    assert presets.load_presets() == {"b": {"n": "22"}}


def test_external_delete_invalidates_cache(tmp_path, monkeypatch):
    target = _isolate(tmp_path, monkeypatch)
    with open(target, "w", encoding="utf-8") as f:
        json.dump({"a": {}}, f)
    assert presets.load_presets() == {"a": {}}
    os.remove(target)
    assert presets.load_presets() == {}


def test_save_refreshes_cache(tmp_path, monkeypatch):
    target = _isolate(tmp_path, monkeypatch)
    presets.save_presets({"p": {"k": "v"}})
    counter = _CountingOpen(target)
    monkeypatch.setattr("builtins.open", counter)
    assert presets.load_presets() == {"p": {"k": "v"}}
    assert counter.reads == 0, "刚写过应直接命中 cache，无需读盘"
    with open(target, "r", encoding="utf-8") as f:
        assert json.load(f) == {"p": {"k": "v"}}


def test_returned_dict_is_a_copy(tmp_path, monkeypatch):
    target = _isolate(tmp_path, monkeypatch)
    with open(target, "w", encoding="utf-8") as f:
        json.dump({"a": {}}, f)
    got = presets.load_presets()
    got["injected"] = 1
    assert presets.load_presets() == {"a": {}}, "调用方改返回值不应污染 cache"


def test_corrupt_then_recover(tmp_path, monkeypatch):
    target = _isolate(tmp_path, monkeypatch)
    with open(target, "w", encoding="utf-8") as f:
        f.write("{ not json")
    assert presets.load_presets() == {}
    with open(target, "w", encoding="utf-8") as f:
        json.dump({"ok": {}}, f)
    assert presets.load_presets() == {"ok": {}}


def test_non_dict_treated_as_empty(tmp_path, monkeypatch):
    target = _isolate(tmp_path, monkeypatch)
    with open(target, "w", encoding="utf-8") as f:
        json.dump([1, 2, 3], f)
    assert presets.load_presets() == {}

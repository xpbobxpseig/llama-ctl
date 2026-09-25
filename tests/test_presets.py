# -*- coding: utf-8 -*-
"""presets.py 单测：读/写/损坏回退/原子写。纯文件模块，不 import tkinter。

覆盖候选 #5 的非平凡逻辑：
- 缺文件 / 损坏 / 非字典 都回退空字典
- 每次 load 都真实读盘（外部改写立刻可见，含同尺寸快速改写）
- save_presets 原子写回，内容可被重新读出
- 返回值是独立对象，改动不污染后续读取
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import presets


def _isolate(tmp_path, monkeypatch):
    """把 PRESETS_FILE 指到临时文件。"""
    target = str(tmp_path / "presets.json")
    monkeypatch.setattr(presets, "PRESETS_FILE", target)
    return target


def test_missing_file_returns_empty(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert presets.load_presets() == {}


def test_loads_existing(tmp_path, monkeypatch):
    target = _isolate(tmp_path, monkeypatch)
    with open(target, "w", encoding="utf-8") as f:
        json.dump({"a": {"n": "1"}}, f)
    assert presets.load_presets() == {"a": {"n": "1"}}


def test_repeated_load_reads_disk_each_time(tmp_path, monkeypatch):
    """无缓存：每次 load 都必须真实读盘（用读文件次数证明）。"""
    target = _isolate(tmp_path, monkeypatch)
    with open(target, "w", encoding="utf-8") as f:
        json.dump({"a": {}}, f)

    reads = []
    real_open = open

    def counting_open(file, *a, **kw):
        if os.path.abspath(str(file)) == os.path.abspath(target):
            reads.append(file)
        return real_open(file, *a, **kw)

    monkeypatch.setattr("builtins.open", counting_open)
    for _ in range(3):
        presets.load_presets()
    assert len(reads) == 3, "无缓存实现每次 load 都应读盘"


def test_external_rewrite_invalidates(tmp_path, monkeypatch):
    target = _isolate(tmp_path, monkeypatch)
    with open(target, "w", encoding="utf-8") as f:
        json.dump({"a": {"n": "1"}}, f)
    assert presets.load_presets() == {"a": {"n": "1"}}
    with open(target, "w", encoding="utf-8") as f:
        json.dump({"b": {"n": "22"}}, f)
    assert presets.load_presets() == {"b": {"n": "22"}}


def test_same_size_same_tick_rewrite_is_seen(tmp_path, monkeypatch):
    """回归：同尺寸内容在同一时间戳刻度内被改写，也必须读到新内容。

    旧实现用 (st_mtime_ns, st_size) 作缓存签名；NTFS 时间戳粒度约 15.6 ms，
    两次等长写入常落在同一刻度 → 签名相同 → 外部改写被静默吞掉。
    "{ not json" 与 {"ok": {}} 都是 10 字节，正是触发该碰撞的形态。
    """
    target = _isolate(tmp_path, monkeypatch)
    with open(target, "w", encoding="utf-8") as f:
        f.write("{ not json")           # 10 B，损坏
    assert presets.load_presets() == {}
    with open(target, "w", encoding="utf-8") as f:
        json.dump({"ok": {}}, f)        # 也是 10 B
    assert presets.load_presets() == {"ok": {}}


def test_external_delete_returns_empty(tmp_path, monkeypatch):
    target = _isolate(tmp_path, monkeypatch)
    with open(target, "w", encoding="utf-8") as f:
        json.dump({"a": {}}, f)
    assert presets.load_presets() == {"a": {}}
    os.remove(target)
    assert presets.load_presets() == {}


def test_save_then_load_roundtrip(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    presets.save_presets({"p": {"k": "v"}})
    assert presets.load_presets() == {"p": {"k": "v"}}


def test_save_is_atomic_leaves_no_tmp(tmp_path, monkeypatch):
    target = _isolate(tmp_path, monkeypatch)
    presets.save_presets({"p": {"k": "v"}})
    assert not os.path.exists(target + ".tmp"), "原子写不应残留 .tmp"


def test_returned_dict_is_a_copy(tmp_path, monkeypatch):
    target = _isolate(tmp_path, monkeypatch)
    with open(target, "w", encoding="utf-8") as f:
        json.dump({"a": {}}, f)
    got = presets.load_presets()
    got["injected"] = 1
    assert presets.load_presets() == {"a": {}}, "调用方改返回值不应落盘"


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

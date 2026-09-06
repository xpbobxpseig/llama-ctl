# -*- coding: utf-8 -*-
"""updater.py 单测：官方 release 解析/资产匹配/zip 处理。纯逻辑模块，不 import tkinter。"""

import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import updater


# ---------------------------------------------------------------------------
# 版本号解析
# ---------------------------------------------------------------------------

def test_parse_build():
    assert updater.parse_build("b10819") == 10819
    assert updater.parse_build("v0.4.0") is None
    assert updater.parse_build("") is None


def test_parse_version_output():
    text = "version: 0.4.0-dev (build 10813, commit 4acf4a4cb)"
    assert updater.parse_version_output(text) == 10813
    assert updater.parse_version_output("version: 1.2.3") is None


# ---------------------------------------------------------------------------
# 资产精确匹配（防误抓 arm64 / 其它 CUDA 版本）
# ---------------------------------------------------------------------------

def _rel(tag, names):
    return {"tag_name": tag, "assets": [{"name": n, "browser_download_url": "https://x/" + n}
                                        for n in names]}


def test_select_assets_exact_match_cuda_13_3():
    rel = _rel("b10819", [
        "nightly-tag.txt",
        "llama-b10819-bin-win-cuda-12.4-x64.zip",
        "llama-b10819-bin-win-cuda-13.3-x64.zip",
        "llama-b10819-bin-win-cuda-13.4-arm64.zip",
        "llama-b10819-bin-win-rocm-10.0-x64.zip",
        "cudart-llama-bin-win-cuda-13.3-x64.zip",
        "cudart-llama-bin-win-cuda-12.4-x64.zip",
    ])
    got = [a["name"] for a in updater.select_assets(rel, "win-cuda-13.3-x64")]
    assert got == ["llama-b10819-bin-win-cuda-13.3-x64.zip",
                   "cudart-llama-bin-win-cuda-13.3-x64.zip"]


def test_select_assets_cpu_single_zip():
    rel = _rel("b10819", [
        "llama-b10819-bin-win-cpu-arm64.zip",
        "llama-b10819-bin-win-cpu-x64.zip",
    ])
    got = [a["name"] for a in updater.select_assets(rel, "win-cpu-x64")]
    assert got == ["llama-b10819-bin-win-cpu-x64.zip"]


def test_select_assets_requires_build_tag():
    assert updater.select_assets(_rel("v0.4.0", ["nightly-tag.txt"]),
                                 "win-cuda-13.3-x64") == []


# ---------------------------------------------------------------------------
# find_latest_release：跳过不含目标资产的 release，取第一个可用的
# ---------------------------------------------------------------------------

def test_find_latest_release_skips_empty_releases(monkeypatch):
    def fake_json(url):
        return [
            {"tag_name": "v0.4.0", "draft": False, "html_url": "https://x/v0.4.0",
             "body": "stable", "published_at": "2026-09-04T00:00:00Z",
             "assets": [{"name": "nightly-tag.txt"}]},
            {"tag_name": "b10819", "draft": False, "html_url": "https://x/b10819",
             "body": "nightly changelog", "published_at": "2026-09-05T00:00:00Z",
             "assets": [{"name": "llama-b10819-bin-win-cuda-13.3-x64.zip",
                         "browser_download_url": "https://x/a.zip"}]},
        ]

    monkeypatch.setattr(updater, "http_json", fake_json)
    rel = updater.find_latest_release("win-cuda-13.3-x64")
    assert rel["tag"] == "b10819"
    assert rel["build"] == 10819
    assert len(rel["assets"]) == 1


def test_find_latest_release_raises_when_no_match(monkeypatch):
    monkeypatch.setattr(updater, "http_json",
                        lambda url: [{"tag_name": "v0.4.0", "draft": False,
                                      "assets": [{"name": "nightly-tag.txt"}]}])
    with pytest.raises(updater.UpdateError):
        updater.find_latest_release("win-cuda-13.3-x64")


# ---------------------------------------------------------------------------
# zip 顶层文件：只取扁平结构，忽略目录与嵌套
# ---------------------------------------------------------------------------

def _make_zip(path, entries):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries.items():
            zf.writestr(name, content)


def test_zip_top_files_ignores_dirs_and_nested(tmp_path):
    zp = str(tmp_path / "a.zip")
    _make_zip(zp, {
        "llama-server.exe": "BIN",
        "ggml.dll": "BIN2",
        "sub/": "",
        "sub/deep.dll": "BIN3",
    })
    assert updater.zip_top_files(zp) == ["ggml.dll", "llama-server.exe"]


def test_collect_conflicts_and_extract(tmp_path):
    zp = str(tmp_path / "a.zip")
    _make_zip(zp, {"new.exe": "NEW", "shared.dll": "NEWDLL", "sub/keep.exe": "X"})
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "shared.dll").write_text("OLD", encoding="utf-8")
    (dest / "old.exe").write_text("OLD", encoding="utf-8")

    assert updater.collect_conflicts([zp], str(dest)) == ["shared.dll"]
    updater.extract_top_level(zp, str(dest))

    assert (dest / "new.exe").read_text(encoding="utf-8") == "NEW"
    assert (dest / "shared.dll").read_text(encoding="utf-8") == "NEWDLL"
    assert (dest / "old.exe").read_text(encoding="utf-8") == "OLD"  # 未受影响
    assert not (dest / "sub").exists()                          # 嵌套不落盘
    assert not os.path.exists(str(dest) + r"\sub\keep.exe")


def test_extract_top_level_failure_leaves_no_half_file(tmp_path, monkeypatch):
    """第二个文件写坏：已写好的文件正常落盘，未写成的目标保持原样。"""
    zp = str(tmp_path / "a.zip")
    _make_zip(zp, {"a.dll": "A", "b.dll": "B"})
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "b.dll").write_text("OLD", encoding="utf-8")

    real_copy = updater.shutil.copyfileobj
    calls = {"n": 0}

    def flaky_copy(src, dst, length=0):
        calls["n"] += 1
        if calls["n"] > 1:
            raise OSError("boom")
        real_copy(src, dst, length)

    monkeypatch.setattr(updater.shutil, "copyfileobj", flaky_copy)
    with pytest.raises(OSError):
        updater.extract_top_level(zp, str(dest))

    assert (dest / "a.dll").read_text(encoding="utf-8") == "A"
    assert (dest / "b.dll").read_text(encoding="utf-8") == "OLD"  # 未被半截覆盖


# ---------------------------------------------------------------------------
# 更新失败回滚（短期清单第 2 条）：备份 / 逐文件恢复 / 新增文件清理
# ---------------------------------------------------------------------------

def test_backup_and_restore_files(tmp_path):
    dest = tmp_path / "dest"
    bak = tmp_path / "bak"
    dest.mkdir()
    (dest / "a.dll").write_text("OLD-A", encoding="utf-8")
    (dest / "b.dll").write_text("OLD-B", encoding="utf-8")

    updater.backup_files(["a.dll", "b.dll"], str(dest), str(bak))
    assert (bak / "a.dll").read_text(encoding="utf-8") == "OLD-A"
    assert (bak / "b.dll").read_text(encoding="utf-8") == "OLD-B"

    (dest / "a.dll").write_text("NEW-A", encoding="utf-8")
    (dest / "b.dll").write_text("NEW-B", encoding="utf-8")
    updater.restore_files(["a.dll", "b.dll"], str(dest), str(bak))

    assert (dest / "a.dll").read_text(encoding="utf-8") == "OLD-A"
    assert (dest / "b.dll").read_text(encoding="utf-8") == "OLD-B"


def test_backup_skips_missing_source(tmp_path):
    """目标文件缺失时跳过（回滚语义：文件本就不存在，无需恢复）。"""
    dest = tmp_path / "dest"
    bak = tmp_path / "bak"
    dest.mkdir()
    updater.backup_files(["missing.dll"], str(dest), str(bak))
    updater.restore_files(["missing.dll"], str(dest), str(bak))
    assert not (dest / "missing.dll").exists()


def test_restore_files_aggregates_errors_and_keeps_going(tmp_path, monkeypatch):
    """单个文件恢复失败不能阻止其余文件继续恢复。"""
    dest = tmp_path / "dest"
    bak = tmp_path / "bak"
    dest.mkdir()
    bak.mkdir()
    (bak / "a.dll").write_text("OLD-A", encoding="utf-8")
    (bak / "b.dll").write_text("OLD-B", encoding="utf-8")

    real_replace = updater.os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if "a.dll" in src and calls["n"] == 1:
            raise OSError("boom")
        real_replace(src, dst)

    monkeypatch.setattr(updater.os, "replace", flaky_replace)
    with pytest.raises(OSError) as ei:
        updater.restore_files(["a.dll", "b.dll"], str(dest), str(bak))
    assert "a.dll" in str(ei.value)
    assert (dest / "b.dll").read_text(encoding="utf-8") == "OLD-B"


def test_remove_files_cleans_added_files(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "new.dll").write_text("NEW", encoding="utf-8")
    (dest / "keep.dll").write_text("KEEP", encoding="utf-8")

    updater.remove_files(["new.dll", "never-existed.dll"], str(dest))

    assert not (dest / "new.dll").exists()
    assert (dest / "keep.dll").read_text(encoding="utf-8") == "KEEP"


def test_extract_one_failure_cleans_temp(tmp_path, monkeypatch):
    """extract_one 写坏时清理 *.llama_ctl_new，目标文件保持原样。"""
    zp = str(tmp_path / "a.zip")
    _make_zip(zp, {"a.dll": "A"})
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "a.dll").write_text("OLD", encoding="utf-8")

    real_copy = updater.shutil.copyfileobj

    def flaky_copy(src, dst, length=0):
        real_copy(src, dst, length)
        raise OSError("boom")

    monkeypatch.setattr(updater.shutil, "copyfileobj", flaky_copy)
    with pytest.raises(OSError):
        updater.extract_one(zp, str(dest), "a.dll")

    assert (dest / "a.dll").read_text(encoding="utf-8") == "OLD"
    assert not os.path.exists(str(dest / "a.dll.llama_ctl_new"))

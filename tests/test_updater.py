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


# ---------------------------------------------------------------------------
# prune_old_subdirs：更新缓存/备份的滚动保留策略
# 安全红线：只删子目录，绝不删普通文件
# ---------------------------------------------------------------------------

def _make_dirs(root, spec):
    """spec: {name: mtime}，建子目录并设 mtime。"""
    for name, mtime in spec.items():
        d = root / name
        d.mkdir()
        (d / "payload.bin").write_text("x", encoding="utf-8")
        os.utime(str(d), (mtime, mtime))
    return root


def test_prune_keeps_newest_n(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    _make_dirs(root, {"old1": 1000, "old2": 2000, "new1": 3000, "new2": 4000})

    removed = updater.prune_old_subdirs(str(root), keep=2)

    assert sorted(removed) == ["old1", "old2"]
    assert sorted(p.name for p in root.iterdir()) == ["new1", "new2"]


def test_prune_never_deletes_plain_files(tmp_path):
    """安全红线：root 下的普通文件必须毫发无损。"""
    root = tmp_path / "downloads"
    root.mkdir()
    (root / "README.txt").write_text("keep me", encoding="utf-8")
    (root / "stray.zip").write_text("keep me too", encoding="utf-8")
    _make_dirs(root, {"a": 1000, "b": 2000, "c": 3000})

    removed = updater.prune_old_subdirs(str(root), keep=1)

    assert sorted(removed) == ["a", "b"]
    assert (root / "README.txt").read_text(encoding="utf-8") == "keep me"
    assert (root / "stray.zip").read_text(encoding="utf-8") == "keep me too"


def test_prune_missing_root_returns_empty(tmp_path):
    assert updater.prune_old_subdirs(str(tmp_path / "nope"), keep=3) == []


def test_prune_keep_zero_deletes_nothing(tmp_path):
    """keep <= 0 不得清空历史（防误调用）。"""
    root = tmp_path / "backup"
    root.mkdir()
    _make_dirs(root, {"a": 1000, "b": 2000})

    assert updater.prune_old_subdirs(str(root), keep=0) == []
    assert sorted(p.name for p in root.iterdir()) == ["a", "b"]


def test_prune_fewer_than_keep_deletes_nothing(tmp_path):
    root = tmp_path / "backup"
    root.mkdir()
    _make_dirs(root, {"only": 1000})

    assert updater.prune_old_subdirs(str(root), keep=3) == []
    assert [p.name for p in root.iterdir()] == ["only"]


def test_prune_default_keep_is_three(tmp_path):
    root = tmp_path / "backup"
    root.mkdir()
    _make_dirs(root, {("d%d" % i): 1000 * i for i in range(1, 6)})

    removed = updater.prune_old_subdirs(str(root))

    assert sorted(removed) == ["d1", "d2"]
    assert sorted(p.name for p in root.iterdir()) == ["d3", "d4", "d5"]


def test_prune_aggregates_errors_without_stopping(tmp_path, monkeypatch):
    """首个删除失败不得中断其余删除；聚合后抛 OSError。"""
    root = tmp_path / "backup"
    root.mkdir()
    _make_dirs(root, {"a": 1000, "b": 2000, "c": 3000})

    real_rmtree = updater.shutil.rmtree

    def flaky_rmtree(path, *a, **kw):
        if os.path.basename(path) == "a":
            raise OSError("locked")
        return real_rmtree(path, *a, **kw)

    monkeypatch.setattr(updater.shutil, "rmtree", flaky_rmtree)
    with pytest.raises(OSError) as ei:
        updater.prune_old_subdirs(str(root), keep=1)
    assert "a" in str(ei.value)
    # b 仍被删掉（未因 a 失败而中断）
    assert sorted(p.name for p in root.iterdir()) == ["a", "c"]


# ---------------------------------------------------------------------------
# 下载完整性：截断不得转正（真实故障回归）
#
# 实测故障：某次主二进制只落地 1,061,602 B（应为 149,703,589 B），因为
# download() 把「连接提前 EOF」与「正常读完」当同一出口，随后无条件
# os.replace 把残缺文件转正；缓存复用又只看 os.path.isfile，于是每次重试
# 都用同一个坏文件，更新永久失败。
# ---------------------------------------------------------------------------

class _FakeResp:
    """伪造 urlopen 响应：可按 Content-Length 与实收字节数制造截断。"""

    def __init__(self, payload, content_length=None):
        self._payload = payload
        self._pos = 0
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    def read(self, n=-1):
        if self._pos >= len(self._payload):
            return b""                      # 模拟连接断开 / 正常读完
        if n is None or n < 0:
            n = len(self._payload) - self._pos
        chunk = self._payload[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _zip_bytes(files):
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_is_valid_zip_accepts_real_zip(tmp_path):
    p = tmp_path / "good.zip"
    p.write_bytes(_zip_bytes({"a.dll": "A"}))
    assert updater.is_valid_zip(str(p)) is True


def test_is_valid_zip_rejects_truncated(tmp_path):
    """真实故障形态：前 1MiB 是合法 zip 头，但整体被截断。"""
    data = _zip_bytes({"a.dll": "A" * 5000})
    p = tmp_path / "trunc.zip"
    p.write_bytes(data[:max(1, len(data) // 3)])
    assert updater.is_valid_zip(str(p)) is False


def test_is_valid_zip_rejects_missing_and_nonzip(tmp_path):
    assert updater.is_valid_zip(str(tmp_path / "nope.zip")) is False
    txt = tmp_path / "plain.zip"
    txt.write_text("not a zip at all", encoding="utf-8")
    assert updater.is_valid_zip(str(txt)) is False


def test_is_valid_zip_never_raises(tmp_path):
    """校验函数不得因损坏/异常输入而抛出（含 None、目录、空路径）。"""
    d = tmp_path / "adir"
    d.mkdir()
    for bad in (None, "", str(d), str(tmp_path / "missing")):
        assert updater.is_valid_zip(bad) is False


def test_download_rejects_truncated_by_content_length(tmp_path, monkeypatch):
    """声明 100 字节、实收 10 字节 → 抛错，且 dest 与 .part 都不存在。"""
    dest = str(tmp_path / "big.zip")
    monkeypatch.setattr(updater, "urlopen",
                        lambda *a, **k: _FakeResp(b"X" * 10, content_length=100))

    with pytest.raises(updater.UpdateError) as ei:
        updater.download("https://x/big.zip", dest)

    assert "不完整" in str(ei.value)
    assert not os.path.exists(dest), "截断产物不得转正为 dest"
    assert not os.path.exists(dest + ".part"), ".part 必须清理"


def test_download_rejects_invalid_zip_when_length_unknown(tmp_path, monkeypatch):
    """Content-Length 不可知 + 内容非 zip → 仍在转正前拦下。"""
    dest = str(tmp_path / "unknown.zip")
    monkeypatch.setattr(updater, "urlopen",
                        lambda *a, **k: _FakeResp(b"garbage-not-a-zip"))

    with pytest.raises(updater.UpdateError) as ei:
        updater.download("https://x/unknown.zip", dest)

    assert not os.path.exists(dest)
    assert not os.path.exists(dest + ".part")


def test_download_happy_path_still_works(tmp_path, monkeypatch):
    """完整下载且长度匹配：正常落地，内容一致（不得回归）。"""
    payload = _zip_bytes({"a.dll": "A", "b.dll": "BB"})
    dest = str(tmp_path / "ok.zip")
    monkeypatch.setattr(updater, "urlopen",
                        lambda *a, **k: _FakeResp(payload, content_length=len(payload)))

    got = updater.download("https://x/ok.zip", dest)

    assert got == dest
    assert os.path.isfile(dest)
    assert open(dest, "rb").read() == payload
    assert not os.path.exists(dest + ".part")
    assert updater.is_valid_zip(dest) is True


def test_download_reports_progress_and_completes(tmp_path, monkeypatch):
    """进度回调仍被调用，且回调次数随分块推进（happy path 行为保持）。"""
    payload = _zip_bytes({"a.dll": "A" * 10})
    dest = str(tmp_path / "p.zip")
    monkeypatch.setattr(updater, "urlopen",
                        lambda *a, **k: _FakeResp(payload, content_length=len(payload)))
    seen = []

    updater.download("https://x/p.zip", dest, progress=lambda d, t: seen.append((d, t)))

    assert seen and seen[-1] == (len(payload), len(payload))

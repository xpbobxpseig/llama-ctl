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


def test_retired_cuda_13_3_channel_is_not_offered():
    """官方已停止产出 13.3（实测 b11201-b11213 只有 12.4 / 13.4）：退役变体必须
    从 CHANNELS 移除，否则 check 永远匹配不到资产（本次故障根因）。"""
    assert "win-cuda-13.4-x64" in updater.CHANNELS
    assert updater.DEFAULT_CHANNEL == "win-cuda-13.4-x64"
    assert "win-cuda-13.3-x64" not in updater.CHANNELS
    assert "win-cuda-13.3-x64" not in updater.CHANNEL_ORDER



# ---------------------------------------------------------------------------
# find_latest_release：跳过没有渠道资产的较新 tag，解析网页下载链接
# ---------------------------------------------------------------------------

def test_find_latest_release_skips_tags_without_channel_assets(monkeypatch):
    pages = {
        updater.RELEASES_PAGE: (
            '<a href="/ggml-org/llama.cpp/releases/tag/b10820">b10820</a>'
            '<a href="/ggml-org/llama.cpp/releases/tag/b10819">b10819</a>'
            '<a href="/ggml-org/llama.cpp/releases/tag/v0.4.0">stable</a>'),
        updater.RELEASES_BASE + "expanded_assets/b10820": (
            '<a href="/ggml-org/llama.cpp/releases/download/b10820/'
            'llama-b10820-bin-win-cpu-x64.zip">CPU</a>'),
        updater.RELEASES_BASE + "expanded_assets/b10819": (
            '<a href="/ggml-org/llama.cpp/releases/download/b10819/'
            'llama-b10819-bin-win-cuda-13.3-x64.zip">binary</a>'
            '<a href="/ggml-org/llama.cpp/releases/download/b10819/'
            'cudart-llama-b10819-bin-win-cuda-13.3-x64.zip">runtime</a>'),
    }
    monkeypatch.setattr(updater, "http_text", lambda url: pages[url])

    rel = updater.find_latest_release("win-cuda-13.3-x64")

    assert rel["tag"] == "b10819"
    assert rel["build"] == 10819
    assert [a["name"] for a in rel["assets"]] == [
        "llama-b10819-bin-win-cuda-13.3-x64.zip",
        "cudart-llama-b10819-bin-win-cuda-13.3-x64.zip",
    ]
    assert rel["assets"][0]["browser_download_url"] == (
        "https://github.com/ggml-org/llama.cpp/releases/download/b10819/"
        "llama-b10819-bin-win-cuda-13.3-x64.zip")


def test_find_latest_release_raises_when_no_matching_assets(monkeypatch):
    pages = {
        updater.RELEASES_PAGE:
            '<a href="/ggml-org/llama.cpp/releases/tag/b10820">b10820</a>',
        updater.RELEASES_BASE + "expanded_assets/b10820":
            '<a href="/ggml-org/llama.cpp/releases/download/b10820/'
            'llama-b10820-bin-win-cpu-x64.zip">CPU</a>',
    }
    monkeypatch.setattr(updater, "http_text", lambda url: pages[url])
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


# ---------------------------------------------------------------------------
# prune_nested_subdirs：backup/{tag}/{时间戳}/ 的两层滚动清理
#
# 根因：备份真实布局是 tag 目录里再套时间戳目录，只对 backup 根做 prune 时
# 被保留的 tag 内部一份都不会清；同一 tag 反复安装（失败重试/回滚重装）会让
# 备份无上限增长（每次约 1.3GB），README 的「保留最近 3 个」不成立。
# ---------------------------------------------------------------------------

def test_prune_nested_keeps_n_per_tag(tmp_path):
    root = tmp_path / "backup"
    for tag in ("b1", "b2"):
        for i in range(1, 6):
            d = root / tag / ("ts%d" % i)
            d.mkdir(parents=True)
            (d / "llama-server.exe").write_bytes(b"x")
            os.utime(d, (1000 * i, 1000 * i))

    removed = updater.prune_nested_subdirs(str(root), keep=3)

    assert len(removed) == 4, "每个 tag 各删 2 份，共 4 份"
    for tag in ("b1", "b2"):
        left = sorted(p.name for p in (root / tag).iterdir())
        assert left == ["ts3", "ts4", "ts5"], "每个 tag 内部应各保留最新 3 份"


def test_prune_nested_never_deletes_files(tmp_path):
    root = tmp_path / "backup"
    (root / "b1" / "ts1").mkdir(parents=True)
    (root / "b1" / "ts2").mkdir(parents=True)
    (root / "keep.txt").write_text("x")
    updater.prune_nested_subdirs(str(root), keep=1)
    assert (root / "keep.txt").is_file(), "普通文件绝不能被删"


def test_prune_nested_missing_root_and_zero_keep(tmp_path):
    assert updater.prune_nested_subdirs(str(tmp_path / "nope"), keep=3) == []
    root = tmp_path / "backup"
    (root / "b1" / "ts1").mkdir(parents=True)
    assert updater.prune_nested_subdirs(str(root), keep=0) == []
    assert (root / "b1" / "ts1").is_dir(), "keep=0 不得删除任何内容"


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



def test_is_valid_zip_rejects_zeroed_entry_data(tmp_path):
    """真实故障形态：中央目录完好（只读 infolist 会判为可用），但条目数据被清零。

    实测：downloads/b11213/cudart-...zip 长度恰好正确（423,535,356 B = 服务端
    Content-Length），中央目录完好，但 92.65% 的字节是 0（一个 392 MB 的连续零区，
    终点正好落在 1 MiB 分块边界）。旧 is_valid_zip 只调 infolist()（读文件末尾的
    索引），于是判为「可用」→ 缓存被永久复用 → 每次解压都在 cublas64_13.dll 上报
    「Bad CRC-32」。校验必须覆盖数据本身。
    """
    payload = b"A" * 20000
    data = bytearray(_zip_bytes_stored({"cublas64_13.dll": payload}))
    # 存储式（无压缩）：载荷在文件中是字面量，直接清零即模拟数据丢失
    at = data.find(payload)
    assert at != -1
    data[at:at + len(payload)] = b"\x00" * len(payload)
    p = tmp_path / "zeroed.zip"
    p.write_bytes(bytes(data))

    with zipfile.ZipFile(str(p)) as zf:
        zf.infolist()                      # 中央目录仍可读（旧判据会误判为有效）

    assert updater.is_valid_zip(str(p)) is False


def _zip_bytes_stored(files):
    """与 _zip_bytes 相同，但用 ZIP_STORED（载荷字面存放，便于精确定位）。"""
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()
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
    """声明 100 字节、实收 10 字节 → 抛错，且 dest 与 .part 都不存在。

    attempts=1：本用例只验证「截断不得转正」，重试行为另有用例覆盖。
    """
    dest = str(tmp_path / "big.zip")
    monkeypatch.setattr(updater, "urlopen",
                        lambda *a, **k: _FakeResp(b"X" * 10, content_length=100))

    with pytest.raises(updater.UpdateError) as ei:
        updater.download("https://x/big.zip", dest, attempts=1)

    assert "不完整" in str(ei.value)
    assert not os.path.exists(dest), "截断产物不得转正为 dest"
    assert not os.path.exists(dest + ".part"), ".part 必须清理"


def test_download_rejects_invalid_zip_when_length_unknown(tmp_path, monkeypatch):
    """Content-Length 不可知 + 内容非 zip → 仍在转正前拦下。"""
    dest = str(tmp_path / "unknown.zip")
    monkeypatch.setattr(updater, "urlopen",
                        lambda *a, **k: _FakeResp(b"garbage-not-a-zip"))

    with pytest.raises(updater.UpdateError):
        updater.download("https://x/unknown.zip", dest, attempts=1)

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


class _FlakyResp:
    """伪造响应：首次只给 part1 就断流，之后支持 Range 续传给剩余部分。

    模拟实测的 CDN 抖动 —— 同一个 URL 连下 5 次有 1 次在传输中途被切断。
    """

    def __init__(self, payload, part1, served):
        self._payload = payload
        self._part1 = part1
        self._served = served          # 已服务过几次（决定本次给多少）
        self._pos = 0
        self._start = 0
        self.headers = {}
        self.status = 200

    def begin(self, range_start):
        """按本次请求的 Range 起点准备响应体与头。

        关键：Content-Length 一律声明**完整**长度——真实断流就是这样发生的
        （实测响应头声明 423,535,356，实际只送达 2,276,115 字节）。若这里声明
        的是短长度，断流就变得「符合声明」而不可检测，等于没模拟。
        """
        self._start = range_start
        self._pos = 0
        full = len(self._payload)
        if range_start:
            self.status = 206
            self.headers["Content-Range"] = (
                "bytes %d-%d/%d" % (range_start, full - 1, full))
            self.headers["Content-Length"] = str(full - range_start)
            body = self._payload[range_start:]
        else:
            self.status = 200
            self.headers["Content-Length"] = str(full)
            body = self._payload
        # 首次只送到 part1 就断流（模拟连接中断）；之后送达完整
        self._body = body if self._served else body[:self._part1]


    def read(self, n=-1):
        if self._pos >= len(self._body):
            return b""
        if n is None or n < 0:
            n = len(self._body) - self._pos
        chunk = self._body[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_download_retries_and_resumes_after_mid_transfer_cut(tmp_path, monkeypatch):
    """实测故障回归：传输中途被切断后，必须重试并**续传**补齐，而不是整次失败。

    真实故障：cudart 只收到 2,276,115 / 423,535,356 字节就断流，旧实现单发
    下载 → 直接抛「下载不完整…请重试」，用户点再多次也可能再次撞上抖动。
    """
    payload = _zip_bytes({"a.dll": "A" * 3000})
    dest = str(tmp_path / "flaky.zip")
    resp = _FlakyResp(payload, part1=1000, served=0)
    calls = {"n": 0}

    def fake_urlopen(req, **kw):
        calls["n"] += 1
        ra = req.headers.get("Range")           # 代码用的 "Range"
        start = 0
        if ra:
            start = int(ra.split("=")[1].split("-")[0])
        resp.begin(start)
        resp._served += 1
        return resp

    monkeypatch.setattr(updater, "urlopen", fake_urlopen)
    got = updater.download("https://x/flaky.zip", dest, attempts=3, backoff=0)

    assert got == dest
    assert open(dest, "rb").read() == payload
    assert calls["n"] == 2, "应重试一次（第 2 次续传补齐）"
    assert not os.path.exists(dest + ".part")


def test_download_resume_restarts_from_zero_when_server_ignores_range(
        tmp_path, monkeypatch):
    """服务端不支持 Range（回 200 而非 206）时必须从头写，不能追加出坏文件。"""
    payload = _zip_bytes({"a.dll": "B" * 3000})
    dest = str(tmp_path / "norange.zip")

    class _NoRange:
        """始终回 200（忽略 Range）并声明**完整**长度，但首次只送 500 字节。"""

        _SHORT = 500

        def __init__(self, served):
            self._served = served
            self._pos = 0
            self.status = 200                  # 始终 200：忽略 Range
            self.headers = {"Content-Length": str(len(payload))}
            self._body = payload if served else payload[:self._SHORT]

        def read(self, n=-1):
            if self._pos >= len(self._body):
                return b""
            if n is None or n < 0:
                n = len(self._body) - self._pos
            c = self._body[self._pos:self._pos + n]
            self._pos += len(c)
            return c

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    state = {"n": 0}

    def fake_urlopen(req, **kw):
        r = _NoRange(state["n"])
        state["n"] += 1
        return r

    monkeypatch.setattr(updater, "urlopen", fake_urlopen)
    got = updater.download("https://x/norange.zip", dest, attempts=3, backoff=0)

    assert got == dest
    assert open(dest, "rb").read() == payload, "不支持续传时必须从头重下"
    assert updater.is_valid_zip(dest) is True


def test_download_exhausts_attempts_then_cleans_up(tmp_path, monkeypatch):
    """重试全部失败：抛最后一次的错误，且 dest 与 .part 都不留。"""
    dest = str(tmp_path / "always_bad.zip")
    calls = {"n": 0}

    def fake_urlopen(req, **kw):
        calls["n"] += 1
        return _FakeResp(b"X" * 10, content_length=999)

    monkeypatch.setattr(updater, "urlopen", fake_urlopen)
    with pytest.raises(updater.UpdateError) as ei:
        updater.download("https://x/big.zip", dest, attempts=3, backoff=0)

    assert "不完整" in str(ei.value)
    assert calls["n"] == 3, "应按 attempts 次数重试"
    assert not os.path.exists(dest)
    assert not os.path.exists(dest + ".part")


def test_download_rejects_full_length_but_corrupt_content(tmp_path, monkeypatch):
    """长度恰好相符但内容损坏（清零）的样本不得转正。

    实测故障：中央目录完好、长度逐字节等于 Content-Length，但 92.65% 的字节是 0，
    解压时 CRC 失败。只信长度会把它转正成缓存并永久复用，所以长度相符后仍必须
    做内容校验。
    """
    good = _zip_bytes_stored({"cublas64_13.dll": b"A" * 20000})
    at = good.find(b"A" * 20000)
    corrupt = bytearray(good)
    corrupt[at:at + 20000] = b"\x00" * 20000        # 清零数据，长度不变
    dest = str(tmp_path / "corrupt.zip")

    monkeypatch.setattr(updater, "urlopen",
                        lambda *a, **k: _FakeResp(bytes(corrupt),
                                                  content_length=len(corrupt)))
    with pytest.raises(updater.UpdateError) as ei:
        updater.download("https://x/corrupt.zip", dest, attempts=2, backoff=0)

    assert "校验失败" in str(ei.value)
    assert not os.path.exists(dest), "长度对但内容坏的文件不得转正"
    assert not os.path.exists(dest + ".part")


def test_download_keeps_partial_file_across_attempts(tmp_path, monkeypatch):
    """一次中断后，下一次必须发 Range 续传（而不是从头重下）。"""
    payload = _zip_bytes({"a.dll": "C" * 5000})
    dest = str(tmp_path / "resume.zip")
    sent = {"first": False}
    ranges = []

    class _Once:
        def __init__(self, body, status, cl):
            self._b = body
            self._p = 0
            self.status = status
            self.headers = {"Content-Length": str(cl)}

        def read(self, n=-1):
            if self._p >= len(self._b):
                return b""
            if n is None or n < 0:
                n = len(self._b) - self._p
            c = self._b[self._p:self._p + n]
            self._p += len(c)
            return c

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, **kw):
        ranges.append(req.headers.get("Range"))
        if not sent["first"]:
            sent["first"] = True
            # 声明完整长度，却只给前 1000 字节 → 中断
            return _Once(payload[:1000], 200, len(payload))
        start = 1000
        return _Once(payload[start:], 206, len(payload) - start)

    monkeypatch.setattr(updater, "urlopen", fake_urlopen)
    got = updater.download("https://x/resume.zip", dest, attempts=3, backoff=0)

    assert got == dest
    assert open(dest, "rb").read() == payload
    assert ranges == [None, "bytes=1000-"], "第二次必须从断点续传"


# ---------------------------------------------------------------------------
# 回归：残留 .part 不得让下载陷入「删数据 → 必然 416」的死循环
#
# 根因：total 已知时若 done >= total，旧实现清 .part 却不清 total，于是下一轮
# 发出 `Range: bytes=<总长>-`。真实 CDN 对「起始偏移 == 文件长度」返回 416
# （对 b11213 主二进制实测：bytes=152343958- → HTTP 416），10 次尝试全打在
# 这个必然失败的请求上，最后把其实已经完整的数据删掉。
# ---------------------------------------------------------------------------

def test_download_promotes_already_complete_part_without_network(tmp_path, monkeypatch):
    """.part 已完整且是有效 zip → 直接转正，0 次网络请求（上次被杀/转正失败的形态）。"""
    payload = _zip_bytes({"a.dll": "D" * 20000})
    dest = str(tmp_path / "complete.zip")
    with open(dest + ".part", "wb") as fh:
        fh.write(payload)                     # 长度与内容都正确，但没转正

    def boom(*a, **k):
        raise AssertionError("已完整的 .part 不该再发起任何网络请求")

    monkeypatch.setattr(updater, "urlopen", boom)
    got = updater.download("https://x/complete.zip", dest, attempts=3, backoff=0)

    assert got == dest
    assert open(dest, "rb").read() == payload
    assert not os.path.exists(dest + ".part")


def test_download_recovers_from_416_instead_of_looping(tmp_path, monkeypatch):
    """.part 抵达 EOF 语义（起点==总长）时服务端回 416：必须丢弃重下，不得死循环。"""
    payload = _zip_bytes({"a.dll": "E" * 20000})
    dest = str(tmp_path / "at416.zip")
    log = []

    class _Resp:
        def __init__(self, status, body, cl):
            self.status, self._b, self._p = status, body, 0
            self.headers = {"Content-Length": str(cl)}

        def read(self, n=-1):
            if self._p >= len(self._b):
                return b""
            if n is None or n < 0:
                n = len(self._b) - self._p
            c = self._b[self._p:self._p + n]
            self._p += len(c)
            return c

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, **kw):
        rng = req.headers.get("Range")
        start = int(rng.split("=")[1].rstrip("-")) if rng else 0
        log.append(start)
        if start >= len(payload):            # 真实 CDN 行为
            raise updater.HTTPError("https://x", 416, "Range Not Satisfiable", {},
                                    __import__("io").BytesIO(b""))
        if start:
            return _Resp(206, payload[start:], len(payload) - start)
        return _Resp(200, payload, len(payload))

    # 残留一个「长度等于远端」的 .part（内容其实已完整）：首次进入 total 未知，
    # 若直接续传会撞 416；修复后必须能自愈。
    with open(dest + ".part", "wb") as fh:
        fh.write(payload)
    monkeypatch.setattr(updater, "urlopen", fake_urlopen)

    got = updater.download("https://x/at416.zip", dest, attempts=3, backoff=0)

    assert got == dest
    assert open(dest, "rb").read() == payload
    assert sum(1 for s in log if s >= len(payload)) <= 1, "416 不得反复出现"

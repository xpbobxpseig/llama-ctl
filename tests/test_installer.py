# -*- coding: utf-8 -*-
"""installer.py 单测：更新安装事务序列的成功/失败/回滚路径。

纯逻辑模块（不 import tkinter）。用假 deps 记录调用、假 sink 收集日志，
在无 UI、无网络、无 Windows 服务的环境下跑完整条事务路径。

覆盖候选 #6 的非平凡逻辑：
- 成功路径：下载→停→备份→替换→启→报告新 build
- 坏缓存：删除重下；重下仍坏则中止
- 停服失败：直接抛，不进备份/替换
- 备份失败：未替换任何文件，且尽力重启服务
- 替换失败：按 replaced 精确回滚 + 删除新增文件 + 重启收尾
- 启动未达 RUNNING：回滚 + 重启收尾
- 空 conflicts（更新包不匹配）：恢复服务后中止
- 已 STOPPED 时失败：_try_restart_service 会拉起服务
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import installer
from updater import UpdateError


class FakeDeps:
    """记录调用的假依赖。用 flags 控制每一步的行为。"""

    def __init__(self, **flags):
        self.flags = flags
        self.calls = []
        self.state = flags.get("state", "STOPPED")
        self.valid = flags.get("valid", True)
        self.conflicts = flags.get("conflicts", ["llama-server.exe"])
        self.zip_names = flags.get("zip_names", ["llama-server.exe"])
        self.build = flags.get("build", 4583)

    # --- 记录辅助 ---
    def _rec(self, *a):
        self.calls.append(a)

    def is_valid_zip(self, path):
        self._rec("is_valid_zip", path)
        return self.valid

    def download(self, url, dest, progress=None):
        self._rec("download", url, dest)
        if self.flags.get("download_fail"):
            raise OSError("network down")
        if progress:
            progress(1, 4)  # 25%

    def collect_conflicts(self, zips, target):
        self._rec("collect_conflicts", tuple(zips), target)
        if self.flags.get("collect_fail"):
            raise OSError("bad zip")
        return list(self.conflicts)

    def backup_files(self, names, target, bak):
        self._rec("backup_files", tuple(names), target, bak)
        if self.flags.get("backup_fail"):
            raise OSError("disk full")

    def zip_top_files(self, zp):
        self._rec("zip_top_files", zp)
        if self.flags.get("zip_fail"):
            raise OSError("corrupt zip")
        return list(self.zip_names)

    def extract_one(self, zp, target, name):
        self._rec("extract_one", zp, target, name)
        if self.flags.get("extract_fail") == name:
            raise OSError("cannot write %s" % name)

    def restore_files(self, names, target, bak):
        self._rec("restore_files", tuple(names), target, bak)
        if self.flags.get("restore_fail"):
            raise OSError("no backup")

    def remove_files(self, names, target):
        self._rec("remove_files", tuple(names), target)

    def get_installed_build(self, exe):
        self._rec("get_installed_build", exe)
        return self.build

    def query_state(self, service):
        self._rec("query_state", service)
        return self.state

    def action(self, verb, service):
        self._rec("action", verb, service)
        if self.flags.get("stop_fail") and verb == "stop":
            return False, "denied"
        if verb == "start":
            if self.flags.get("start_fail"):
                return False, "denied"
            self.state = "RUNNING"
        if verb == "stop":
            self.state = "STOPPED"
        return True, "ok"

    # --- 断言辅助 ---
    def called(self, name):
        return [c for c in self.calls if c[0] == name]


def _rel():
    return {
        "tag": "b4583",
        "assets": [
            {"name": "llama-win.zip", "browser_download_url": "http://x/llama-win.zip"},
        ],
    }


def _install(tmp_path, deps, **kw):
    sink = []
    installer.install(
        _rel(), "QwenLLM", str(tmp_path / "target"), str(tmp_path / "bak"),
        sink.append, str(tmp_path / "dl"), deps=deps,
    )
    return sink


# ---------------------------------------------------------------- 成功路径
def test_success_sequence(tmp_path, monkeypatch):
    # 预置一个「已缓存且有效」的资产，避免真下载
    deps = FakeDeps(state="RUNNING")   # 运行中才会走停服分支
    monkeypatch.setattr(installer.os.path, "isfile", lambda p: p.endswith("llama-win.zip"))
    sink = _install(tmp_path, deps)

    assert deps.called("backup_files")
    assert deps.called("extract_one")
    assert ("action", "stop", "QwenLLM") in deps.calls
    assert ("action", "start", "QwenLLM") in deps.calls
    assert "__REFRESH_STATUS__" in sink
    assert any("更新完成" in s or "Update complete" in s for s in sink)


def test_success_reports_build_from_binary(tmp_path, monkeypatch):
    deps = FakeDeps(build=4583)
    monkeypatch.setattr(installer.os.path, "isfile", lambda p: p.endswith("llama-win.zip"))
    sink = _install(tmp_path, deps)
    assert deps.called("get_installed_build")
    assert any("b4583" in s for s in sink)


def test_cached_asset_reused(tmp_path, monkeypatch):
    deps = FakeDeps()
    monkeypatch.setattr(installer.os.path, "isfile", lambda p: True)
    sink = _install(tmp_path, deps)
    assert not deps.called("download")
    assert any("(cached)" in s for s in sink)


# ---------------------------------------------------------------- 下载失败
def test_bad_cache_deleted_and_redownloaded(tmp_path, monkeypatch):
    deps = FakeDeps(valid=False)
    removing = []

    def fake_isfile(p):
        return True

    monkeypatch.setattr(installer.os.path, "isfile", fake_isfile)
    monkeypatch.setattr(installer.os, "remove", lambda p: removing.append(p))
    # 重下后仍无效 → 中止，且不触碰备份/替换
    with pytest.raises(UpdateError):
        _install(tmp_path, deps)
    assert removing  # 坏缓存被删
    assert deps.called("download")
    assert not deps.called("backup_files")


def test_download_failure_cleans_partials(tmp_path, monkeypatch):
    deps = FakeDeps(download_fail=True)
    removed = []
    monkeypatch.setattr(installer.os.path, "isfile", lambda p: False)
    monkeypatch.setattr(installer.os, "remove", lambda p: removed.append(p))
    monkeypatch.setattr(installer, "RealDeps", lambda: deps)
    with pytest.raises(UpdateError):
        installer.install(_rel(), "QwenLLM", "t", "b", lambda s: None, "d")
    assert len(removed) == 2  # dest 与 dest.part
    assert not deps.called("backup_files")


# ---------------------------------------------------------------- 停服失败
def test_stop_failure_aborts(tmp_path, monkeypatch):
    deps = FakeDeps(state="RUNNING", stop_fail=True)
    monkeypatch.setattr(installer.os.path, "isfile", lambda p: True)
    monkeypatch.setattr(installer, "time", _NoSleepTime())
    with pytest.raises(UpdateError):
        _install(tmp_path, deps)
    assert not deps.called("backup_files")
    assert not deps.called("extract_one")
# ---------------------------------------------------------------- 备份失败
def test_backup_failure_restarts_and_aborts(tmp_path, monkeypatch):
    deps = FakeDeps(backup_fail=True)
    monkeypatch.setattr(installer.os.path, "isfile", lambda p: True)
    monkeypatch.setattr(installer, "time", _NoSleepTime())
    sink = []
    with pytest.raises(UpdateError):
        installer.install(_rel(), "QwenLLM", "t", "b", sink.append, "d", deps=deps)
    assert not deps.called("extract_one")
    # 服务被停止后备份失败 → 尽力拉起
    assert ("action", "start", "QwenLLM") in deps.calls


def test_empty_conflicts_restarts_and_aborts(tmp_path, monkeypatch):
    deps = FakeDeps(conflicts=[])
    monkeypatch.setattr(installer.os.path, "isfile", lambda p: True)
    monkeypatch.setattr(installer, "time", _NoSleepTime())
    with pytest.raises(UpdateError):
        _install(tmp_path, deps)
    assert ("action", "start", "QwenLLM") in deps.calls


def test_extract_failure_rolls_back_replaced(tmp_path, monkeypatch):
    # 目标目录已有 llama-server.exe（替换）；extra.dll 是新增；new.dll 写入失败
    deps = FakeDeps(extract_fail="new.dll",
                    zip_names=["llama-server.exe", "extra.dll", "new.dll"])
    monkeypatch.setattr(installer, "time", _NoSleepTime())

    def fake_isfile(p):
        s = str(p)
        return s.endswith("llama-server.exe") or s.endswith("llama-win.zip")

    monkeypatch.setattr(installer.os.path, "isfile", fake_isfile)
    with pytest.raises(OSError):
        _install(tmp_path, deps)
    # 已替换的旧文件被回滚，已新增的文件被删除
    assert deps.called("restore_files")
    assert deps.called("remove_files")
    assert deps.called("restore_files")[0][1] == ("llama-server.exe",)
    assert deps.called("remove_files")[0][1] == ("extra.dll",)


def test_zip_listing_failure_restarts(tmp_path, monkeypatch):
    deps = FakeDeps(zip_fail=True)
    monkeypatch.setattr(installer.os.path, "isfile", lambda p: True)
    monkeypatch.setattr(installer, "time", _NoSleepTime())
    with pytest.raises(UpdateError):
        _install(tmp_path, deps)
    assert ("action", "start", "QwenLLM") in deps.calls


# ---------------------------------------------------------------- 启动失败
def test_start_not_running_rolls_back(tmp_path, monkeypatch):
    deps = FakeDeps(start_fail=True,
                    zip_names=["llama-server.exe", "new.dll"])

    def fake_isfile(p):
        s = str(p)
        return s.endswith("llama-server.exe") or s.endswith("llama-win.zip")

    monkeypatch.setattr(installer.os.path, "isfile", fake_isfile)
    monkeypatch.setattr(installer, "time", _NoSleepTime())
    with pytest.raises(UpdateError):
        _install(tmp_path, deps)
    assert deps.called("restore_files")   # 回滚旧的 llama-server.exe
    assert deps.called("remove_files")    # 删除新增的 new.dll


# ---------------------------------------------------------------- 回滚自身健壮性
def test_rollback_failure_does_not_raise(tmp_path):
    deps = FakeDeps(restore_fail=True)
    sink = []
    # 不抛：回滚失败只写日志
    installer.rollback_files(["a.dll"], "t", "b", sink.append, deps)
    assert deps.called("restore_files")
    assert any("回滚失败" in s or "Rollback failed" in s for s in sink)


def test_remove_added_failure_does_not_raise():
    class Bad(FakeDeps):
        def remove_files(self, names, target):
            raise OSError("locked")

    sink = []
    installer.remove_added_files(["x.dll"], "t", sink.append, Bad())
    assert any("回滚失败" in s or "Rollback failed" in s for s in sink)


# ---------------------------------------------------------------- 辅助
class _NoSleepTime:
    """替换 installer.time：sleep 变成 no-op，保持其余属性透传。"""

    def __getattr__(self, name):
        import time as _t
        return getattr(_t, name)

    def sleep(self, _s):
        pass


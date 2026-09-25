# -*- coding: utf-8 -*-
"""nssm_adapter.ServiceFacts 单测（C1）：

静态事实注册表直读 + 按服务缓存；写回后失效；缓存命中 0 spawn。

用注入的 fake reader 替代真注册表——不需要管理员权限、不需要本机存在该服务。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import nssm_adapter as n


class _Fake:
    """计数版内存 reader：记录读取次数，可按服务名给值或模拟缺失。"""

    def __init__(self, data):
        self.data = data
        self.reads = []

    def __call__(self, service):
        self.reads.append(service)
        return self.data.get(service)


def _install(fake, monkeypatch):
    n.invalidate()
    monkeypatch.setattr(n, "_reader", fake)
    monkeypatch.setattr(n, "_spawn_count", 0, raising=False)


def test_registry_read_no_spawn_and_cache_hit(monkeypatch):
    """facts() 走注册表：0 spawn；第二次命中缓存，不再读 reader。"""
    fake = _Fake({"S": {"app_dir": r"D:\x", "app_params": "-m a.gguf", "start": 3}})
    _install(fake, monkeypatch)

    assert n.facts("S")["app_dir"] == r"D:\x"
    assert n.facts("S")["app_params"] == "-m a.gguf"
    assert n.facts("S")["start"] == "manual"          # DWORD 3 → DEMAND
    assert fake.reads == ["S"]                        # 只读一次
    assert n._spawn_count == 0                        # Q1 硬指标：0 次 spawn

    # 旧接口签名不变，且同样命中缓存
    assert n.app_directory("S") == r"D:\x"
    assert n.get_app_parameters("S") == "-m a.gguf"
    assert n.get_start_mode("S") == "manual"
    assert fake.reads == ["S"]
    assert n._spawn_count == 0


def test_start_dword_mapping(monkeypatch):
    """Start DWORD 映射：2=auto / 3=manual / 4=disabled；未知值与无值回退。"""
    for dword, expect in ((2, "auto"), (3, "manual"), (4, "disabled"), (7, "manual")):
        fake = _Fake({"S": {"app_dir": None, "app_params": "", "start": dword}})
        _install(fake, monkeypatch)
        assert n.get_start_mode("S") == expect

    fake = _Fake({"S": {"app_dir": None, "app_params": "", "start": None}})
    _install(fake, monkeypatch)
    assert n.get_start_mode("S") == "manual"


def test_invalidate_per_service(monkeypatch):
    """invalidate(service) 只失效该服务；另一个服务仍命中缓存。"""
    fake = _Fake({
        "A": {"app_dir": r"D:\a", "app_params": "-m a", "start": 3},
        "B": {"app_dir": r"D:\b", "app_params": "-m b", "start": 2},
    })
    _install(fake, monkeypatch)

    n.facts("A")
    n.facts("B")
    assert sorted(fake.reads) == ["A", "B"]

    n.invalidate("A")
    n.facts("A")
    n.facts("B")
    assert fake.reads == ["A", "B", "A"]              # 只有 A 重读
    assert n.get_start_mode("B") == "auto"            # B 仍是缓存值


def test_fallback_to_nssm_when_registry_unavailable(monkeypatch):
    """reader 返回 None（非 NSSM 服务 / 权限不足）时回退 nssm get。"""
    _install(_Fake({}), monkeypatch)
    calls = []

    def fake_get(service, param, sub=None):
        calls.append(param)
        return {"AppDirectory": r"E:\ll", "AppParameters": "-m z",
                "Start": "SERVICE_AUTO_START"}.get(param)

    monkeypatch.setattr(n, "nssm_get", fake_get)
    snap = n.facts("S")
    assert snap == {"app_dir": r"E:\ll", "app_params": "-m z", "start": "auto"}
    assert "AppDirectory" in calls and "Start" in calls


def test_write_invalidates_only_on_success(monkeypatch):
    """写回成功后失效缓存；失败时保留缓存（Q9）。"""
    fake = _Fake({"S": {"app_dir": None, "app_params": "-m old", "start": 3}})
    _install(fake, monkeypatch)
    assert n.get_app_parameters("S") == "-m old"

    written = {}

    def fake_set(service, param, value, sub=None):
        written[param] = value
        return written.get("_ok", True), "ok"

    monkeypatch.setattr(n, "nssm_set", fake_set)

    # 失败：缓存仍在，不发失效
    written["_ok"] = False
    assert n.set_app_parameters("S", "-m new") == (False, "ok")
    assert n.get_app_parameters("S") == "-m old"
    assert fake.reads == ["S"]

    # 成功：下次读重新走注册表
    fake.data["S"] = {"app_dir": None, "app_params": "-m new", "start": 3}
    written["_ok"] = True
    ok, _ = n.set_app_parameters("S", "-m new")
    assert ok
    assert n.get_app_parameters("S") == "-m new"
    assert fake.reads == ["S", "S"]


def test_set_start_mode_maps_and_invalidates(monkeypatch):
    """set_start_mode 传 nssm 枚举值，并在成功后失效。"""
    fake = _Fake({"S": {"app_dir": None, "app_params": "", "start": 3}})
    _install(fake, monkeypatch)
    assert n.get_start_mode("S") == "manual"

    seen = []

    def fake_set(service, param, value, sub=None):
        seen.append((param, value))
        return True, "ok"

    monkeypatch.setattr(n, "nssm_set", fake_set)
    fake.data["S"] = {"app_dir": None, "app_params": "", "start": 2}
    n.set_start_mode("S", "auto")
    assert seen == [("Start", "SERVICE_AUTO_START")]
    assert n.get_start_mode("S") == "auto"

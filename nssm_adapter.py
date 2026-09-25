#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nssm_adapter.py — 服务事实与控制 adapter（llama_ctl）

把本机 NSSM / 注册表 / Windows sc / powershell / HTTP 探活收拢为一个 deep module，
GUI 层只依赖这里的函数 interface；测试可用 monkeypatch 替换任意函数。

ServiceFacts（C1）：静态事实（AppDirectory / AppParameters / Start）走注册表直读
（0 次 spawn，微秒级），按服务名缓存快照；写回后 invalidate 该服务。未配置 /
注册表不可读时回退 nssm get。

本机固定事实：NSSM 路径与默认服务名。
"""

import re
import subprocess
from urllib.request import urlopen
from urllib.error import URLError

try:
    import winreg
except ImportError:  # 非 Windows：注册表直读不可用，一律回退 nssm get
    winreg = None

# ---------------------------------------------------------------------------
# 本机固定事实
# ---------------------------------------------------------------------------
NSSM_EXE = r"F:\llama.cpp\nssm\nssm-2.24\win64\nssm.exe"
DEFAULT_SERVICE = "QwenLLM"


def _run(cmd, timeout=15):
    """跑命令，返回 (returncode, stripped_stdout)。

    NSSM 输出为 UTF-16LE（每字符后带 \\x00）；sc 等系统命令为本地代码页（GBK）。
    按字节特征自动解码。
    """
    global _spawn_count
    _spawn_count += 1
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        raw = p.stdout or b""
        if len(raw) >= 2 and raw[1:2] == b"\x00":
            try:
                out = raw.decode("utf-16-le", errors="replace").replace("\x00", "")
            except Exception:
                out = raw.decode("mbcs", errors="replace")
        else:
            try:
                out = raw.decode("mbcs", errors="replace")
            except Exception:
                out = raw.decode("utf-8", errors="replace")
        return p.returncode, out.strip()
    except Exception as exc:  # noqa: BLE001
        return -1, f"执行失败: {exc}"


def nssm_get(service, param, sub=None):
    cmd = [NSSM_EXE, "get", service, param]
    if sub:
        cmd.append(sub)
    rc, out = _run(cmd)
    return out if rc == 0 else None


def nssm_set(service, param, value, sub=None):
    cmd = [NSSM_EXE, "set", service, param]
    if sub:
        cmd.append(sub)
    cmd.append(value)
    rc, out = _run(cmd)
    return rc == 0, out


# ---------------------------------------------------------------------------
# ServiceFacts（C1）：静态事实 = 注册表直读 + 按服务缓存
# ---------------------------------------------------------------------------
# 注册表位置：服务键下的 Parameters 子键存 AppDirectory / AppParameters /
# Application；Start（DWORD）在服务键本身。
_SVC_KEY = r"SYSTEM\CurrentControlSet\Services\%s"
_PARAMS_KEY = _SVC_KEY + r"\Parameters"

# 静态事实缓存：service -> {"app_dir","app_params","start"}。
# 读侧微秒级且无 spawn；写侧（nssm set）后按 key invalidate。
_facts_cache = {}

# _run 每次真实 spawn 计数（只增不减）。测试用于断言空闲主线程 spawn=0/s。
_spawn_count = 0


def _read_facts_registry(service):
    """注册表直读静态事实；键/值缺失或不可读时返回 None（不回退）。"""
    if winreg is None:
        return None
    out = {"app_dir": None, "app_params": None, "start": None}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _PARAMS_KEY % service) as k:
            out["app_dir"] = winreg.QueryValueEx(k, "AppDirectory")[0] or None
            out["app_params"] = winreg.QueryValueEx(k, "AppParameters")[0]
    except OSError:
        return None  # 服务不存在 / 无 Parameters 子键：交由调用方回退
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _SVC_KEY % service) as k:
            out["start"] = winreg.QueryValueEx(k, "Start")[0]
    except OSError:
        pass
    return out


# 注入点：测试替换为内存 fake，无需管理员权限 / 本机真存在该服务。
_reader = _read_facts_registry


def facts(service, refresh=False):
    """返回服务的静态事实 dict（AppDirectory / AppParameters / Start）。

    首次或 refresh=True 时经注册表直读（0 spawn）；注册表不可用则回退 nssm get
    （每次一个进程，但仍进缓存）。命中缓存时不 spawn、不读注册表。
    """
    if not refresh and service in _facts_cache:
        return _facts_cache[service]
    reg = _reader(service)
    if reg is None:
        # 回退：非 NSSM 服务 / 权限不足 / 非 Windows
        snap = {
            "app_dir": nssm_get(service, "AppDirectory") or None,
            "app_params": nssm_get(service, "AppParameters") or "",
            "start": _start_from_nssm(nssm_get(service, "Start")),
        }
    else:
        snap = {
            "app_dir": reg["app_dir"],
            "app_params": reg["app_params"] or "",
            "start": _start_label(reg["start"]),
        }
    _facts_cache[service] = snap
    return snap


def invalidate(service=None):
    """写回成功后失效缓存：service 为 None 时清空全部。"""
    if service is None:
        _facts_cache.clear()
    else:
        _facts_cache.pop(service, None)


def _start_label(raw):
    """注册表 Start(DWORD) → auto/manual/disabled；未知值回退 manual。"""
    return {2: "auto", 3: "manual", 4: "disabled"}.get(raw, "manual")


def _start_from_nssm(raw):
    """nssm get Start 文本（SERVICE_AUTO_START 等）→ auto/manual/disabled。"""
    if raw is None:
        return None
    if "AUTO" in raw:
        return "auto"
    if "DEMAND" in raw or "MANUAL" in raw:
        return "manual"
    if "DISABLED" in raw:
        return "disabled"
    return "manual"


def get_app_parameters(service):
    """服务当前 AppParameters 文本（注册表直读，命中缓存不 spawn）。"""
    return facts(service)["app_params"]


def set_app_parameters(service, text):
    ok, out = nssm_set(service, "AppParameters", text)
    if ok:
        invalidate(service)  # 写后失效：下次读回注册表，与 nssm 规范化结果一致
    return ok, out


def app_directory(service):
    """返回服务的 AppDirectory，供 GUI 推导日志路径（取代硬编码）。

    未配置（None / 空串）时返回 None。
    """
    return facts(service)["app_dir"]


def get_start_mode(service):
    """服务启动模式：auto / manual / disabled（注册表 Start 直读）。"""
    return facts(service)["start"]


# NSSM set Start 仅接受这些完整大写枚举值
_NSSM_START_MAP = {
    "auto": "SERVICE_AUTO_START",
    "manual": "SERVICE_DEMAND_START",
    "disabled": "SERVICE_DISABLED",
}


def set_start_mode(service, mode):
    ok, out = nssm_set(service, "Start", _NSSM_START_MAP.get(mode, mode))
    if ok:
        invalidate(service)
    return ok, out


def sc_query_state(service):
    rc, out = _run(["sc", "query", service])
    if rc != 0:
        return "UNKNOWN"
    m = re.search(r"STATE\s*:\s*\d+\s+(\w+)", out)
    return m.group(1) if m else "UNKNOWN"


def sc_action(action, service):
    rc, out = _run(["sc", action, service])
    return rc == 0, (out or "").strip()


def list_nssm_services():
    """列出本机所有 NSSM 管理的服务名（NSSM 服务其 bin 路径含 nssm）。"""
    names = []
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             'Get-CimInstance Win32_Service | Where-Object { $_.PathName -like "*nssm*" } | ForEach-Object { $_.Name }'],
            capture_output=True, text=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
        names = [l.strip() for l in out.splitlines() if l.strip()]
    except Exception:  # noqa: BLE001
        pass
    if DEFAULT_SERVICE not in names:
        names.insert(0, DEFAULT_SERVICE)
    return names


def check_health(host, port):
    """GET /health（旧构建为 /healthz）。返回 (ok: bool, detail: str)。

    host 为空或 0.0.0.0 / :: 这类通配地址时回退到 127.0.0.1
    （Windows 上直接连 http://0.0.0.0:port 常失败）。
    """
    if not port:
        return False, "无 port"
    # 空 host / 通配地址统一回退环回地址
    probe_host = "127.0.0.1" if (host or "") in ("", "0.0.0.0", "::") else host
    base = f"http://{probe_host}:{port}"
    for path in ("/health", "/healthz"):
        try:
            with urlopen(base + path, timeout=3) as r:
                body = r.read(200).decode("utf-8", "replace").strip()
                return True, f"{r.status} {body}"
        except URLError as e:
            # 404 类错误换下一个候选路径；连接拒绝则直接失败
            if getattr(e, "code", None) == 404:
                continue
            return False, f"连接失败: {e.reason}"
        except Exception as e:  # noqa: BLE001
            return False, f"错误: {e}"
    return False, "无可用健康端点"

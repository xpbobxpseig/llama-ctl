#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nssm_adapter.py — 服务控制与探测 adapter（llama_ctl）

把本机 NSSM / Windows sc / powershell / HTTP 探活收拢为一个 deep module，
GUI 层只依赖这里的函数 interface；测试可用 monkeypatch 替换任意函数。

本机固定事实：NSSM 路径与默认服务名。
"""

import re
import subprocess
from urllib.request import urlopen
from urllib.error import URLError

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


def get_app_parameters(service):
    return nssm_get(service, "AppParameters") or ""


def set_app_parameters(service, text):
    return nssm_set(service, "AppParameters", text)


def app_directory(service):
    """返回服务的 AppDirectory，供 GUI 推导日志路径（取代硬编码）。

    未配置（None / 空串）时返回 None。
    """
    val = nssm_get(service, "AppDirectory")
    return val if val else None


def get_start_mode(service):
    raw = nssm_get(service, "Start")
    if raw is None:
        return None
    if "AUTO" in raw:
        return "auto"
    if "DEMAND" in raw or "MANUAL" in raw:
        return "manual"
    if "DISABLED" in raw:
        return "disabled"
    return "manual"


# NSSM set Start 仅接受这些完整大写枚举值
_NSSM_START_MAP = {
    "auto": "SERVICE_AUTO_START",
    "manual": "SERVICE_DEMAND_START",
    "disabled": "SERVICE_DISABLED",
}


def set_start_mode(service, mode):
    return nssm_set(service, "Start", _NSSM_START_MAP.get(mode, mode))


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

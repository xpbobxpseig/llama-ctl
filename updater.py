#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
updater.py — llama.cpp 官方更新检查与安装（llama_ctl）

纯逻辑模块（不 import tkinter），GUI 层只调用这里的函数：
  - find_latest_release(channel)  从 ggml-org/llama.cpp 官方 releases 找最新构建
  - select_assets(release, channel) 精确匹配该构建的 Windows 二进制 zip 资产
  - get_installed_build(exe)      运行 llama-server.exe --version 解析本地 build 号
  - download / collect_conflicts / extract_top_level  下载、备份清单、解压替换

官方 nightly 发布规律（2026-09）：
  - 最新稳定 release（如 v0.4.0）只挂 nightly-tag.txt，真正的二进制挂在
    b10819 / b10818 … 等 nightly tag 上，故按 per_page 列表顺序找第一个
    含匹配资产的 release。
  - Windows CUDA 版拆成两个 zip：主二进制 llama-bNNNNN-bin-win-cuda-13.3-x64.zip
    与 CUDA 运行时 cudart-llama-bin-win-cuda-13.3-x64.zip；CPU/Vulkan 只有一个 zip。
"""

import json
import os
import re
import shutil
import subprocess
import zipfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases"
USER_AGENT = "llama_ctl-updater/1.0"

# 二进制变体（channel 即资产名中的 -bin- 后缀段；下拉展示 label）
CHANNELS = {
    "win-cuda-13.3-x64": "CUDA 13.3 (x64)",
    "win-cuda-12.4-x64": "CUDA 12.4 (x64)",
    "win-cpu-x64": "CPU (x64)",
    "win-vulkan-x64": "Vulkan (x64)",
}
CHANNEL_ORDER = list(CHANNELS.keys())
DEFAULT_CHANNEL = "win-cuda-13.3-x64"


class UpdateError(Exception):
    """更新流程中可预期失败（网络 / 资产缺失 / 校验不通过）。"""


def http_json(url, timeout=25):
    """GET 并解析 JSON。支持可选 GITHUB_TOKEN 环境变量缓解 API 限流（60 次/时）。

    限流（403/429）时抛 UpdateError 并附 token 提示，GUI 可直接展示。
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
    }
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = "Bearer " + token
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except HTTPError as exc:
        hint = ("（GitHub API 限流：可设置环境变量 GITHUB_TOKEN 后重试）"
                if exc.code in (403, 429) else "")
        raise UpdateError("官方接口 HTTP %s %s" % (exc.code, hint)) from exc
    except URLError as exc:
        raise UpdateError("网络错误：%s" % getattr(exc, "reason", exc)) from exc
    return json.loads(raw.decode("utf-8"))


def parse_build(tag):
    """从 release tag（如 b10819）解析 build 号。"""
    m = re.search(r"b(\d+)", tag or "")
    return int(m.group(1)) if m else None


def parse_version_output(text):
    """从 llama-server --version 输出解析 build 号。

    输出形如：version: 0.4.0-dev (build 10813, commit 4acf4a4cb)
    实测该行由进程写到 stderr，因此调用方须合并 stdout+stderr。
    """
    m = re.search(r"build\s+(\d+)", text or "")
    return int(m.group(1)) if m else None


def get_installed_build(exe_path):
    """运行 exe --version 取本地 build 号；失败/缺失返回 None。"""
    if not exe_path or not os.path.isfile(exe_path):
        return None
    try:
        proc = subprocess.run(
            [exe_path, "--version"], capture_output=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        text = ((proc.stdout or b"").decode("utf-8", "replace") + "\n"
                + (proc.stderr or b"").decode("utf-8", "replace"))
        return parse_version_output(text)
    except Exception:  # noqa: BLE001 - 解析失败按「未知版本」处理
        return None


def select_assets(release, channel):
    """从 release 里精确挑出该 channel 需要的 zip（缺失某项就只挑存在的）。

    资产命名精确匹配，避免误抓 arm64 / 其它 CUDA 版本：
      - cudart-llama-bin-{channel}.zip        （CUDA 运行时，仅 cuda channel 有）
      - llama-b{build}-bin-{channel}.zip      （主二进制）
    """
    tag = release.get("tag_name") or ""
    build = parse_build(tag)
    if not build:
        return []
    wanted = {
        "llama-b%d-bin-%s.zip" % (build, channel),
        "cudart-llama-bin-%s.zip" % channel,
    }
    picked = []
    for asset in release.get("assets") or []:
        name = asset.get("name") or ""
        if name in wanted:
            picked.append(asset)
    return picked


def find_latest_release(channel):
    """找第一个包含该 channel 资产的非草稿 release。

    返回 dict(tag/name/html_url/body/build/assets/published_at)；找不到抛
    UpdateError（网络错误原样上抛，由 GUI 统一显示）。
    """
    releases = http_json(REPO_API + "?per_page=30")
    if not isinstance(releases, list):
        raise UpdateError("官方接口返回格式异常")
    for rel in releases:
        if rel.get("draft"):
            continue
        assets = select_assets(rel, channel)
        if assets:
            build = parse_build(rel.get("tag_name") or "")
            return {
                "tag": rel.get("tag_name") or "",
                "name": rel.get("name") or rel.get("tag_name") or "",
                "html_url": rel.get("html_url") or "",
                "body": rel.get("body") or "",
                "build": build,
                "published_at": rel.get("published_at") or "",
                "assets": assets,
            }
    raise UpdateError("未找到匹配的官方发布资产（channel: %s）" % channel)


def download(url, dest, progress=None):
    """流式下载到 dest（先写 .part 再原子改名）。progress(done, total)。"""
    req = Request(url, headers={"User-Agent": USER_AGENT})
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    tmp = dest + ".part"
    with urlopen(req, timeout=60) as resp:
        total = 0
        try:
            total = int(resp.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            total = 0
        done = 0
        with open(tmp, "wb") as fh:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if progress and total > 0:
                    progress(done, total)
    os.replace(tmp, dest)
    return dest


def zip_top_files(zip_path):
    """官方 zip 为扁平结构：只取顶层文件条目（排除目录与嵌套路径）。"""
    names = set()
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename
            if "/" in name or "\\" in name:
                continue
            names.add(name)
    return sorted(names)


def collect_conflicts(zip_paths, dest_dir):
    """返回解压时会覆盖的现存文件列表（供备份）。"""
    names = set()
    for zp in zip_paths:
        names.update(zip_top_files(zp))
    return sorted(n for n in names
                  if os.path.isfile(os.path.join(dest_dir, n)))


def extract_one(zip_path, dest_dir, name):
    """把 zip 内单个顶层文件写入 dest_dir（先写 *.llama_ctl_new 再原子替换）。

    与 extract_top_level 分离：更新流程需要逐个追踪已替换文件，
    以便失败时按文件级精确回滚。写坏时清理临时文件后重抛。
    """
    tmp = os.path.join(dest_dir, name + ".llama_ctl_new")
    try:
        with zipfile.ZipFile(zip_path) as zf:
            with zf.open(name) as src, open(tmp, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
        os.replace(tmp, os.path.join(dest_dir, name))
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def extract_top_level(zip_path, dest_dir):
    """把 zip 顶层文件逐个写入 dest_dir（先写 *.llama_ctl_new 再 os.replace，
    任一文件写坏不会留下半截文件）。"""
    for name in zip_top_files(zip_path):
        extract_one(zip_path, dest_dir, name)


def backup_files(names, dest_dir, backup_dir):
    """把 dest_dir 中将被覆盖的文件逐个备份到 backup_dir。

    采用先写临时文件再 rename 的原子写，任一文件写坏不会留下半截备份；
    失败抛 OSError（调用方此时尚未替换任何目标文件，直接中止即可）。
    """
    os.makedirs(backup_dir, exist_ok=True)
    for name in names:
        src = os.path.join(dest_dir, name)
        if not os.path.isfile(src):
            continue
        tmp = os.path.join(backup_dir, name + ".llama_ctl_new")
        shutil.copy2(src, tmp)
        os.replace(tmp, os.path.join(backup_dir, name))


def restore_files(names, dest_dir, backup_dir):
    """从 backup_dir 恢复 dest_dir 中被替换过的文件（更新失败回滚）。

    以原子写逐个恢复；任一文件失败继续尝试其余文件，最后聚合错误
    抛 OSError——绝不因单个文件失败而停止恢复其余文件。
    """
    os.makedirs(dest_dir, exist_ok=True)
    errors = []
    for name in names:
        src = os.path.join(backup_dir, name)
        if not os.path.isfile(src):
            continue
        try:
            tmp = os.path.join(dest_dir, name + ".llama_ctl_old")
            shutil.copy2(src, tmp)
            os.replace(tmp, os.path.join(dest_dir, name))
        except OSError as exc:  # noqa: BLE001 - 聚合后统一抛出
            errors.append("%s: %s" % (name, exc))
    if errors:
        raise OSError("; ".join(errors))


def remove_files(names, dest_dir):
    """删除更新新增的文件（回滚时清理此前不存在的顶层文件）。

    缺失视为已删除；任一失败继续处理其余文件，最后聚合错误抛 OSError。
    """
    errors = []
    for name in names:
        try:
            os.remove(os.path.join(dest_dir, name))
        except FileNotFoundError:
            pass
        except OSError as exc:  # noqa: BLE001 - 聚合后统一抛出
            errors.append("%s: %s" % (name, exc))
    if errors:
        raise OSError("; ".join(errors))


def prune_old_subdirs(root, keep=3):
    """只保留 root 下 mtime 最新的 keep 个子目录，删除其余，返回被删目录名。

    用于更新缓存（downloads/{tag}/）与备份（backup/{tag}/{时间戳}/）的滚动清理：
    这两处每装一次就新增一个目录，长期堆积可达 GB 级。

    安全边界：
      - **只处理子目录**；root 下的普通文件一律不动（绝不删文件）。
      - root 不存在 → 返回 []（首次运行尚无缓存属正常）。
      - keep <= 0 → 不删除任何内容，返回 []（防误调用清空历史）。
    失败按 remove_files 的风格聚合错误后抛 OSError，不在首个失败处中断。
    """
    if keep <= 0 or not root or not os.path.isdir(root):
        return []
    try:
        entries = [e for e in os.scandir(root) if e.is_dir()]
    except OSError as exc:
        raise OSError("扫描失败 %s: %s" % (root, exc)) from exc
    # mtime 降序；mtime 相同时按名降序，保证结果稳定可测
    entries.sort(key=lambda e: (e.stat().st_mtime, e.name), reverse=True)
    removed = []
    errors = []
    for entry in entries[keep:]:
        try:
            shutil.rmtree(entry.path)
            removed.append(entry.name)
        except OSError as exc:  # noqa: BLE001 - 聚合后统一抛出
            errors.append("%s: %s" % (entry.name, exc))
    if errors:
        raise OSError("; ".join(errors))
    return removed

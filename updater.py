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
  - Releases 网页先列 nightly tag，再展开每个 tag 的资产；按页面顺序找到
    第一个包含所选 Windows 二进制的构建。
  - Windows CUDA 版拆成主二进制与 CUDA 运行时两个 zip；CPU/Vulkan 只有主二进制 zip。
"""

import os
import re
import shutil
import subprocess
import zipfile
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen

RELEASES_PAGE = "https://github.com/ggml-org/llama.cpp/releases"
RELEASES_BASE = "https://github.com/ggml-org/llama.cpp/releases/"
USER_AGENT = "llama_ctl-updater/1.0"

# 二进制变体（channel 即资产名中的 -bin- 后缀段；下拉展示 label）
#
# 必须镜像官方实际发布的变体：官方停止产出某个 CUDA 版本后，该 channel 会
# 永远匹配不到资产。曾以 win-cuda-13.3-x64 为默认，官方改发 13.4 后弃用了
# 13.3（实测 b11201-b11213 只剩 cuda-12.4 / cuda-13.4 / cuda-13.4-arm64），
# 而旧 settings.json 仍存着 13.3，于是每次检查都报「未找到匹配资产」。
# 退役变体一律从这里删除：_upd_channel() 会把不在表内的持久化值回退到默认。
CHANNELS = {
    "win-cuda-13.4-x64": "CUDA 13.4 (x64)",
    "win-cuda-12.4-x64": "CUDA 12.4 (x64)",
    "win-cpu-x64": "CPU (x64)",
    "win-vulkan-x64": "Vulkan (x64)",
}
CHANNEL_ORDER = list(CHANNELS.keys())
DEFAULT_CHANNEL = "win-cuda-13.4-x64"


class UpdateError(Exception):
    """更新流程中可预期失败（网络 / 资产缺失 / 校验不通过）。"""


def http_text(url, timeout=25):
    """GET 网页并返回 UTF-8 文本；使用 GitHub 网页端，不依赖 API token。"""
    req = Request(url, headers={"User-Agent": USER_AGENT,
                                "Accept": "text/html"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")
    except HTTPError as exc:
        raise UpdateError("GitHub Releases 页面 HTTP %s" % exc.code) from exc
    except URLError as exc:
        raise UpdateError("网络错误：%s" % getattr(exc, "reason", exc)) from exc


def _page_links(html):
    """提取网页中的链接；HTMLParser 会处理属性引号与 HTML 实体。"""
    class LinkParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.links = []

        def handle_starttag(self, tag, attrs):
            if tag == "a":
                href = dict(attrs).get("href")
                if href:
                    self.links.append(href)

    parser = LinkParser()
    parser.feed(html)
    return parser.links



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
        "cudart-llama-b%d-bin-%s.zip" % (build, channel),
    }
    picked = []
    for asset in release.get("assets") or []:
        name = asset.get("name") or ""
        if name in wanted:
            picked.append(asset)
    return picked


def find_latest_release(channel):
    """从 GitHub Releases 网页找第一个包含所选渠道资产的 nightly。"""
    page = http_text(RELEASES_PAGE)
    tags = []
    for href in _page_links(page):
        match = re.fullmatch(r"/ggml-org/llama\.cpp/releases/tag/([^/?#]+)",
                             urlparse(href).path)
        tag = unquote(match.group(1)) if match else ""
        if tag and parse_build(tag) and tag not in tags:
            tags.append(tag)
    for tag in tags[:30]:
        assets_page = http_text(urljoin(RELEASES_BASE,
                                        "expanded_assets/" + tag))
        assets = []
        for href in _page_links(assets_page):
            path = urlparse(href).path
            match = re.fullmatch(
                r"/ggml-org/llama\.cpp/releases/download/([^/]+)/([^/]+)", path)
            if not match or unquote(match.group(1)) != tag:
                continue
            name = unquote(match.group(2))
            assets.append({"name": name, "browser_download_url":
                           urljoin("https://github.com", href)})
        assets = select_assets({"tag_name": tag, "assets": assets}, channel)
        if assets:
            return {
                "tag": tag,
                "name": tag,
                "html_url": urljoin(RELEASES_BASE, "tag/" + tag),
                "body": "",
                "build": parse_build(tag),
                "published_at": "",
                "assets": assets,
            }
    raise UpdateError("GitHub Releases 页面中未找到匹配资产（channel: %s）"
                      % channel)


def is_valid_zip(path):
    """path 是否为可用的 zip：**逐条目校验数据**，而非只读中央目录。

    供缓存复用前校验：坏缓存必须能被识别出来，否则一次数据损坏会让更新**永久
    失败**（每次重试都拿同一个坏文件）。任何异常一律返回 False，绝不抛出——校验
    函数的调用方不应因为「文件损坏」本身而崩溃。

    为什么必须读到数据（两起实测故障）：
      1. 截断：文件被截短，中央目录（在文件末尾）根本读不到。
      2. 清零：长度恰好等于服务端 Content-Length、中央目录也完好，但 92.65% 的
         字节成了 0（一个 392 MB 的连续零区）。此时 `infolist()` 完全正常，旧实现
         因此判为「可用」→ 缓存被永久复用 → 每次解压都在 cublas64_13.dll 上报
         「Bad CRC-32 for file」。只有 testzip()（逐条目解压并核对 CRC）能发现。
    """
    try:
        if not path or not os.path.isfile(path):
            return False
        with zipfile.ZipFile(path) as zf:
            return zf.testzip() is None   # 真正读取每个条目并核对 CRC
    except Exception:  # noqa: BLE001 - 损坏/权限/IO 一律视为不可用
        return False

def download(url, dest, progress=None):
    """流式下载到 dest（先写 .part 再原子改名）。progress(done, total)。

    完整性（关键）：`resp.read()` 在**连接提前断开**时返回空串，与「正常读完」
    走同一出口。若不加校验就 os.replace，残缺文件会被转正成「已下载」并被缓存
    复用，导致更新永久失败（实测：某次主二进制只落地 1,061,602 B / 应为
    149,703,589 B，此后每次重试都复用该坏文件）。
    故：
      - Content-Length 可知 → 校验 done == total，不足即抛 UpdateError；
      - Content-Length 不可知 → 用 is_valid_zip 兜底校验产物。
    失败路径必须清理 .part，且绝不产出 dest。
    """
    req = Request(url, headers={"User-Agent": USER_AGENT})
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    tmp = dest + ".part"

    def _cleanup_tmp():
        try:
            os.remove(tmp)
        except OSError:
            pass

    try:
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
        # 长度可知：字节数不符即连接被截断（或服务端声明有误），不得转正
        if total > 0 and done != total:
            _cleanup_tmp()
            raise UpdateError(
                "下载不完整：%s 收到 %d / %d 字节（连接中断），已丢弃，请重试"
                % (os.path.basename(dest), done, total))
        # 长度不可知：退回内容校验，确保产物真是可用 zip
        if total <= 0 and not is_valid_zip(tmp):
            _cleanup_tmp()
            raise UpdateError(
                "下载内容校验失败：%s 不是有效的 zip（可能被截断），已丢弃，请重试"
                % os.path.basename(dest))
        os.replace(tmp, dest)
    except UpdateError:
        raise
    except Exception:  # noqa: BLE001 - 任何中断都不留可被误认为成品的残留
        _cleanup_tmp()
        raise
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

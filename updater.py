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
import time
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

def download(url, dest, progress=None, attempts=10, backoff=1.5):
    """流式下载到 dest（先写 .part 再原子改名）。progress(done, total)。

    完整性（关键）：`resp.read()` 在**连接提前断开**时返回空串，与「正常读完」
    走同一出口。若不加校验就 os.replace，残缺文件会被转正成「已下载」并被缓存
    复用，导致更新永久失败（实测：某次主二进制只落地 1,061,602 B / 应为
    149,703,589 B）。
    故长度相符之外**还要验内容**：实测有一份文件长度逐字节等于 Content-Length、
    中央目录也完好，但 92.65% 的字节是 0，只信长度就会把它转正成缓存，之后每次
    解压都在 cublas64_13.dll 上报 Bad CRC-32。长度已知不足 → 中断；否则一律
    is_valid_zip()（逐条目 CRC）无误才转正。转正前绝不产出 dest。

    重试 + 断点续传（关键）：候选 CDN（release-assets.githubusercontent.com）
    实测**间歇性中断**——同一 URL 连下 5 次有 1 次被切断（另有 1 次拖到 226s），
    是链路/CDN 抖动而非服务端问题。单发下载会让一次抖动直接毁掉整次更新，故
    本函数自带重试（attempts 次，逐次退避）；服务端支持 Range（实测 206），
    重试时**从已有字节续传**，不必重下整个 400 MB。重试尽数失败才抛 UpdateError
    （附最后一条原因），并清理 .part、绝不产出 dest。
    """
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    tmp = dest + ".part"

    def _cleanup_tmp():
        try:
            os.remove(tmp)
        except OSError:
            pass

    last_err = None
    total = 0            # 目标总长（首次响应已知后固定，供续传判断）
    done = 0             # 已落盘字节（续传时从 .part 现有长度起步）
    for attempt in range(max(1, attempts)):
        if attempt:
            time.sleep(min(backoff * attempt, 8))   # 退避：1.5s,3s,4.5s…（测试传 0）
        try:
            if os.path.isfile(tmp):
                done = os.path.getsize(tmp)
            else:
                done = 0
            # 已知总长时，残留 .part 若已达/超过总长，说明是上一轮的坏样本
            # （长度对但内容坏，如清零文件）——不能拿它续传，从头来。
            # 注意必须**同时清掉 total**：否则下一轮仍按旧总长判断，会发出
            # `Range: bytes=<总长>-` 这种必然 416 的请求（实测真实 CDN 对
            # 起始偏移==文件长度返回 416），把已完整落盘的数据删掉后反复空转。
            if total > 0 and done >= total:
                _cleanup_tmp()
                done = 0
                total = 0
            # 首次进入（total 未知）而 .part 恰好等于远端长度时，上面的分支不会
            # 触发；此时 Range 起点 == EOF 会 416。用 HEAD 语义无法便宜地拿到长度，
            # 故在 416 时把 total 归零重来（见下方 HTTPError 处理）。
            # 首次进入时 total 未知，无法用长度判断 .part 是否已完整。此时若直接
            # 发 `Range: bytes=<总长>-`，真实 CDN 会回 416（实测：起始偏移等于
            # 文件长度即 416），于是这份其实**已经完整**的数据被下面的失败分支
            # 删掉、再反复空转。故：remaining_unknown 时先不续传，改为先验内容——
            # 已是有效 zip 就直接转正（0 次网络请求），否则从头下。
            if done and total <= 0 and is_valid_zip(tmp):
                os.replace(tmp, dest)
                return dest
            headers = {"User-Agent": USER_AGENT}
            if done:
                headers["Range"] = "bytes=%d-" % done   # 续传
            req = Request(url, headers=headers)
            with urlopen(req, timeout=60) as resp:
                # 206 才是真续传；服务端不支持时会回 200 并从头发，必须从头写。
                if done and getattr(resp, "status", 200) != 206:
                    _cleanup_tmp()
                    done = 0
                    mode = "wb"
                else:
                    mode = "ab" if done else "wb"
                if total <= 0:
                    total = _content_length(resp, done)
                with open(tmp, mode) as fh:
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
                last_err = UpdateError(
                    "下载不完整：%s 收到 %d / %d 字节（连接中断），将从断点继续重试"
                    % (os.path.basename(dest), done, total))
                continue          # 保留 .part 供下次续传（不清空，避免重下 400 MB）
            # 长度相符也必须验内容：长度对但字节被清零的坏样本真实发生过
            # （实测：长度逐字节等于 Content-Length，中央目录完好，92.65% 是 0）。
            # 只信长度会把这个坏文件转正成缓存，之后每次解压都 CRC 失败。
            if not is_valid_zip(tmp):
                last_err = UpdateError(
                    "下载内容校验失败：%s 不是有效的 zip（可能被截断或损坏），已丢弃，请重试"
                    % os.path.basename(dest))
                _cleanup_tmp()    # 内容不对，留着也没法续传
                done = 0
                continue
            os.replace(tmp, dest)
            return dest
        except Exception as exc:  # noqa: BLE001 - 网络/IO 抖动一律重试
            last_err = exc
            # 416：Range 起点已到/超过文件末尾，说明 .part 其实已完整（首次进入
            # 时 total 未知，上面的 to-verify 分支漏掉了这种）。丢掉重下，
            # 而不是反复发同一个必然失败的请求（旧实现会把重建后的 total 又设上，
            # 陷入「删数据 → 再 416」的死循环）。
            if getattr(exc, "code", None) == 416:
                _cleanup_tmp()
                done = 0
                total = 0
            continue
    _cleanup_tmp()                # 重试尽数失败：不留可被误认为成品的残留
    if isinstance(last_err, UpdateError):
        raise last_err
    raise UpdateError("下载失败：%s（%s）请重试"
                      % (os.path.basename(dest), last_err))


def _content_length(resp, already):
    """响应声明的**总**长度；续传（206）时它是剩余长度，需加上已有字节。

    取不到返回 0（调用方退回内容校验）。
    """
    try:
        n = int(resp.headers.get("Content-Length") or 0)
    except (TypeError, ValueError):
        return 0
    if n <= 0:
        return 0
    return n + already if getattr(resp, "status", 200) == 206 else n


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


def prune_nested_subdirs(root, keep=3):
    """对 root 下每个 tag 目录，再各保留其内部最新的 keep 个子目录。

    备份真实布局是 `backup/{tag}/{时间戳}/`（GUI 按 tag 建目录、每次安装新建
    一个时间戳子目录）。只对 backup 根做 prune 时，被保留的 tag 目录内部的
    历史时间戳一个都不会被清——同一 tag 反复安装（失败重试 / 回滚后重装）
    会让备份无上限增长（每次约 1.3 GB），README 承诺的「保留最近 3 个」不成立。

    只删目录、绝不删文件；root 不存在返回 []；任何单个 tag 失败不影响其它。
    """
    if keep <= 0 or not root or not os.path.isdir(root):
        return []
    removed = []
    errors = []
    try:
        tags = [e for e in os.scandir(root) if e.is_dir()]
    except OSError as exc:
        raise OSError("扫描失败 %s: %s" % (root, exc)) from exc
    for tag in tags:
        try:
            for name in prune_old_subdirs(tag.path, keep=keep):
                removed.append(os.path.join(tag.name, name))
        except OSError as exc:  # noqa: BLE001 - 聚合后统一抛出
            errors.append("%s: %s" % (tag.name, exc))
    if errors:
        raise OSError("; ".join(errors))
    return removed


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

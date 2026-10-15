#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""presets.py — 命名参数组合持久化（llama_ctl）

与 settings.py 同模式：用户目录固定路径、原子写、损坏回退空字典。

存放位置（issue 00；Rust 侧照搬同一约定，见 .scratch/tauri2-migration/issues/00）：
    %APPDATA%\\llama-ctl\\presets.json
环境变量 LLAMA_CTL_PRESETS 优先级更高，设置后完全不走用户目录。
"""

import json
import os
import shutil

USER_DATA_DIRNAME = "llama-ctl"        # %APPDATA% 下的子目录名
PRESETS_BASENAME = "presets.json"

# 旧版本写在程序目录下的位置：仅作迁移来源，迁移后不再读取。
LEGACY_PRESETS_FILE = r"F:\llama_ctl\presets.json"


def user_data_dir():
    """llama_ctl 的用户数据目录：%APPDATA%\\llama-ctl\\

    只用环境变量判定，不绑定某套 Windows API（Rust 侧 std::env::var("APPDATA")
    可直接照搬）：APPDATA 缺失时退回 %USERPROFILE%\\AppData\\Roaming。
    """
    appdata = os.environ.get("APPDATA")
    if not appdata:
        appdata = os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    return os.path.join(appdata, USER_DATA_DIRNAME)


def _migrate_legacy_file(legacy, target):
    """用户目录无文件、旧路径有文件 → 复制过去，旧文件保留（不删除）。

    迁移是尽力而为：读不到旧文件就当全新安装起步，失败一律静默——首次启动
    不该因为「迁移没成」弹错或中断。
    """
    if os.path.exists(target) or not os.path.isfile(legacy):
        return
    try:
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        shutil.copy2(legacy, target)
    except OSError:
        pass


def resolve_presets_file():
    """返回 presets.json 的最终路径：LLAMA_CTL_PRESETS > 用户目录。

    走用户目录时顺带做一次迁移（见 _migrate_legacy_file）。
    """
    override = os.environ.get("LLAMA_CTL_PRESETS")
    if override:
        return override
    target = os.path.join(user_data_dir(), PRESETS_BASENAME)
    _migrate_legacy_file(LEGACY_PRESETS_FILE, target)
    return target


# 预设文件：存命名参数组合（含全部字段 values），独立于具体服务。
# 路径可用环境变量 LLAMA_CTL_PRESETS 覆盖（便于跨机器部署）；默认落在用户目录，
# 不依赖程序安装位置，exe 换目录/升级后仍读写同一份，避免预设丢失与双副本分裂。
PRESETS_FILE = resolve_presets_file()


def load_presets():
    """读取预设字典 {name: {key: value}}。文件不存在/损坏/非字典返回空字典。

    每次真实读盘：文件是本工具与用户手工编辑共用的落点，任何基于
    mtime+size 的进程内缓存都会漏判「同一时间戳刻度内等长改写」
    （NTFS 时间戳粒度约 15.6 ms），把外部改动静默吞掉。整份读 + json.load
    约 47 µs，一次预设点击至多 2-3 次，不值得为它冒数据不一致的风险。
    """
    try:
        with open(PRESETS_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)
    except Exception:  # noqa: BLE001
        return {}
    return loaded if isinstance(loaded, dict) else {}


def save_presets(presets):
    """写回预设字典到 PRESETS_FILE（原子写：先临时文件再替换）。

    返回 (ok, err)：不抛异常。调用方是 Tk 回调与 GUI 的簿记步骤，抛出会让
    「参数已写回服务」之后的动作被跳过（真实故障：presets.json 被占用时，
    重启被连带跳过，服务仍在跑旧参数）。失败信息交给调用方决定如何提示。
    """
    tmp = PRESETS_FILE + ".tmp"
    try:
        os.makedirs(os.path.dirname(PRESETS_FILE) or ".", exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(presets, f, ensure_ascii=False, indent=2)
        os.replace(tmp, PRESETS_FILE)
        return True, ""
    except OSError as exc:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False, str(exc)

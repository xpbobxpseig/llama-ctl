#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
settings.py — 工具偏好持久化（llama_ctl）

语言/外观/窗口几何/最后预设名/动效总开关。与 presets.json 同模式：用户目录固定路径、
原子写、损坏回退默认值。

存放位置（issue 00；Rust 侧照搬同一约定，见 .scratch/tauri2-migration/issues/00）：
    %APPDATA%\\llama-ctl\\settings.json
环境变量 LLAMA_CTL_SETTINGS 优先级更高，设置后完全不走用户目录。
"""

import json
import os
import shutil

USER_DATA_DIRNAME = "llama-ctl"        # %APPDATA% 下的子目录名
SETTINGS_BASENAME = "settings.json"

# 旧版本写在程序目录下的位置：仅作迁移来源，迁移后不再读取。
LEGACY_SETTINGS_FILE = r"F:\llama_ctl\settings.json"


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


def resolve_settings_file():
    """返回 settings.json 的最终路径：LLAMA_CTL_SETTINGS > 用户目录。

    走用户目录时顺带做一次迁移（见 _migrate_legacy_file）。
    """
    override = os.environ.get("LLAMA_CTL_SETTINGS")
    if override:
        return override
    target = os.path.join(user_data_dir(), SETTINGS_BASENAME)
    _migrate_legacy_file(LEGACY_SETTINGS_FILE, target)
    return target


SETTINGS_FILE = resolve_settings_file()

DEFAULTS = {
    "language": "zh",        # "zh" | "en"
    "appearance": "system",  # "system" | "light" | "dark"
    "geometry": None,        # "WxH+X+Y" 字符串，None = 系统默认
    "last_preset": "",       # 最后选中的预设名
    "motion_enabled": True,   # 动效总开关（design-guide §五：关闭后动画直跳终态）
    "upd_check_on_startup": True,  # 启动时后台自动检查官方更新（仅提示，绝不自动安装）
    "upd_channel": "win-cuda-13.4-x64",  # 官方二进制变体（updater.CHANNELS 的键）
    "services": [],          # 上次枚举到的 nssm 服务名，供首帧下拉先渲染（#3 启动骨架）
}


def load_settings():
    """读取设置；缺文件/损坏/类型不符的键逐项回退默认。"""
    merged = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for k in DEFAULTS:
                if k in data and isinstance(data[k], type(DEFAULTS[k]) if DEFAULTS[k] is not None else str):
                    merged[k] = data[k]
    except FileNotFoundError:
        pass
    except Exception:  # noqa: BLE001
        pass
    return merged


def save_settings(settings):
    """写回设置（原子写：先临时文件再替换）。未知键忽略。

    返回 (ok, err)：**不抛异常**。调用方全是 Tk 控件回调，抛出的
    FileNotFoundError（目录被移走/只读）会直接冒泡进 Tk 事件循环；而打包是
    console=False，用户看不到任何堆栈，只表现为「设置看着生效、下次启动又
    变回去」。故此处收敛为返回值，由调用方决定是否提示。
    """
    out = {k: settings.get(k, DEFAULTS[k]) for k in DEFAULTS}
    tmp = SETTINGS_FILE + ".tmp"
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE) or ".", exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SETTINGS_FILE)
        return True, ""
    except OSError as exc:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False, str(exc)

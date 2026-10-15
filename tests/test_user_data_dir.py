# -*- coding: utf-8 -*-
"""用户目录解析与旧路径迁移（issue 00）单测。

钉住三件非平凡的事，Rust 侧（07）照搬时的契约全在这里：
- 路径约定：%APPDATA%\\llama-ctl\\<basename>，只用 env 判定，不绑 Windows API；
- 迁移规则：用户目录无文件 + 旧路径有文件 → 复制过去，旧文件保留；
- 优先级：LLAMA_CTL_SETTINGS / LLAMA_CTL_PRESETS 最高，且覆盖时不做迁移。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import presets
import settings as S


def _appdata(tmp_path, monkeypatch):
    """把 APPDATA 指到临时目录，并返回该目录。"""
    root = tmp_path / "AppData" / "Roaming"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("APPDATA", str(root))
    monkeypatch.delenv("LLAMA_CTL_PRESETS", raising=False)
    monkeypatch.delenv("LLAMA_CTL_SETTINGS", raising=False)
    return root


def _legacy(tmp_path, monkeypatch, module, const, basename, data):
    """造一个旧路径文件，并把模块的 LEGACY_* 常量指过去。返回其路径。"""
    legacy = tmp_path / "legacy" / basename
    legacy.parent.mkdir(parents=True, exist_ok=True)
    with open(legacy, "w", encoding="utf-8") as f:
        json.dump(data, f)
    monkeypatch.setattr(module, const, str(legacy))
    return legacy


# ---------------------------------------------------------------------------
# 路径约定
# ---------------------------------------------------------------------------

def test_user_data_dir_is_appdata_llama_ctl(tmp_path, monkeypatch):
    root = _appdata(tmp_path, monkeypatch)
    assert presets.user_data_dir() == str(root / "llama-ctl")
    assert S.user_data_dir() == presets.user_data_dir(), "两个模块必须落在同一目录"


def test_user_data_dir_falls_back_without_appdata(tmp_path, monkeypatch):
    """APPDATA 缺失 → %USERPROFILE%\\AppData\\Roaming。"""
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert presets.user_data_dir() == str(tmp_path / "AppData" / "Roaming" / "llama-ctl")


def test_resolve_defaults_to_user_dir(tmp_path, monkeypatch):
    root = _appdata(tmp_path, monkeypatch)
    assert presets.resolve_presets_file() == str(root / "llama-ctl" / "presets.json")
    assert S.resolve_settings_file() == str(root / "llama-ctl" / "settings.json")


def test_resolve_without_legacy_creates_nothing(tmp_path, monkeypatch):
    """全新安装：解析路径不得顺手建目录/文件。"""
    root = _appdata(tmp_path, monkeypatch)
    monkeypatch.setattr(presets, "LEGACY_PRESETS_FILE", str(tmp_path / "nope.json"))
    presets.resolve_presets_file()
    assert not (root / "llama-ctl").exists()


# ---------------------------------------------------------------------------
# 迁移
# ---------------------------------------------------------------------------

def test_legacy_file_is_migrated_and_kept(tmp_path, monkeypatch):
    """首次启动：旧路径有文件 → 复制到用户目录，旧文件保留（不删除）。"""
    root = _appdata(tmp_path, monkeypatch)
    legacy = _legacy(tmp_path, monkeypatch, presets, "LEGACY_PRESETS_FILE",
                     "presets.json", {"Alpha": {"model": "A.gguf"}})
    target = presets.resolve_presets_file()
    assert os.path.isfile(target), "旧文件未迁移到用户目录"
    with open(target, encoding="utf-8") as f:
        assert json.load(f) == {"Alpha": {"model": "A.gguf"}}
    assert os.path.isfile(legacy), "迁移后旧文件不得被删除"


def test_settings_legacy_file_is_migrated(tmp_path, monkeypatch):
    _appdata(tmp_path, monkeypatch)
    legacy = _legacy(tmp_path, monkeypatch, S, "LEGACY_SETTINGS_FILE",
                     "settings.json", {"language": "en"})
    target = S.resolve_settings_file()
    with open(target, encoding="utf-8") as f:
        assert json.load(f) == {"language": "en"}
    assert os.path.isfile(legacy)


def test_both_exist_user_dir_wins(tmp_path, monkeypatch):
    """两处都有文件 → 以用户目录为准，旧文件既不覆盖也不被反向改写。"""
    root = _appdata(tmp_path, monkeypatch)
    legacy = _legacy(tmp_path, monkeypatch, presets, "LEGACY_PRESETS_FILE",
                     "presets.json", {"老": {"model": "OLD.gguf"}})
    target_dir = root / "llama-ctl"
    target_dir.mkdir()
    with open(target_dir / "presets.json", "w", encoding="utf-8") as f:
        json.dump({"新": {"model": "NEW.gguf"}}, f)

    target = presets.resolve_presets_file()
    with open(target, encoding="utf-8") as f:
        assert json.load(f) == {"新": {"model": "NEW.gguf"}}, "旧文件覆盖了用户目录版本"
    with open(legacy, encoding="utf-8") as f:
        assert json.load(f) == {"老": {"model": "OLD.gguf"}}, "旧文件被反向改写"

    monkeypatch.setattr(presets, "PRESETS_FILE", target)
    assert presets.load_presets() == {"新": {"model": "NEW.gguf"}}, "迁移后不该再读旧路径"


def test_migration_failure_is_silent(tmp_path, monkeypatch):
    """迁移失败（用户目录不可建）不得冒泡，仍解析出用户目录路径。"""
    root = _appdata(tmp_path, monkeypatch)
    (root / "llama-ctl").write_text("我是一个文件，不是目录")   # makedirs 会失败
    _legacy(tmp_path, monkeypatch, presets, "LEGACY_PRESETS_FILE", "presets.json", {"a": {}})
    assert presets.resolve_presets_file() == str(root / "llama-ctl" / "presets.json")


# ---------------------------------------------------------------------------
# 环境变量优先级
# ---------------------------------------------------------------------------

def test_env_override_beats_user_dir(tmp_path, monkeypatch):
    _appdata(tmp_path, monkeypatch)
    override = str(tmp_path / "elsewhere" / "presets.json")
    monkeypatch.setenv("LLAMA_CTL_PRESETS", override)
    _legacy(tmp_path, monkeypatch, presets, "LEGACY_PRESETS_FILE", "presets.json", {"a": {}})
    assert presets.resolve_presets_file() == override


def test_env_override_beats_user_dir_for_settings(tmp_path, monkeypatch):
    _appdata(tmp_path, monkeypatch)
    override = str(tmp_path / "elsewhere" / "settings.json")
    monkeypatch.setenv("LLAMA_CTL_SETTINGS", override)
    _legacy(tmp_path, monkeypatch, S, "LEGACY_SETTINGS_FILE", "settings.json", {"language": "en"})
    assert S.resolve_settings_file() == override


def test_env_override_skips_migration(tmp_path, monkeypatch):
    """已覆盖时不碰用户目录、不读旧路径：覆盖是用户显式指定的唯一落点。"""
    root = _appdata(tmp_path, monkeypatch)
    override = str(tmp_path / "elsewhere" / "presets.json")
    monkeypatch.setenv("LLAMA_CTL_PRESETS", override)
    _legacy(tmp_path, monkeypatch, presets, "LEGACY_PRESETS_FILE", "presets.json", {"a": {}})
    presets.resolve_presets_file()
    assert not (root / "llama-ctl").exists(), "覆盖生效时不应创建用户目录"
    assert not os.path.exists(override), "覆盖生效时不应顺手创建文件"

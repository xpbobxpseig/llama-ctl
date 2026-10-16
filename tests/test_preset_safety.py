# -*- coding: utf-8 -*-
"""llama_ctl_gui 预设/服务切换的纯逻辑回归测试（不建真实 Tk 窗口）。

用假 self 调未绑定方法（与 test_first_paint.py 同模式），只验证三条非平凡判据：
- 表单不是从某预设载入时，「应用更改」不得覆盖它（启动自动选中/切服务后）；
- 删掉表单所对应的预设后，不得再把它写进同名预设；
- 切服务时点「否」必须整体中止（不换服务、不覆盖表单）。
"""
import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import llama_ctl_gui as g
import presets


def _fake(tmp_path, monkeypatch, preset_values, loaded="", shown=""):
    """最小假 self：只提供被调用方法需要的属性。"""
    target = str(tmp_path / "presets.json")
    with open(target, "w", encoding="utf-8") as f:
        json.dump(preset_values, f)
    monkeypatch.setattr(presets, "PRESETS_FILE", target)
    monkeypatch.setattr(g, "load_presets", presets.load_presets)
    monkeypatch.setattr(g, "save_presets", presets.save_presets)

    fake = types.SimpleNamespace(
        _preset_loaded=loaded,
        preset_var=types.SimpleNamespace(
            get=lambda: shown, set=lambda v: setattr(fake, "_shown", v)),
        _collect=lambda: ({"model": "SERVICE.gguf"}, []),
        cmb_preset=types.SimpleNamespace(configure=lambda **k: None),
        _flash_preset_highlight=lambda: None,
        # 走真实助手，顺带覆盖「落盘失败不静默」这条路径
        _save_presets=lambda p: g.ControlGUI._persist(
            fake, *presets.save_presets(p), what="presets"),
        _persist_warned=True,      # 测试里不弹提示框
    )
    fake._shown = shown
    return fake, target


def test_sync_does_not_clobber_preset_not_loaded(tmp_path, monkeypatch):
    """启动自动选中 names[0] 后表单装的是**服务**参数：应用不得覆盖该预设。"""
    fake, target = _fake(tmp_path, monkeypatch,
                         {"Alpha": {"model": "ALPHA.gguf"}}, loaded="", shown="Alpha")
    g.ControlGUI._sync_preset_with_form(fake)
    with open(target, encoding="utf-8") as f:
        assert json.load(f)["Alpha"]["model"] == "ALPHA.gguf", "未载入的预设被覆盖"


def test_sync_updates_preset_actually_loaded(tmp_path, monkeypatch):
    """表单确实来自该预设时，应用后应同步它（保留原有的防漂移行为）。"""
    fake, target = _fake(tmp_path, monkeypatch,
                         {"Alpha": {"model": "ALPHA.gguf"}}, loaded="Alpha", shown="Alpha")
    g.ControlGUI._sync_preset_with_form(fake)
    with open(target, encoding="utf-8") as f:
        assert json.load(f)["Alpha"]["model"] == "SERVICE.gguf"


def test_load_params_clears_loaded_preset(tmp_path, monkeypatch):
    """载入服务参数后，表单不再对应任何预设。"""
    fake = types.SimpleNamespace(
        service="S", _preset_loaded="Alpha", _apply_values=lambda *a, **k: None,
    )
    monkeypatch.setattr(g, "get_app_parameters", lambda s: "--model m.gguf")
    monkeypatch.setattr(g, "parse_params", lambda t, f: ({}, [], []))
    g.ControlGUI.load_params(fake)
    assert fake._preset_loaded == "", "载入服务参数后仍声称对应预设 → 会误覆盖"


def test_delete_preset_clears_loaded_marker(tmp_path, monkeypatch):
    """删除表单所对应的预设后，不得再把它当成「可覆盖的当前预设」。"""
    fake, _ = _fake(tmp_path, monkeypatch,
                    {"Alpha": {"model": "A.gguf"}, "Beta": {"model": "B.gguf"}},
                    loaded="Alpha", shown="Alpha")
    monkeypatch.setattr(g.messagebox, "askyesno", lambda *a, **k: True)
    fake.refresh_presets = lambda: None
    g.ControlGUI.delete_preset(fake)
    assert fake._preset_loaded == "", "删除后仍标记为已载入 → 下一次应用会写坏别的预设"


def test_service_change_cancel_aborts_switch(tmp_path, monkeypatch):
    """切服务点「否」：必须保持原服务并保留表单编辑。"""
    calls = []
    fake = types.SimpleNamespace(
        service="QwenLLM", _dirty=lambda: True, _preset_loaded="",
        service_var=types.SimpleNamespace(
            get=lambda: "OtherSvc", set=lambda v: calls.append(("set", v))),
        refresh_all=lambda: calls.append(("refresh_all", None)),
    )
    monkeypatch.setattr(g.messagebox, "askyesno", lambda *a, **k: False)
    monkeypatch.setattr(g, "fmt", lambda k, **kw: k)

    g.ControlGUI.on_service_change(fake)

    assert fake.service == "QwenLLM", "点「否」却仍然切换了服务"
    assert ("refresh_all", None) not in calls, "点「否」后不该重建表单（会丢编辑）"
    assert ("set", "QwenLLM") in calls, "下拉显示应回滚到当前服务"


def test_service_change_confirm_switches(tmp_path, monkeypatch):
    """点「是」：正常切换并载入新服务参数。"""
    calls = []
    fake = types.SimpleNamespace(
        service="QwenLLM", _dirty=lambda: True, _preset_loaded="Alpha",
        service_var=types.SimpleNamespace(get=lambda: "OtherSvc", set=lambda v: None),
        _collect=lambda: ({"model": "x"}, []),
        refresh_presets=lambda: None,
        refresh_all=lambda: calls.append("refresh_all"),
        _save_presets=lambda p: True,
    )
    monkeypatch.setattr(g.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(g, "fmt", lambda k, **kw: "自动备份 X")
    monkeypatch.setattr(g, "load_presets", lambda: {})
    monkeypatch.setattr(g, "save_presets", lambda p: (True, ""))

    g.ControlGUI.on_service_change(fake)

    assert fake.service == "OtherSvc"
    assert calls == ["refresh_all"]
    assert fake._preset_loaded == "", "换服务后表单不再对应原预设"


# ---------------------------------------------------------------------------
# 回归：设置窗下拉取消后必须回滚显示
#
# 根因：_lang_var/_appear_var 是 tk.StringVar，没有 winfo_exists()；旧实现对
# 它们调用该方法抛 AttributeError，被 except 吞掉，整个回滚是死代码。
# ---------------------------------------------------------------------------

def test_setting_vars_have_no_winfo_exists():
    """把导致死代码的语言特性钉住，防止有人再把 winfo_exists 用在变量上。"""
    import tkinter as tk
    assert not hasattr(tk.StringVar, "winfo_exists")


def test_restore_setting_widgets_rolls_back_language():
    calls = []
    fake = types.SimpleNamespace(
        settings={"appearance": "light"},
        _lang_var=types.SimpleNamespace(set=lambda v: calls.append(("lang", v))),
        _appear_var=types.SimpleNamespace(set=lambda v: calls.append(("appear", v))),
    )
    monkey = g.strings._current
    try:
        g.strings._current = "zh"
        g.ControlGUI._restore_setting_widgets(fake)
    finally:
        g.strings._current = monkey
    assert ("lang", "中文") in calls, "取消语言切换后下拉未回滚（回滚逻辑仍是死代码）"
    assert any(k == "appear" for k, _ in calls), "外观下拉未回滚"


def test_restore_setting_widgets_survives_broken_var():
    """变量失效（控件已销毁）不得抛进 Tk 事件循环。"""
    class Boom:
        def set(self, v):
            raise RuntimeError("invalid command name")

    fake = types.SimpleNamespace(settings={"appearance": "light"},
                                 _lang_var=Boom(), _appear_var=Boom())
    g.ControlGUI._restore_setting_widgets(fake)   # 不应抛异常


# ---------------------------------------------------------------------------
# 回归：配置落盘失败不得静默
# ---------------------------------------------------------------------------

def test_save_settings_returns_error_instead_of_raising(tmp_path, monkeypatch):
    """不可写路径（目标是目录）→ 返回 (False, 原因)，绝不抛异常。"""
    import settings as S
    target = tmp_path / "adir"
    target.mkdir()
    monkeypatch.setattr(S, "SETTINGS_FILE", str(target))   # 目标是目录，写必失败
    ok, err = S.save_settings({"language": "en"})
    assert ok is False and err, "写入失败必须返回 (False, 原因)，不得抛异常"


def test_save_settings_creates_missing_dir(tmp_path, monkeypatch):
    """父目录不存在时应自动创建（exe 换目录/首次运行场景）。"""
    import settings as S
    target = tmp_path / "fresh" / "settings.json"
    monkeypatch.setattr(S, "SETTINGS_FILE", str(target))
    ok, err = S.save_settings({"language": "en"})
    assert ok is True and target.is_file(), "父目录缺失应自动建目录后写入"


def test_save_presets_returns_error_instead_of_raising(tmp_path, monkeypatch):
    import presets as P
    target = tmp_path / "adir"
    target.mkdir()
    monkeypatch.setattr(P, "PRESETS_FILE", str(target))
    ok, err = P.save_presets({"a": {}})
    assert ok is False and err


def test_persist_warns_once_and_reports_failure():
    warnings = []
    fake = types.SimpleNamespace(
        _persist_warned=False,
        _lang_var=None,
    )
    monkeypatch_msg = g.messagebox.showwarning
    g.messagebox.showwarning = lambda *a, **k: warnings.append(a)
    try:
        assert g.ControlGUI._persist(fake, False, "disk full", "预设") is False
        assert g.ControlGUI._persist(fake, False, "disk full", "预设") is False
    finally:
        g.messagebox.showwarning = monkeypatch_msg
    assert len(warnings) == 1, "落盘失败应提示且只提示一次（不刷屏）"


# ---------------------------------------------------------------------------
# 回归：已销毁的检查按钮不得把 _upd_checking 永久卡在 True
#
# 根因：语言/外观重建销毁设置窗后 _upd_check_btn 仍是旧引用，直接 configure
# 抛 TclError，而异常发生在 _upd_checking=True 之后 → 防重入标志再不复位，
# 此后所有更新检查都在入口静默 return。
# ---------------------------------------------------------------------------

def test_check_btn_set_survives_destroyed_widget():
    class Dead:
        def winfo_exists(self):
            return False

        def configure(self, **k):
            raise AssertionError("已销毁的控件不该被 configure")

    fake = types.SimpleNamespace(_upd_check_btn=Dead())
    g.ControlGUI._upd_check_btn_set(fake, "disabled", "checking")   # 不应抛


def test_check_btn_set_survives_tcl_error():
    """winfo_exists 都可能抛（解释器已销毁）——仍不得冒泡。"""
    class Exploding:
        def winfo_exists(self):
            raise RuntimeError("invalid command name")

    fake = types.SimpleNamespace(_upd_check_btn=Exploding())
    g.ControlGUI._upd_check_btn_set(fake, "normal", "check")


def test_check_btn_set_noop_without_button():
    g.ControlGUI._upd_check_btn_set(types.SimpleNamespace(), "normal", "check")

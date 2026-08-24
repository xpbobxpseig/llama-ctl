#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
strings.py — 框架文案 i18n（llama_ctl）

范围遵循 ADR-0005：仅界面骨架短文案（按钮/标题/messagebox/状态行）中英双语；
FIELDS 参数详解（label/help/option_help）保持中文不翻。

t(key) 返回当前语言文案；带参数的动态文案用 fmt(key, **kw)。
语言切换由 GUI 写 settings 后调用 set_lang 生效。
"""

_current = "zh"

STRINGS = {
    # ---- 标题 / 卡片 ----
    "app.title":        {"zh": "llama.cpp 服务控制台", "en": "llama.cpp Service Console"},
    "card.service":     {"zh": "服务", "en": "Service"},
    "card.presets":     {"zh": "参数预设", "en": "Presets"},
    "card.params":      {"zh": "启动参数", "en": "Launch Parameters"},
    # ---- 顶栏 ----
    "svc.label":        {"zh": "服务", "en": "Svc"},
    "state.unknown":    {"zh": "服务 —", "en": "Svc —"},
    "health.idle":      {"zh": "探活 —", "en": "Health —"},
    "health.down":      {"zh": "探活 未运行", "en": "Health not running"},
    "boot.label":       {"zh": "开机自启", "en": "Auto-start"},
    "boot.auto":        {"zh": "自动(开机)", "en": "Auto (boot)"},
    "boot.manual":      {"zh": "手动", "en": "Manual"},
    "boot.disabled":    {"zh": "禁用", "en": "Disabled"},
    # ---- 预设 ----
    "preset.name.ph":   {"zh": "预设名（输入或选）", "en": "Preset name (type or pick)"},
    "preset.delete":    {"zh": "删除", "en": "Delete"},
    "preset.autobackup":{"zh": "自动备份 {t}", "en": "Auto backup {t}"},
    # ---- 参数区 ----
    "quick.label":      {"zh": "快捷：", "en": "Quick:"},
    "browse":           {"zh": "浏览", "en": "Browse"},
    "btn.start":        {"zh": "启动", "en": "Start"},
    "btn.stop":         {"zh": "停止", "en": "Stop"},
    "btn.restart":      {"zh": "重启", "en": "Restart"},
    "btn.revert":       {"zh": "还原", "en": "Revert"},
    "btn.apply2":       {"zh": "应用更改", "en": "Apply changes"},
    # ---- 日志 ----
    "log.collapsed":    {"zh": "日志尾随 server.err（已折叠）", "en": "Tail server.err (collapsed)"},
    "log.expanded":     {"zh": "日志尾随 server.err（点击折叠）", "en": "Tail server.err (click to fold)"},
    "log.restart.stop": {"zh": ">>> 重启 {s}：停止...", "en": ">>> Restarting {s}: stopping..."},
    "log.restart.start":{"zh": ">>> 启动...", "en": ">>> Starting..."},
    "log.restart.ready":{"zh": ">>> 服务就绪：{d}", "en": ">>> Service ready: {d}"},
    # ---- 状态 ----
    "status.svc":       {"zh": "服务 {st}", "en": "Svc {st}"},
    "status.health.ok": {"zh": "探活 OK · {d}", "en": "Health OK · {d}"},
    "status.health.bad":{"zh": "探活 FAIL · {d}", "en": "Health FAIL · {d}"},
    # ---- 设置窗口 ----
    "settings.title":   {"zh": "设置", "en": "Settings"},
    "settings.lang":    {"zh": "界面语言（参数详解保持中文）", "en": "UI language (parameter guides stay Chinese)"},
    "settings.appear":  {"zh": "外观", "en": "Appearance"},
    "appear.system":    {"zh": "跟随系统", "en": "System"},
    "appear.light":     {"zh": "浅色", "en": "Light"},
    "appear.dark":      {"zh": "深色", "en": "Dark"},
    "settings.close":   {"zh": "关闭", "en": "Close"},
    "settings.note":    {"zh": "几何与预设记忆自动生效，无需设置。",
                         "en": "Geometry & last-preset memory are automatic."},
    "btn.settings":     {"zh": "⚙ 设置", "en": "⚙ Settings"},
    # ---- messagebox 标题 ----
    "mb.unsupported":   {"zh": "不支持", "en": "Unsupported"},
    "mb.hint":          {"zh": "提示", "en": "Hint"},
    "mb.error":         {"zh": "错误", "en": "Error"},
    "mb.confirm":       {"zh": "确认", "en": "Confirm"},
    "mb.unchanged":     {"zh": "无需改动", "en": "No changes"},
    "mb.doublecheck":   {"zh": "二次确认", "en": "Double-check"},
    "mb.fail":          {"zh": "失败", "en": "Failed"},
    "mb.success":       {"zh": "成功", "en": "Success"},
    "file.pick":        {"zh": "选择文件", "en": "Pick a file"},
    # ---- messagebox 正文 ----
    "msg.winonly":      {"zh": "本工具仅支持 Windows（依赖 NSSM / sc / powershell）。",
                         "en": "Windows only (requires NSSM / sc / powershell)."},
    "msg.presetname":   {"zh": "请先在下拉框输入或选择一个预设名。",
                         "en": "Type or pick a preset name first."},
    "msg.preset.pick":  {"zh": "请先在下拉选择一个预设。", "en": "Pick a preset first."},
    "msg.preset.miss":  {"zh": "预设「{n}」不存在。", "en": "Preset \"{n}\" not found."},
    "msg.preset.del":   {"zh": "删除预设「{n}」？", "en": "Delete preset \"{n}\"?"},
    "msg.nochange":     {"zh": "参数与当前服务一致。", "en": "Parameters already match the service."},
    "msg.written":      {"zh": "已写回。服务未运行，下次启动即生效。",
                         "en": "Written. Service not running; takes effect on next start."},
    "msg.sc.done":      {"zh": "sc {a} 已提交（服务 {s}）。", "en": "sc {a} submitted (service {s})."},
    "msg.sc.fail":      {"zh": "sc {a} 失败：{m}", "en": "sc {a} failed: {m}"},
    "msg.write.fail":   {"zh": "写回失败：{o}", "en": "Write failed: {o}"},
    "msg.auto.fail":    {"zh": "开机自启设置失败：{o}", "en": "Auto-start change failed: {o}"},
    "msg.auto.confirm": {"zh": "将开机自启设为「{m}」？", "en": "Set auto-start to \"{m}\"?"},
    "msg.svc.dirty":    {"zh": "当前表单有未应用的更改，切换服务将丢失。是否先把当前表单自动备份为新预设再切换？",
                         "en": "Unapplied changes will be lost on switch. Auto-backup current form as a new preset first?"},
    "msg.apply.run":    {"zh": "服务正在运行，将写回新参数并自动重启（{s}）：\n\n新参数：\n{n}\n\n旧参数：\n{o}\n\n确认？",
                         "en": "Service is running; parameters will be written and the service restarted ({s}):\n\nNew:\n{n}\n\nOld:\n{o}\n\nProceed?"},
    "msg.apply.stop":   {"zh": "即将写回 NSSM AppParameters（服务 {s}，当前未运行）：\n\n新参数：\n{n}\n\n旧参数：\n{o}\n\n确认写回？",
                         "en": "About to write NSSM AppParameters (service {s}, not running):\n\nNew:\n{n}\n\nOld:\n{o}\n\nProceed?"},
}


def set_lang(lang):
    global _current
    _current = lang if lang in ("zh", "en") else "zh"


def t(key):
    entry = STRINGS.get(key)
    if entry is None:
        return key
    return entry.get(_current) or entry["zh"]


def fmt(key, **kw):
    return t(key).format(**kw)

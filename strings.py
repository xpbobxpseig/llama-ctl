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
    "card.presets":     {"zh": "参数预设", "en": "Presets"},
    "card.params":      {"zh": "启动参数", "en": "Launch Parameters"},
    # ---- 顶栏 ----
    "svc.label":        {"zh": "服务", "en": "Svc"},
    "state.unknown":    {"zh": "服务 —", "en": "Svc —"},
    "health.idle":      {"zh": "探活 —", "en": "Health —"},
    "health.down":      {"zh": "探活 未运行", "en": "Health down"},
    "boot.label":       {"zh": "开机自启", "en": "Auto-start"},
    "boot.auto":        {"zh": "自动(开机)", "en": "Auto (boot)"},
    "boot.manual":      {"zh": "手动", "en": "Manual"},
    "boot.disabled":    {"zh": "禁用", "en": "Disabled"},
    # ---- 预设 ----
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
    "log.expanded":     {"zh": "日志尾随 server.err（点击折叠）", "en": "Log tail: server.err (click to fold)"},  # 37ch，日志头 fit 适配
    "log.restart.stop": {"zh": ">>> 重启 {s}：停止...", "en": ">>> Restarting {s}: stopping..."},
    "log.restart.start":{"zh": ">>> 启动...", "en": ">>> Starting..."},
    "log.restart.ready":{"zh": ">>> 服务就绪：{d}", "en": ">>> Service ready: {d}"},
    "log.restart.unhealthy":{"zh": ">>> 当前未探活，继续重启", "en": ">>> Not healthy, restarting anyway"},
    "log.restart.stopfail":{"zh": ">>> 停止失败，已中止重启：{m}", "en": ">>> Stop failed, restart aborted: {m}"},
    "log.restart.stoptimeout":{"zh": ">>> 停止超时（40×0.5s 未 STOPPED），已中止重启", "en": ">>> Stop timed out, restart aborted"},
    # ---- 状态 ----
    "status.svc":       {"zh": "服务 {st}", "en": "Svc {st}"},
    "status.health.ok": {"zh": "探活 OK · {d}", "en": "Health OK · {d}"},
    "status.health.bad":{"zh": "探活 FAIL · {d}", "en": "Health FAIL · {d}"},
    # ---- 状态 / 内联提示（P2 英文冒烟补齐：原为硬编码中文）----
    "status.dirty":     {"zh": "● 有未应用的更改", "en": "● Unapplied changes"},  # 19ch，预设行右侧留白充足
    # ---- 设置窗口 ----
    "settings.title":   {"zh": "设置", "en": "Settings"},
    "settings.lang":    {"zh": "界面语言（参数详解保持中文）", "en": "Language (parameter guides stay Chinese)"},  # 42ch < 360px 可用宽
    "settings.appear":  {"zh": "外观", "en": "Appearance"},
    "settings.motion":  {"zh": "动效（关闭后所有动画直跳终态）", "en": "Motion (off = instant, no animation)"},
    "appear.system":    {"zh": "跟随系统", "en": "System"},
    "appear.light":     {"zh": "浅色", "en": "Light"},
    "appear.dark":      {"zh": "深色", "en": "Dark"},
    "settings.close":   {"zh": "关闭", "en": "Close"},
    "settings.note":    {"zh": "几何与预设记忆自动生效，无需设置。",
                         "en": "Geometry & last-preset memory are automatic."},  # 45ch ≤ 一行 52ch，不换行
    "btn.settings":     {"zh": "⚙ 设置", "en": "Settings"},
    # ---- messagebox 标题 ----
    "mb.unsupported":   {"zh": "不支持", "en": "Unsupported"},
    "mb.hint":          {"zh": "提示", "en": "Hint"},
    "mb.error":         {"zh": "错误", "en": "Error"},
    "mb.confirm":       {"zh": "确认", "en": "Confirm"},
    "mb.unchanged":     {"zh": "无需改动", "en": "No changes"},
    "mb.doublecheck":   {"zh": "二次确认", "en": "Double-check"},
    "mb.fail":          {"zh": "失败", "en": "Failed"},
    "mb.success":       {"zh": "成功", "en": "Success"},
    "mb.busy":          {"zh": "任务进行中", "en": "Task in progress"},
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
    "msg.restarting":   {"zh": "重启进行中，请稍候…", "en": "Restart in progress…"},
    "msg.close.busy":   {"zh": "后台任务正在进行（重启或官方更新）。\n\n立即退出可能让服务停摆，或留下半更新状态的二进制文件。\n\n确定要强制退出吗？",
                         "en": "A background task is running (restart or official update).\n\nExiting now could leave the service down or the binaries half-updated.\n\nForce quit anyway?"},
    "msg.write.fail":   {"zh": "写回失败：{o}", "en": "Write failed: {o}"},
    "msg.auto.fail":    {"zh": "开机自启设置失败：{o}", "en": "Auto-start change failed: {o}"},
    "msg.auto.confirm": {"zh": "将开机自启设为「{m}」？", "en": "Set auto-start to \"{m}\"?"},
    "msg.svc.dirty":    {"zh": "当前表单有未应用的更改，切换服务将丢失。是否先把当前表单自动备份为新预设再切换？",
                         "en": "The form has unapplied changes. Switch now and auto-backup the form as a new preset?"},  # 88ch，messagebox 自换行
    "msg.rebuild.dirty":{"zh": "当前表单有未应用的更改，切换语言 / 外观会重建界面并丢失这些更改。是否先自动备份为新预设再继续？",
                         "en": "The form has unapplied changes. Switching language/appearance rebuilds the UI and discards them. Auto-backup as a new preset and continue?"},
    "msg.apply.run":    {"zh": "服务正在运行，将写回新参数并自动重启（{s}）：\n\n新参数：\n{n}\n\n旧参数：\n{o}\n\n确认？",
                         "en": "Service is running; parameters will be written and the service restarted ({s}):\n\nNew:\n{n}\n\nOld:\n{o}\n\nProceed?"},
    "msg.apply.stop":   {"zh": "即将写回 NSSM AppParameters（服务 {s}，当前未运行）：\n\n新参数：\n{n}\n\n旧参数：\n{o}\n\n确认写回？",
                         "en": "About to write NSSM AppParameters (service {s}, not running):\n\nNew:\n{n}\n\nOld:\n{o}\n\nProceed?"},
      # ---- 官方更新（llama.cpp） ----
      "upd.section":      {"zh": "官方更新", "en": "Official updates"},
      "upd.channel":      {"zh": "二进制版本（替换 F:\\llama.cpp 下文件）",
                          "en": "Build variant (files under F:\\llama.cpp)"},
      "upd.auto.label":   {"zh": "启动时自动检查（仅提示，绝不自动安装）",
                          "en": "Check on startup (notify only, never auto-install)"},
      "upd.check":        {"zh": "立即检查更新", "en": "Check for updates"},
      "upd.status.now":   {"zh": "当前：{b}", "en": "Installed: {b}"},
      "upd.status.unknown":{"zh": "当前版本未知（无法读取 llama-server.exe）",
                          "en": "Installed version unknown (llama-server.exe unreadable)"},
      "upd.status.none":  {"zh": "还未检查过更新", "en": "Not checked yet"},
      "upd.checking":     {"zh": "正在检查官方最新版本…", "en": "Checking official releases…"},
      "upd.check.done":   {"zh": "最新：{t}", "en": "Latest: {t}"},
      "upd.check.fail":   {"zh": "检查失败：{e}", "en": "Check failed: {e}"},
      "upd.uptodate":     {"zh": "已是最新", "en": "Up to date"},
      "upd.uptodate.msg": {"zh": "当前 b{cur} 已是最新官方构建（b{new}）。",
                          "en": "Build b{cur} is already the latest official build (b{new})."},
      "upd.title":        {"zh": "发现新版本：{t}", "en": "Update available: {t}"},
      "upd.prompt":       {"zh": "官方最新 b{n}（当前 b{c}）。是否查看更新日志并更新？",
                          "en": "Official latest b{n} (installed b{c}). Review the changelog and update?"},
      "upd.changelog":    {"zh": "更新日志", "en": "Changelog"},
      "upd.assets":       {"zh": "下载内容：{a}", "en": "Will download: {a}"},
      "upd.install":      {"zh": "立即更新", "en": "Install now"},
      "upd.install.confirm":{"zh": "将停止服务「{s}」并替换 llama.cpp 二进制。旧文件会备份到 {d}。\n\n继续？",
                          "en": "The service \"{s}\" will be stopped and llama.cpp binaries replaced. Old files are backed up to {d}.\n\nContinue?"},
      "upd.installing":   {"zh": "正在更新 llama.cpp…", "en": "Updating llama.cpp…"},
      "upd.stopping":     {"zh": "停止服务 {s}…", "en": "Stopping service {s}…"},
      "upd.stopped":      {"zh": "服务已停止。", "en": "Service stopped."},
      "upd.stop.fail":    {"zh": "停止服务失败：{m}", "en": "Failed to stop service: {m}"},
      "upd.downloading":  {"zh": "下载 {n}（{p}%）", "en": "Downloading {n} ({p}%)"},
      "upd.backing":      {"zh": "备份旧文件到 {d}", "en": "Backing up old files to {d}"},
      "upd.backup.fail":  {"zh": "备份旧文件失败：{m}（已中止，未替换任何文件）",
                           "en": "Backup failed: {m} (aborted; no files were replaced)"},
      "upd.extracting":   {"zh": "解压替换二进制…", "en": "Extracting and replacing binaries…"},
      "upd.extract.fail": {"zh": "解压替换失败：{e}", "en": "Extract/replace failed: {e}"},
      "upd.rollback":     {"zh": ">>> 检测到失败，正在回滚已替换的文件…", "en": ">>> Failure detected, rolling back replaced files…"},
      "upd.rollback.done":{"zh": ">>> 回滚完成：旧文件已恢复。", "en": ">>> Rollback complete: previous files restored."},
      "upd.rollback.fail":{"zh": ">>> 回滚失败：{e}（可手动从 {d} 恢复）", "en": ">>> Rollback failed: {e} (restore manually from {d})"},
      "upd.no.files":     {"zh": "没有需要替换的文件（更新包与目标目录不匹配）",
                           "en": "No files to replace (package does not match target directory)"},
      "upd.not.running":  {"zh": "更新后服务 {s} 未进入 RUNNING，已回滚旧文件",
                           "en": "Service {s} did not reach RUNNING after update; previous files restored"},
      "upd.starting":     {"zh": "重启服务 {s}…", "en": "Restarting service {s}…"},
      "upd.done":         {"zh": "更新完成：{s} 已重启，当前 b{b}。", "en": "Update complete: {s} restarted, now b{b}."},
      "upd.err":          {"zh": "更新失败：{e}", "en": "Update failed: {e}"},
      "upd.err.title":    {"zh": "更新失败", "en": "Update failed"},
      "upd.required":     {"zh": "未找到匹配的官方资产。请确认二进制版本选择是否正确。",
                          "en": "No matching official asset found. Check the build variant setting."},
      "upd.prune":        {"zh": "已清理 {n} 个陈旧目录：{d}",
                          "en": "Pruned {n} stale directories: {d}"},
}


def wraplength_for(win_width, offset=160, floor=400):
    """P2 动态 wraplength 公式：窗口宽减去固定边距，下限 400 防极窄时折行过碎。

    GUI 的 lbl_hint / lbl_warn 在 <Configure> 时按此更新；测试直接复用同一
    公式，保证「实现 = 验收」零漂移。
    """
    return max(floor, int(win_width or 0) - offset)  # None/0 → floor


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

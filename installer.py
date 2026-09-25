#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""installer.py — 官方更新「安装事务」深模块（llama_ctl）

从 ControlGUI 里挖出的后台安装序列：下载→停服→备份→逐文件替换→重启，
任一步失败精确回滚，收尾尽力恢复服务。

interface 只有一个入口：

    install(rel, service, target, bak, sink, download_dir, deps=None)

实现是全部事务细节（每一步的顺序、失败点、回滚清单、服务状态收敛）。
外部副作用（updater 的网络/文件操作、nssm 的状态查询与启停、日志去向）
全部经参数注入——默认绑真实现，测试传假实现即可在无 UI、无网络、无服务
的环境下跑完整条失败/回滚路径。

sink 收两类东西：可读日志行（str）与状态哨兵（"__REFRESH_STATUS__" 等），
与 GUI 原 `self._log_q.put` 语义一致（队列线程安全）。日志行沿用 strings
的 key，与 GUI 其余文案同源，语言切换行为不变。
"""

import os
import time

import strings
import updater
from strings import fmt, t
from updater import UpdateError


class RealDeps:
    """默认依赖：真 updater + 真 nssm（sc_query_state / sc_action）。

    仅暴露安装事务用到的那几个函数；测试传一个同属性名的假对象即可替换。
    """

    def __init__(self):
        self.is_valid_zip = updater.is_valid_zip
        self.download = updater.download
        self.collect_conflicts = updater.collect_conflicts
        self.backup_files = updater.backup_files
        self.zip_top_files = updater.zip_top_files
        self.extract_one = updater.extract_one
        self.restore_files = updater.restore_files
        self.remove_files = updater.remove_files
        self.get_installed_build = updater.get_installed_build
        # nssm 状态/动作延迟导入：避免在本模块顶层拉入 winreg 等平台依赖，
        # 也让纯逻辑测试可以在非 Windows 上 import 本模块。
        from nssm_adapter import sc_query_state, sc_action
        self.query_state = sc_query_state
        self.action = sc_action


def install(rel, service, target, bak, sink, download_dir, deps=None):
    """执行一次官方更新安装（阻塞；调用方负责放到后台线程）。

    事务保障：
    - 备份采用逐文件原子写，备份失败即中止且未替换任何文件；
    - 替换记录 replaced 清单，任一步失败自动从 bak 精确回滚已替换文件；
    - 失败收尾尽力重启服务，绝不静默留下停摆服务。

    参数
    - rel: 最新 release 信息（含 tag / assets）。
    - service: 目标 nssm 服务名。
    - target: 二进制替换目标目录。
    - bak: 本次备份目录（时间戳子目录）。
    - sink: 日志/哨兵出口，收 str（线程安全，通常为 GUI 的 _log_q.put）。
    - download_dir: 资产下载缓存根目录（按 release tag 分目录）。
    - deps: 外部依赖；None 用 RealDeps()。
    """
    if deps is None:
        deps = RealDeps()

    # 1) 下载官方资产到缓存目录（按 release tag 分目录）
    dl_dir = os.path.join(download_dir, rel["tag"])
    local_zips = []
    for asset in rel["assets"]:
        dest = os.path.join(dl_dir, asset["name"])
        # 缓存必须验有效性再复用：一次截断若被当作「已缓存」，之后每次重试
        # 都拿同一个坏文件，更新会**永久失败**（实测故障）。坏缓存直接删除重下。
        if os.path.isfile(dest) and deps.is_valid_zip(dest):
            sink("  " + asset["name"] + " (cached)")
        else:
            if os.path.isfile(dest):
                sink(fmt("upd.cache.bad", n=asset["name"]))
                try:
                    os.remove(dest)
                except OSError as exc:
                    raise UpdateError(fmt("upd.cache.del.fail",
                                          n=asset["name"], e=exc)) from exc

            def _prog(done, total, name=asset["name"]):
                pct = int(done * 100.0 / max(total, 1))
                if pct in (0, 25, 50, 75, 100):
                    sink(fmt("upd.downloading", n=name, p=pct))

            try:
                deps.download(asset["browser_download_url"], dest, progress=_prog)
            except Exception as exc:  # noqa: BLE001 - 下载失败清理残留
                for suffix in ("", ".part"):
                    try:
                        os.remove(dest + suffix)
                    except OSError:
                        pass
                raise UpdateError(str(exc)) from exc
            # 重下后仍无效：明确中止，不进后续备份/替换
            if not deps.is_valid_zip(dest):
                try:
                    os.remove(dest)
                except OSError:
                    pass
                raise UpdateError(fmt("upd.cache.still.bad", n=asset["name"]))
        local_zips.append(dest)

    # 2) 停止服务（Windows 上替换二进制必须先停）；已停止则直接继续
    sink(fmt("upd.stopping", s=service))
    if deps.query_state(service) != "STOPPED":
        ok, msg = deps.action("stop", service)
        if not ok and deps.query_state(service) != "STOPPED":
            raise UpdateError(fmt("upd.stop.fail", m=msg))
    stopped = False
    for _ in range(40):
        if deps.query_state(service) == "STOPPED":
            stopped = True
            break
        time.sleep(0.5)
    if not stopped:
        raise UpdateError(fmt("upd.stop.fail", m="timeout"))
    sink(t("upd.stopped"))

    # 3) 备份将被覆盖的旧文件（逐文件原子写；失败则中止，未替换任何文件）
    #    此时服务**已停止**，故本段任何失败都必须尽力把服务拉起来，
    #    否则会留下一个停摆的服务。
    try:
        conflicts = deps.collect_conflicts(local_zips, target)
    except Exception as exc:  # noqa: BLE001 - 坏 zip / IO 错误转为可读提示
        sink(fmt("upd.zip.bad", e=exc))
        _try_restart_service(service, sink, deps)
        raise UpdateError(fmt("upd.zip.bad", e=exc)) from exc
    if not conflicts:
        _try_restart_service(service, sink, deps)
        raise UpdateError(t("upd.no.files"))
    sink(fmt("upd.backing", d=bak))
    try:
        deps.backup_files(conflicts, target, bak)
    except OSError as exc:
        sink(fmt("upd.backup.fail", m=exc))
        _try_restart_service(service, sink, deps)
        raise UpdateError(fmt("upd.backup.fail", m=exc)) from exc

    # 4) 逐文件替换：与 conflicts 同序，失败时按 replaced 精确回滚。
    #    同名文件以最后一个 zip 为准（与旧「按 zip 顺序逐个解压」行为一致）。
    #    注意：服务此时**已停止**，故列举 zip 条目失败（坏包）也必须恢复服务。
    sink(t("upd.extracting"))
    sources = {}
    try:
        for zp in local_zips:
            for name in deps.zip_top_files(zp):
                sources[name] = zp
    except Exception as exc:  # noqa: BLE001 - 坏 zip：可读提示 + 恢复服务
        sink(fmt("upd.zip.bad", e=exc))
        _try_restart_service(service, sink, deps)
        raise UpdateError(fmt("upd.zip.bad", e=exc)) from exc
    # 与旧行为一致：先覆盖目标目录中已存在的文件，再安装 zip 新增文件
    ordered = conflicts + [n for n in sources if n not in conflicts]
    replaced = []   # 覆盖过的旧文件（可回滚）
    added = []      # 目标目录原本不存在的新文件（回滚时删除）
    try:
        for name in ordered:
            zp = sources.get(name)
            if zp is None:
                continue
            existed = os.path.isfile(os.path.join(target, name))
            deps.extract_one(zp, target, name)
            if existed:
                replaced.append(name)
            else:
                added.append(name)
    except Exception as exc:  # noqa: BLE001 - 替换失败：回滚已替换文件后重启收尾
        sink(fmt("upd.extract.fail", e=exc))
        rollback_files(replaced, target, bak, sink, deps)
        remove_added_files(added, target, sink, deps)
        _try_restart_service(service, sink, deps)
        raise
    sink("__REFRESH_STATUS__")

    # 5) 重启服务并等待 RUNNING；未恢复 RUNNING 则回滚旧文件
    sink(fmt("upd.starting", s=service))
    deps.action("start", service)
    running = False
    for _ in range(120):
        if deps.query_state(service) == "RUNNING":
            running = True
            break
        time.sleep(0.5)
    if not running:
        sink(fmt("upd.not.running", s=service))
        rollback_files(replaced, target, bak, sink, deps)
        remove_added_files(added, target, sink, deps)
        _try_restart_service(service, sink, deps)
        raise UpdateError(fmt("upd.not.running", s=service))
    b = deps.get_installed_build(os.path.join(target, "llama-server.exe"))
    sink(fmt("upd.done", s=service, b=("b%d" % b) if b else "?"))


def rollback_files(names, target, bak, sink, deps):
    """用备份目录恢复已替换文件（线程安全：只写 sink）。"""
    if not names:
        return
    sink(t("upd.rollback"))
    try:
        deps.restore_files(names, target, bak)
        sink(t("upd.rollback.done"))
    except Exception as exc:  # noqa: BLE001 - 回滚失败不阻断后续重启收尾
        sink(fmt("upd.rollback.fail", e=exc, d=bak))


def remove_added_files(names, target, sink, deps):
    """删除更新新增的文件（回滚清理，线程安全：只写 sink）。"""
    if not names:
        return
    try:
        deps.remove_files(names, target)
    except Exception as exc:  # noqa: BLE001 - 清理失败不阻断后续重启收尾
        sink(fmt("upd.rollback.fail", e=exc, d=target))


def _try_restart_service(service, sink, deps):
    """更新失败收尾：若服务处于 STOPPED，尽力重启（线程安全）。"""
    try:
        if deps.query_state(service) != "STOPPED":
            return
        sink(fmt("upd.starting", s=service))
        deps.action("start", service)
        for _ in range(120):
            if deps.query_state(service) == "RUNNING":
                break
            time.sleep(0.5)
    except Exception:  # noqa: BLE001 - 尽力而为，失败由外层收尾日志兜底
        pass

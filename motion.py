"""llama_ctl 动效引擎（纯数值模块，零 GUI 依赖）。

本模块刻意不 import tkinter / customtkinter / 任何 GUI 库，也不使用线程或真实定时器，
只做数值插值、缓动函数与动画状态机，因此可脱离 GUI 单独单元测试。

GUI 层负责把 Tk 的 after 包装成 schedule(fn, delay_ms) -> token
（token 即 after id，供取消时用 widget.after_cancel 使用），并在构造
Animator 时注入；测试则可注入一个收集调用列表的假调度器（见模块末尾演示）。

依据 docs/design-guide.md 第二节（动效规范）与第五节（动效降级策略）：
- 帧步进约 16ms（ease-out cubic 等缓动由 GUI 侧按需调用 ease_* 函数包一层，
  本模块 Animator 只给线性进度 p，回调里可自行 ease_out_cubic 变换）；
- 性能兜底：同时活动动画 > max_active（默认 8）或上一帧回调实际耗时 >
  frame_budget_ms（默认 50ms）时，新动画直接瞬时完成，不进入调度循环。
"""

from __future__ import annotations

import sys
import time
from typing import Any, Callable, Dict, Optional, Tuple

__all__ = [
    "parse_hex",
    "format_hex",
    "lerp",
    "ease_out_cubic",
    "ease_in_cubic",
    "ease_in_out",
    "Animator",
]


# ---------------------------------------------------------------------------
# 1. hex 工具
# ---------------------------------------------------------------------------

def parse_hex(s: str) -> Tuple[int, int, int]:
    """把 "#rrggbb" / "#rgb" / "rrggbb" 解析为 0-255 的 (r, g, b) 元组。

    非法输入（类型不对、长度不对、非十六进制字符）抛 ValueError。
    """
    if not isinstance(s, str):
        raise ValueError(f"hex 颜色必须是字符串，得到 {type(s).__name__}")
    v = s.strip()
    if v.startswith("#"):
        v = v[1:]
    if len(v) == 3:  # 短格式 "#abc" 展开为 "aabbcc"
        v = "".join(ch * 2 for ch in v)
    if len(v) != 6:
        raise ValueError(f"hex 颜色须为 3 或 6 位十六进制，得到 {len(v)} 位: {s!r}")
    try:
        return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16))
    except ValueError:
        raise ValueError(f"hex 颜色含非十六进制字符: {s!r}") from None


def format_hex(t: Tuple[int, int, int]) -> str:
    """把 (r, g, b) 格式化为 "#rrggbb" 小写字符串（数值按 0-255 截断取整）。"""
    if not (isinstance(t, (tuple, list)) and len(t) == 3):
        raise ValueError(f"颜色须为三元组，得到 {t!r}")
    r, g, b = (int(max(0, min(255, round(c)))) for c in t)
    return "#%02x%02x%02x" % (r, g, b)


def lerp(a: Any, b: Any, t: float) -> Tuple[int, int, int]:
    """在颜色 a、b 间做三通道线性插值，返回 (r, g, b)。

    a / b 可以是 "#rrggbb" 字符串或 (r, g, b) 元组；t 越界时自动截断到 [0, 1]；
    结果四舍五入为 0-255 的 int（供直接 "%02x" 格式化）。
    """
    ca = parse_hex(a) if isinstance(a, str) else a
    cb = parse_hex(b) if isinstance(b, str) else b
    if not (isinstance(ca, (tuple, list)) and len(ca) == 3 and
            isinstance(cb, (tuple, list)) and len(cb) == 3):
        raise ValueError(f"lerp 需要两个颜色（hex 或三元组），得到 {a!r} / {b!r}")
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return tuple(int(round(ca[i] + (cb[i] - ca[i]) * t)) for i in range(3))


# ---------------------------------------------------------------------------
# 2. 缓动函数（手写，无第三方依赖；索引量 i 从 0 到 steps）
# ---------------------------------------------------------------------------

def ease_out_cubic(i: float, steps: int) -> float:
    """ease-out cubic：t = 1 - (1 - i/steps)**3。

    i == 0 返回 0.0；i >= steps 返回 1.0；steps <= 0 抛 ValueError。
    """
    if steps <= 0:
        raise ValueError(f"steps 必须为正整数，得到 {steps}")
    if i <= 0:
        return 0.0
    if i >= steps:
        return 1.0
    x = i / steps
    return 1.0 - (1.0 - x) ** 3


def ease_in_cubic(i: float, steps: int) -> float:
    """ease-in cubic：t = (i/steps)**3，边界与参数校验同 ease_out_cubic。"""
    if steps <= 0:
        raise ValueError(f"steps 必须为正整数，得到 {steps}")
    if i <= 0:
        return 0.0
    if i >= steps:
        return 1.0
    x = i / steps
    return x ** 3


def ease_in_out(i: float, steps: int) -> float:
    """ease-in-out cubic：前半段 ease-in、后半段 ease-out 拼接，中点恰为 0.5。"""
    if steps <= 0:
        raise ValueError(f"steps 必须为正整数，得到 {steps}")
    if i <= 0:
        return 0.0
    if i >= steps:
        return 1.0
    half = steps / 2.0
    if i <= half:  # 前一半：ease-in 缩放到 [0, 0.5]
        x = i / half
        return 0.5 * (x ** 3)
    # 后一半：ease-out 从 [0.5, 1]
    x = (i - half) / (steps - half)
    return 0.5 + 0.5 * (1.0 - (1.0 - x) ** 3)


# ---------------------------------------------------------------------------
# 3. Animator：帧调度状态机（纯数值推进，不 import tkinter / 不开线程）
# ---------------------------------------------------------------------------

# schedule=None 时使用的无操作调度器：不真调度、也不推进帧（测试会自己驱动队列）。
def _no_schedule(_fn: Callable[[], None], _delay_ms: int) -> Any:
    return None


class Animator:
    """基于可注入调度器的逐帧动画引擎。

    schedule: callable(fn, delay_ms) -> token。GUI 层注入
              lambda fn, ms: widget.after(ms, fn)，返回的 token（after id）
              留给 GUI 侧取消用；默认 None 表示不真调度（测试模式）。
    now: 可注入时钟，默认 time.monotonic（返回秒）；last_frame_ms 与进度计算都用它。
    max_active: 活动动画数超过该值时新动画降级为瞬时完成（默认 8）。
    frame_budget_ms: 上一帧回调实际耗时超过该值时新动画降级（默认 50）。
    frame_ms: 帧间隔毫秒（默认 16）；长驻动效建议放宽以降低主线程重绘压力。
    """

    FRAME_MS = 16  # 帧间隔（约 60fps），与设计规范 after(16) 一致

    def __init__(self,
                 schedule: Optional[Callable[[Callable[[], None], int], Any]] = None,
                 now: Optional[Callable[[], float]] = None,
                 max_active: int = 8,
                 frame_budget_ms: float = 50.0,
                 frame_ms: int = 16):
        self.schedule = schedule if schedule is not None else _no_schedule
        self.now = now if now is not None else time.monotonic
        self.max_active = max_active
        self.frame_budget_ms = frame_budget_ms
        # 帧间隔（毫秒）。GUI 长驻动效（呼吸循环）可放宽到 33-50ms 降低
        # 主线程重绘压力；瞬时过渡类保持默认 16ms。
        self.frame_ms = frame_ms
        # 活跃动画注册表：anim_id -> (开始时间, duration_ms)
        self._active: Dict[int, Tuple[float, float]] = {}
        # anim_id -> (callback, on_done)（回调与注册表分离，注册表保持纯时序数据）
        self._hooks: Dict[int, Tuple[Callable[[float], None], Optional[Callable[[], None]]]] = {}
        # anim_id -> 本段动画的帧间隔（ms；animate 未指定时取实例 frame_ms）
        self._frames: Dict[int, int] = {}
        self._next_id = 0
        self._last_frame_ms = 0.0  # 上一次帧回调实际耗时（用 now 时钟测量）

    # -- 内部工具 ----------------------------------------------------------

    def last_frame_ms(self) -> float:
        """上一次帧回调实际耗时（毫秒）。没跑过帧时为 0.0。"""
        return self._last_frame_ms

    def _should_degrade(self) -> bool:
        return len(self._active) > self.max_active or self._last_frame_ms > self.frame_budget_ms

    def _instant(self, callback: Callable[[float], None],
                 on_done: Optional[Callable[[], None]]) -> None:
        """瞬时完成：callback(1) + on_done 直接调，不进注册表、不调度。"""
        try:
            callback(1.0)
        except Exception:  # 回调异常不得泄漏，打印到 stderr 后继续保证 on_done
            print(f"[motion] anim callback 异常: {sys.exc_info()[1]}", file=sys.stderr)
        if on_done is not None:
            try:
                on_done()
            except Exception:
                print(f"[motion] anim on_done 异常: {sys.exc_info()[1]}", file=sys.stderr)

    def _frame(self, anim_id: int, p: float) -> None:
        """执行一帧：计时（更新 last_frame_ms）、回调、异常兜底、终帧调 on_done。"""
        hooks = self._hooks.get(anim_id)
        if hooks is None:
            return
        callback, on_done = hooks
        t0 = self.now()
        try:
            callback(p)
        except Exception:
            print(f"[motion] anim {anim_id} callback 异常: {sys.exc_info()[1]}",
                  file=sys.stderr)
        self._last_frame_ms = max(0.0, (self.now() - t0) * 1000.0)
        if p >= 1.0:
            # 先出注册表，on_done 里再开新动画不受影响
            self._active.pop(anim_id, None)
            self._hooks.pop(anim_id, None)
            self._frames.pop(anim_id, None)
            if on_done is not None:
                try:
                    on_done()
                except Exception:
                    print(f"[motion] anim {anim_id} on_done 异常: {sys.exc_info()[1]}",
                          file=sys.stderr)

    def _step(self, anim_id: int, start: float, duration: float) -> None:
        """一帧推进：算 p = elapsed/duration，p 从 0 单调到 1；未到终帧则自调度下一帧。"""
        if anim_id not in self._active:
            return  # 已被 cancel
        elapsed_ms = (self.now() - start) * 1000.0
        p = min(1.0, max(0.0, elapsed_ms / duration))
        self._frame(anim_id, p)
        if anim_id in self._active:
            self.schedule(lambda: self._step(anim_id, start, duration),
                          self._frames.get(anim_id, self.frame_ms))

    # -- 公开 API -----------------------------------------------------------

    def animate(self, callback: Callable[[float], None],
                duration_ms: float, on_done: Optional[Callable[[], None]] = None,
                frame_ms: Optional[int] = None) -> int:
        """启动一段动画，返回 anim_id。

        每帧算进度 p = elapsed/duration（0 → 1 单调），把 p 传给 callback；
        GUI 侧在 callback(p) 里做 hex 插值渲染。frame_ms 覆盖本段动画的帧间隔
        （None 用实例默认 self.frame_ms；长驻动效放宽、瞬时过渡用 16ms）。
        duration_ms <= 0 时同步直跳 callback(1) 并立即调 on_done；启动前检查：
        活动数 > max_active 或上一帧超 frame_budget_ms 时降级为瞬时完成。
        瞬时完成 / 直跳场景不进入注册表，返回 -1 表示无 anim_id。
        """
        if duration_ms <= 0:
            self._instant(callback, on_done)
            return -1  # 未进入注册表，无有效 anim_id
        if self._should_degrade():
            self._instant(callback, on_done)
            return -1
        self._next_id += 1
        anim_id = self._next_id
        start = self.now()
        interval = int(frame_ms) if frame_ms is not None else self.frame_ms
        self._active[anim_id] = (start, float(duration_ms))
        self._hooks[anim_id] = (callback, on_done)
        self._frames[anim_id] = interval
        # 用注入的 schedule 自调度第一帧（每帧 schedule(step, interval)），不依赖 Tk after 也不开线程。
        self.schedule(lambda: self._step(anim_id, start, float(duration_ms)), interval)
        return anim_id

    def cancel(self, anim_id: int) -> bool:
        """取消动画。成功（仍在活动注册表）返回 True，否则 False。不回调、不调 on_done。"""
        if self._active.pop(anim_id, None) is None:
            return False
        self._hooks.pop(anim_id, None)
        self._frames.pop(anim_id, None)
        return True

    def cancel_all(self) -> None:
        """取消全部活动动画（已排队的帧回调发现不在注册表即自停）。"""
        self._active.clear()
        self._hooks.clear()
        self._frames.clear()


# ---------------------------------------------------------------------------
# 内联演示：假 schedule（列表收集）+ 假时钟手动驱动到完成，p 单调且末帧 1.0
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _q: list = []

    def fake_schedule(fn, _ms):
        _q.append(fn)
        return len(_q)

    # 假时钟：每帧推进 16ms，7 帧后恰好 p=1.0（96ms 时长）
    ticks = iter(t / 1000.0 for t in range(0, 200, 16))  # 每次时钟读取推进 16ms
    a = Animator(schedule=fake_schedule, now=lambda: next(ticks))
    ps, done = [], []

    a.animate(lambda p: ps.append(p), 96, lambda: done.append(True))
    while _q:                          # 手动驱动：弹出并执行所有排队帧
        _q.pop(0)()

    print("p 序列:", [round(p, 2) for p in ps])
    print("p 单调:", ps == sorted(ps), "| 末帧 1.0:", ps[-1] == 1.0,
          "| on_done:", done == [True], "| 注册表空:", not a._active)

    # 降级：max_active=2，已启动 3 个（活动数 3 > 2），第 4 个应瞬时完成
    a = Animator(schedule=fake_schedule, max_active=2)
    for _ in range(3):
        a.animate(lambda p: None, 100)
    before = len(_q)
    got = []
    a.animate(lambda p: got.append(p), 100, lambda: got.append("done"))
    print("超 max_active 降级为瞬时完成（callback(1)+on_done、无新帧调度）:",
          got == [1.0, "done"] and len(_q) == before)

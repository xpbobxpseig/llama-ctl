# -*- coding: utf-8 -*-
"""motion.py 单测：纯数值模块，全部用假 schedule（列表收集）与假时钟驱动，毫秒级跑完，不 import tkinter。

覆盖：hex 工具 / 缓动函数 / Animator 帧推进与降级 / 异常兜底 / cancel。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from motion import (
    Animator,
    ease_in_cubic,
    ease_in_out,
    ease_out_cubic,
    format_hex,
    lerp,
    parse_hex,
)


# ---------------------------------------------------------------------------
# 测试基础设施：假调度器（收集帧回调） + 假时钟（手动推进）
# ---------------------------------------------------------------------------


class FakeClock:
    """假时钟：手动 advance 推进秒数，取代 time.monotonic。"""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


@pytest.fixture
def env():
    """返回 (q, clock, animator)：q 收集 (fn, delay_ms)，clock 可手动推进。"""
    q = []
    clock = FakeClock()

    def sched(fn, delay_ms):
        q.append((fn, delay_ms))
        return len(q)

    return q, clock, Animator(schedule=sched, now=clock)


def drain(q, clock, max_frames=1000):
    """弹出并执行全部排队帧；每执行一帧前先把时钟推进该帧的延迟。"""
    ran = 0
    while q:
        fn, delay_ms = q.pop(0)
        clock.advance(delay_ms / 1000.0)
        fn()
        ran += 1
        assert ran <= max_frames, "动画帧数异常，疑似死循环"
    return ran


# ---------------------------------------------------------------------------
# 1. hex 工具
# ---------------------------------------------------------------------------


def test_parse_hex_full():
    assert parse_hex("#0a84ff") == (10, 132, 255)
    assert parse_hex("0a84ff") == (10, 132, 255)


def test_parse_hex_short_expands():
    assert parse_hex("#fff") == (255, 255, 255)
    assert parse_hex("#0af") == (0, 170, 255)


def test_parse_hex_trims_whitespace():
    assert parse_hex("  #30d158  ") == (48, 209, 88)


@pytest.mark.parametrize("bad", ["12345", "#gg0000", "1234567", "", "#", "#0", "#00"] )
def test_parse_hex_invalid_raises(bad):
    with pytest.raises(ValueError):
        parse_hex(bad)


@pytest.mark.parametrize("bad", [123456, None, [1, 2, 3], (10, 132, 255)])
def test_parse_hex_non_string_raises(bad):
    with pytest.raises(ValueError):
        parse_hex(bad)


def test_format_hex_lowercase():
    assert format_hex((10, 132, 255)) == "#0a84ff"


def test_format_hex_clamps_and_rounds():
    assert format_hex((-5, 300, 0.6)) == "#00ff01"
    assert format_hex((0, 0, 0)) == "#000000"
    assert format_hex((255, 255, 255)) == "#ffffff"


def test_format_hex_bad_tuple_raises():
    with pytest.raises(ValueError):
        format_hex((1, 2))


def test_lerp_hex_and_tuple_mix():
    assert lerp("#000000", "#ffffff", 0.5) == (128, 128, 128)
    assert lerp((0, 0, 0), "#0a84ff", 0.5) == (5, 66, 128)
    assert lerp("#0a84ff", (255, 255, 255), 1.0) == (255, 255, 255)


def test_lerp_t_clamps_to_unit():
    assert lerp("#000000", "#ffffff", -3) == (0, 0, 0)
    assert lerp("#000000", "#ffffff", 9) == (255, 255, 255)


def test_lerp_bad_input_raises():
    with pytest.raises(ValueError):
        lerp((1, 2), "#ffffff", 0.5)
    with pytest.raises(ValueError):
        lerp("xyz", "#ffffff", 0.5)


# ---------------------------------------------------------------------------
# 2. 缓动函数
# ---------------------------------------------------------------------------


def test_ease_out_cubic_boundaries():
    assert ease_out_cubic(0, 10) == 0.0
    assert ease_out_cubic(10, 10) == 1.0
    assert ease_out_cubic(99, 10) == 1.0
    assert ease_out_cubic(-5, 10) == 0.0


def test_ease_out_cubic_midpoint():
    assert ease_out_cubic(5, 10) == pytest.approx(0.875)


def test_ease_in_cubic_boundaries_and_midpoint():
    assert ease_in_cubic(0, 10) == 0.0
    assert ease_in_cubic(10, 10) == 1.0
    assert ease_in_cubic(5, 10) == pytest.approx(0.125)


def test_ease_in_out_splice():
    assert ease_in_out(0, 10) == 0.0
    assert ease_in_out(10, 10) == 1.0
    assert ease_in_out(5, 10) == pytest.approx(0.5)
    # 前半 ease-in：1/4 处 = 0.5*(0.5**3) = 0.0625
    assert ease_in_out(2.5, 10) == pytest.approx(0.0625)
    # 后半 ease-out：3/4 处 = 1 - 0.0625 = 0.9375
    assert ease_in_out(7.5, 10) == pytest.approx(0.9375)


@pytest.mark.parametrize("fn", [ease_out_cubic, ease_in_cubic, ease_in_out])
def test_ease_steps_nonpositive_raises(fn):
    with pytest.raises(ValueError):
        fn(1, 0)
    with pytest.raises(ValueError):
        fn(1, -3)


@pytest.mark.parametrize("fn", [ease_out_cubic, ease_in_cubic, ease_in_out])
def test_ease_monotonic_and_bounded(fn):
    vals = [fn(i, 100) for i in range(0, 101)]
    assert vals == sorted(vals)
    assert min(vals) >= 0.0 and max(vals) <= 1.0


def test_ease_in_out_seam_continuous():
    # 中点接缝两侧无限接近时值也应接近（无跳变）
    assert ease_in_out(4, 8) == pytest.approx(ease_in_out(4.000001, 8), abs=1e-4)


# ---------------------------------------------------------------------------
# 3. Animator：帧推进
# ---------------------------------------------------------------------------


def test_animate_full_run(env):
    q, clock, a = env
    ps, done = [], []
    aid = a.animate(lambda p: ps.append(round(p, 6)), 160, lambda: done.append(True))
    assert aid >= 1
    assert len(q) == 1 and q[0][1] == 16, "首帧应以 16ms 调度"
    drain(q, clock)
    assert ps[0] > 0.0 and ps[0] < 1.0
    assert ps == sorted(ps), "p 必须单调"
    assert ps[-1] == 1.0
    assert len(ps) == len(set(ps)), "p 必须严格递增"
    assert done == [True]
    assert not a._active, "完成后注册表应为空"


def test_animate_first_frame_zero_elapsed_is_p_zero(env):
    q, clock, a = env
    ps = []
    a.animate(lambda p: ps.append(p), 160)
    q.pop(0)[0]()  # 时钟未推进 -> elapsed=0 -> p=0.0
    assert ps == [0.0]


def test_animate_every_frame_scheduled_at_16ms(env):
    q, clock, a = env
    a.animate(lambda p: None, 160)
    delays = []
    while q:
        fn, ms = q.pop(0)
        delays.append(ms)
        clock.advance(ms / 1000.0)
        fn()
    assert delays and all(d == 16 for d in delays)


def test_animate_duration_zero_instant(env):
    q, clock, a = env
    ps, done = [], []
    aid = a.animate(lambda p: ps.append(p), 0, lambda: done.append(True))
    assert aid == -1
    assert ps == [1.0] and done == [True]
    assert not q and not a._active, "直跳不应调度任何帧"


def test_animate_duration_negative_instant(env):
    q, clock, a = env
    ps, done = [], []
    a.animate(lambda p: ps.append(p), -5, lambda: done.append(True))
    assert ps == [1.0] and done == [True]


def test_cancel_active_returns_true_and_halts(env):
    q, clock, a = env
    ps, done = [], []
    aid = a.animate(lambda p: ps.append(p), 160, lambda: done.append(True))
    assert a.cancel(aid) is True
    assert a.cancel(aid) is False, "重复 cancel 应返回 False"
    drain(q, clock)
    assert ps == [] and done == [], "cancel 后不得再回调、不得调 on_done"
    assert not a._active


def test_cancel_unknown_id_returns_false(env):
    q, clock, a = env
    assert a.cancel(999) is False


def test_cancel_all(env):
    q, clock, a = env
    for _ in range(3):
        a.animate(lambda p: None, 200)
    assert len(a._active) == 3
    a.cancel_all()
    assert not a._active
    drain(q, clock)  # 已排队帧发现不在注册表即自停


# ---------------------------------------------------------------------------
# 4. 异常兜底：callback / on_done 异常不得泄漏，on_done 仍被调
# ---------------------------------------------------------------------------


def test_callback_exception_contained_on_done_runs(env):
    q, clock, a = env
    done = []

    def bad(p):
        if p < 1.0:
            raise RuntimeError("boom")

    err = io.StringIO()
    old = sys.stderr
    sys.stderr = err
    try:
        a.animate(bad, 100, lambda: done.append(True))
        drain(q, clock)  # 异常被吞掉不应让 drain 崩溃
    finally:
        sys.stderr = old
    assert done == [True], "callback 异常后 on_done 仍须被调"
    assert "boom" in err.getvalue(), "异常应打印到 stderr"
    assert not a._active


def test_on_done_exception_contained(env):
    q, clock, a = env

    def bad_done():
        raise RuntimeError("doneboom")

    err = io.StringIO()
    old = sys.stderr
    sys.stderr = err
    try:
        a.animate(lambda p: None, 60, bad_done)
        drain(q, clock)
    finally:
        sys.stderr = old
    assert "doneboom" in err.getvalue()
    assert not a._active


def test_instant_path_exception_contained(env):
    """duration<=0 的瞬时路径同样要兜底。"""
    q, clock, a = env
    done = []
    err = io.StringIO()
    old = sys.stderr
    sys.stderr = err
    try:
        a.animate(lambda p: (_ for _ in ()).throw(RuntimeError("instboom")), 0,
                  lambda: done.append(True))
    finally:
        sys.stderr = old
    assert done == [True]
    assert "instboom" in err.getvalue()


# ---------------------------------------------------------------------------
# 5. 降级策略（design-guide §五：>8 活动动画 或 单帧 >50ms）
# ---------------------------------------------------------------------------


def test_degrade_when_active_exceeds_max(env):
    q, clock, a = env
    a.max_active = 2
    for _ in range(3):  # 占满到 3 > 2
        a.animate(lambda p: None, 100)
    before = len(q)
    got = []
    aid = a.animate(lambda p: got.append(p), 100, lambda: got.append("done"))
    assert got == [1.0, "done"], "降级应为瞬时完成：callback(1) + on_done"
    assert aid == -1, "降级动画不进注册表，无 anim_id"
    assert len(q) == before, "降级动画不得调度新帧"
    assert len(a._active) == 3, "注册表不受影响"


def test_animate_instant_returns_minus_one_not_registered(env):
    """契约：瞬时完成（duration<=0）与降级路径返回 -1（无 anim_id），不进注册表；
    cancel(-1) 返回 False 且不误伤其他活动动画。"""
    q, clock, a = env
    # 瞬时路径（duration<=0）
    got1 = []
    assert a.animate(lambda p: got1.append(p), 0) == -1
    assert got1 == [1.0]
    assert not a._active, "瞬时完成不得进注册表"
    # 降级路径（活动数超 max_active）
    a.max_active = 2
    for _ in range(3):
        a.animate(lambda p: None, 100)
    assert len(a._active) == 3
    got2 = []
    assert a.animate(lambda p: got2.append(p), 100) == -1
    assert got2 == [1.0]
    assert len(a._active) == 3, "降级不得改动注册表"
    # cancel(-1)：False，且不误伤仍在活动的动画
    assert a.cancel(-1) is False
    assert len(a._active) == 3


def test_normal_path_id_cancel_semantics(env):
    """对照：正常路径返回正 id，cancel 有效；cancel 后再 cancel 同 id 返回 False。"""
    q, clock, a = env
    aid = a.animate(lambda p: None, 100)
    assert aid >= 1
    assert a.cancel(aid) is True
    assert a.cancel(aid) is False

def test_default_max_active_is_8(env):
    q, clock, a = env
    assert a.max_active == 8
    assert a.frame_budget_ms == 50


def test_degrade_when_frame_over_budget(env):
    q, clock, a = env
    a.frame_budget_ms = 10

    def slow(p):
        clock.advance(0.2)  # 回调期间时钟前进 200ms，模拟慢帧

    a.animate(slow, 100)
    fn, _ = q.pop(0)
    clock.advance(0.016)
    fn()
    assert a.last_frame_ms() > 150, "last_frame_ms 应记录慢帧耗时"
    got = []
    a.animate(lambda p: got.append(p), 100, lambda: got.append("done"))
    assert got == [1.0, "done"], "超帧预算后新动画应瞬时完成"


def test_last_frame_ms_starts_zero(env):
    q, clock, a = env
    assert a.last_frame_ms() == 0.0


def test_default_schedule_does_not_drive_frames():
    """schedule=None（默认）时不真调度，动画只进注册表等外部驱动。"""
    clock = FakeClock()
    a = Animator(now=clock)
    aid = a.animate(lambda p: None, 100)
    assert aid == 1
    assert len(a._active) == 1
    assert a.cancel(aid) is True


def test_registry_shape_is_start_and_duration_only(env):
    """契约：注册表为 {anim_id: (开始时间, duration)}。"""
    q, clock, a = env
    aid = a.animate(lambda p: None, 100)
    start, duration = a._active[aid]
    assert start == 0.0 and duration == 100.0


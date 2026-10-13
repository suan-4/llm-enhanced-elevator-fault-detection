"""雪花 ID 生成器测试。

这台板子的 RTC 不可信（开机会回到 2021-01-01），而雪花 ID 恰好依赖时钟。
生成器一旦在这里出错，后果是主键重复，属数据事故。因此设计文档 §5.5 的
5 条验收全部落成自动化用例。

时钟是注入的（clock 参数），所以"时钟回拨""重启后又回到 2021 年"这类场景
可以稳定复现，不靠 sleep 碰运气。

不依赖 pytest：直接 python backend/tests/test_snowflake.py
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.repo.ids import (  # noqa: E402
    EPOCH_MS,
    SEQ_BITS,
    TIME_SHIFT,
    WORKER_BITS,
    Snowflake,
    restore_last_ms,
)


class FakeClock:
    """可控毫秒时钟：测试里不让时间自己走。"""

    def __init__(self, ms: int) -> None:
        self.ms = ms

    def __call__(self) -> int:
        return self.ms

    def advance(self, ms: int) -> None:
        self.ms += ms


def test_ids_are_unique_and_increasing() -> None:
    """连续生成 10 万个：不重复、严格递增。"""
    clock = FakeClock(EPOCH_MS + 10_000)
    gen = Snowflake(worker_id=1, clock=clock)
    ids = []
    for i in range(100_000):
        ids.append(gen.next_id())
        if i % 500 == 499:
            clock.advance(1)
    assert len(set(ids)) == len(ids), "出现重复 ID"
    assert ids == sorted(ids), "ID 不是严格递增"


def test_same_millisecond_sequence_increases() -> None:
    """同一毫秒内也要严格递增（靠序号位）。"""
    clock = FakeClock(EPOCH_MS + 1)
    gen = Snowflake(worker_id=7, clock=clock)
    ids = [gen.next_id() for _ in range(100)]
    assert len(set(ids)) == 100
    assert ids == sorted(ids)
    assert [i & ((1 << SEQ_BITS) - 1) for i in ids] == list(range(100))


def test_sequence_resets_on_next_millisecond() -> None:
    """跨毫秒后序号归零。"""
    clock = FakeClock(EPOCH_MS + 1)
    gen = Snowflake(worker_id=1, clock=clock)
    gen.next_id()
    gen.next_id()
    clock.advance(1)
    third = gen.next_id()
    assert third & ((1 << SEQ_BITS) - 1) == 0


def test_clock_rollback_keeps_ids_unique_and_counts_event() -> None:
    """时钟被大幅回拨：不报错，继续单调递增，但要记账以便排查。"""
    clock = FakeClock(EPOCH_MS + 1_000_000)
    gen = Snowflake(worker_id=1, clock=clock)
    last = gen.next_id()
    clock.ms -= 3_600_000
    again = [gen.next_id() for _ in range(10)]
    assert all(i > last for i in again), "回拨后发出的 ID 必须仍大于之前的"
    assert len(set(again)) == 10
    assert gen.rollback_events == 1, "回拨应当被记录一次"


def test_restore_last_ms_roundtrip() -> None:
    """能从 ID 反推出当初的时间戳（重启保护的基础）。"""
    ms = EPOCH_MS + 123_456
    gen = Snowflake(worker_id=3, clock=FakeClock(ms))
    value = gen.next_id()
    assert restore_last_ms(value) == ms
    assert restore_last_ms(None) == 0


def test_restart_with_wrong_clock_continues_forward() -> None:
    """关键场景：正常发号后重启，时钟回到 2021 年，新号必须大于旧号。"""
    gen1 = Snowflake(worker_id=1, clock=FakeClock(EPOCH_MS + 5_000_000))
    old_max = max(gen1.next_id() for _ in range(5))

    wrong_clock = FakeClock(1620000000000)
    gen2 = Snowflake(worker_id=1, last_id=old_max, clock=wrong_clock)
    fresh = [gen2.next_id() for _ in range(5)]
    assert min(fresh) > old_max, "重启后不得发出比旧号更小的 ID"


def test_restart_within_same_millisecond_continues_after_last_seq() -> None:
    """更狠的一种：重启发生在同一毫秒内，序号也必须接着上次走。

    （只恢复时间戳、不恢复序号就会栽在这里：新进程会从序号 0 重来，
    发出比旧号更小的 id —— 这条用例就是为这个 bug 写的。）
    """
    clock = FakeClock(EPOCH_MS + 7_000_000)
    gen1 = Snowflake(worker_id=1, clock=clock)
    old = [gen1.next_id() for _ in range(5)]
    gen2 = Snowflake(worker_id=1, last_id=max(old), clock=clock)
    fresh = [gen2.next_id() for _ in range(3)]
    assert min(fresh) > max(old), f"重启后序号应接着走：old_max={max(old)} fresh={fresh}"


def test_worker_id_out_of_range_rejected() -> None:
    """工作节点只有 10 位，越界要早失败而不是悄悄发重号。"""
    for bad in (-1, 1 << WORKER_BITS):
        try:
            Snowflake(worker_id=bad)
        except ValueError:
            continue
        raise AssertionError(f"worker_id={bad} 应当被拒绝")


def test_thread_safety_no_duplicates() -> None:
    """多线程并发生成（真实时钟）：不重复。"""
    gen = Snowflake(worker_id=2)
    out: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        local = [gen.next_id() for _ in range(25_000)]
        with lock:
            out.extend(local)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(out) == 200_000
    assert len(set(out)) == 200_000, "并发下出现重复 ID"


def test_layout_bits() -> None:
    """位布局固定：时间戳 41 位 + 节点 10 位 + 序号 12 位。"""
    assert TIME_SHIFT == 22
    assert SEQ_BITS == 12 and WORKER_BITS == 10


def _main() -> int:
    tests = [
        ("10 万个不重复且递增", test_ids_are_unique_and_increasing),
        ("同毫秒内递增", test_same_millisecond_sequence_increases),
        ("跨毫秒序号归零", test_sequence_resets_on_next_millisecond),
        ("时钟回拨不重复且记账", test_clock_rollback_keeps_ids_unique_and_counts_event),
        ("从 ID 反推时间戳", test_restore_last_ms_roundtrip),
        ("重启后时钟错误仍向前", test_restart_with_wrong_clock_continues_forward),
        ("同毫秒内重启接着上次序号", test_restart_within_same_millisecond_continues_after_last_seq),
        ("工作节点越界被拒", test_worker_id_out_of_range_rejected),
        ("多线程不重复", test_thread_safety_no_duplicates),
        ("位布局固定", test_layout_bits),
    ]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  [PASS] {name}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {name}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  [ERROR] {name}: {type(e).__name__}: {e}")
    print()
    print(f"合计 {len(tests)} 项，通过 {len(tests) - failed}，失败 {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())

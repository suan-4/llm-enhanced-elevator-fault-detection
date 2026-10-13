"""雪花 ID 生成器（设计见《数据库设计 v1》§5）。

位布局（共 63 位可用）：
    1 位符号位恒 0
   41 位毫秒时间戳（相对自定义纪元，可用约 69 年）
   10 位工作节点 id（0~1023，一台终端一个值）
   12 位同毫秒序号（0~4095）

为什么不用数据库自增：将来可能上多台终端，自增必然撞号；而且应用侧生成
可以在插入前就拿到 id。

**时钟策略（本文件最关键的部分）**
这台板子的 RTC 不可信，开机会回到 2021-01-01，所以"时钟落后"是常态而不是
异常。因此生成器**从不因为时钟回拨而报错**——报错等于每次开机系统都用不了。
它只保证一件事：**单调递增、绝不重复**。做法是"时钟落后就沿上次的时间戳继续"，
并把明显的回拨记一次账（rollback_events + 日志），供排查。

id 里的时间戳**不参与任何业务时间**（业务时间看 created_at 等字段），
所以即便时间戳不自洽也不影响报告。
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

EPOCH_MS = 1767225600000  # 2026-01-01 00:00:00 +08:00

WORKER_BITS = 10
SEQ_BITS = 12
WORKER_SHIFT = SEQ_BITS
TIME_SHIFT = SEQ_BITS + WORKER_BITS
SEQ_MASK = (1 << SEQ_BITS) - 1
MAX_WORKER_ID = (1 << WORKER_BITS) - 1

# 时钟落后不超过这个毫秒数，视为"同毫秒内的正常抖动"，不记账。
ROLLBACK_TOLERANCE_MS = 5

_log = logging.getLogger(__name__)


def _wall_clock_ms() -> int:
    """墙上时钟（毫秒）。单独抽出来是为了测试能注入假时钟。"""
    return int(time.time() * 1000)


class Snowflake:
    """线程安全的雪花 ID 生成器。"""

    def __init__(
        self,
        worker_id: int,
        last_id: int | None = None,
        clock: Callable[[], int] | None = None,
    ) -> None:
        if not 0 <= worker_id <= MAX_WORKER_ID:
            raise ValueError(f"worker_id 必须落在 0~{MAX_WORKER_ID}")
        self.worker_id = worker_id
        self.rollback_events = 0
        self._clock = clock or _wall_clock_ms
        # 关键：重启保护必须同时恢复"时间戳"和"序号"。
        # 只恢复时间戳的话，同一毫秒内重启会从序号 0 重来，发出比旧号更小的 id。
        if last_id:
            self._last_ms = restore_last_ms(last_id)
            self._seq = last_id & SEQ_MASK
        else:
            self._last_ms = 0
            self._seq = 0
        self._rollback_active = False
        self._lock = threading.Lock()

    def next_id(self) -> int:
        with self._lock:
            now = self._clock()

            if now < self._last_ms:
                # 时钟落后（板子常态）：沿上次的时间戳继续，绝不倒退。
                gap = self._last_ms - now
                if gap > ROLLBACK_TOLERANCE_MS and not self._rollback_active:
                    self.rollback_events += 1
                    self._rollback_active = True
                    _log.warning(
                        "系统时间比上次发号落后 %d ms，ID 继续按上次时间戳递增（不报错、不重复）",
                        gap,
                    )
                now = self._last_ms
            else:
                self._rollback_active = False

            if now == self._last_ms:
                self._seq = (self._seq + 1) & SEQ_MASK
                if self._seq == 0:
                    # 同一毫秒 4096 个用满：把时间戳强行推进 1ms 再继续。
                    now = self._last_ms + 1
            else:
                self._seq = 0

            self._last_ms = now
            return ((now - EPOCH_MS) << TIME_SHIFT) | (self.worker_id << WORKER_SHIFT) | self._seq


def restore_last_ms(max_id: int | None) -> int:
    """从库里最大的 id 反推当初的时间戳，作为新进程的下界。

    这是"重启后时钟回到 2021 年也不会发重号"的关键：新进程从上次发到哪儿继续，
    而不是相信墙上时钟。
    """
    if not max_id:
        return 0
    return (max_id >> TIME_SHIFT) + EPOCH_MS


def peek_ms(value: int) -> int:
    """从一个 id 里读出它编码的时间戳（排查用）。"""
    return (value >> TIME_SHIFT) + EPOCH_MS


# ── 进程内单例：业务代码统一用 next_id() ──────────────────────
_singleton: Snowflake | None = None
_singleton_lock = threading.Lock()


def configure(worker_id: int, last_id: int | None = None) -> Snowflake:
    """启动时配置一次。last_id 传库里各业务表的 MAX(id)（无数据则传 None）。"""
    global _singleton
    with _singleton_lock:
        _singleton = Snowflake(worker_id=worker_id, last_id=last_id)
        return _singleton


def next_id() -> int:
    """取一个新的雪花 ID。未配置时按 worker_id=1 自动配置。"""
    if _singleton is None:
        configure(1)
    return _singleton.next_id()  # type: ignore[union-attr]


def rollback_events() -> int:
    """累计的时钟回拨次数（诊断接口用）。"""
    return _singleton.rollback_events if _singleton else 0

"""登录失败计数与锁定（**内存态**）。

为什么不落库：终端场景下"重启清零"完全可以接受，为它建一张表不值
（《数据库设计 v1》§3.2 把它砍掉了）。锁定的目的是挡住连点/记错口令，
不是防远程爆破 —— 这台机器本来就在现场、离线。
"""
from __future__ import annotations

import threading
import time
from typing import Callable


class LoginGuard:
    def __init__(self, max_fail: int = 5, lock_minutes: int = 10,
                 clock: Callable[[], float] | None = None) -> None:
        self.max_fail = max_fail
        self.lock_seconds = lock_minutes * 60
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._failed: dict[str, int] = {}
        self._locked_until: dict[str, float] = {}

    def remaining(self, username: str) -> int:
        """剩余锁定秒数；0 表示未锁定（过期的顺手清掉）。"""
        key = username.strip()
        until = self._locked_until.get(key, 0.0)
        left = int(until - self._clock())
        if left <= 0:
            self._locked_until.pop(key, None)
            return 0
        return left

    def record_failure(self, username: str) -> int:
        """记一次失败；达到阈值就锁定，返回剩余锁定秒数。"""
        key = username.strip()
        with self._lock:
            count = self._failed.get(key, 0) + 1
            self._failed[key] = count
            if count >= self.max_fail:
                self._locked_until[key] = self._clock() + self.lock_seconds
                self._failed[key] = 0
        return self.remaining(username)

    def reset(self, username: str) -> None:
        key = username.strip()
        with self._lock:
            self._failed.pop(key, None)
            self._locked_until.pop(key, None)

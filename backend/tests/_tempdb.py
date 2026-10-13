"""测试用的临时数据库工具（三个测试文件共用，避免各写一份）。"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402


class TempDB:
    """把 db.DB_PATH 指向临时文件，退出时删除（含 WAL 边车文件）。"""

    def __enter__(self):
        fd, self.path = tempfile.mkstemp(prefix="elevator-test-", suffix=".db")
        os.close(fd)
        self._old = db.DB_PATH
        db.DB_PATH = Path(self.path)
        db.init_db()
        return self.path

    def __exit__(self, *exc):
        db.DB_PATH = self._old
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(self.path + suffix)
            except OSError:
                pass
        return False

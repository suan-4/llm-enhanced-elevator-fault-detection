"""命令行迁移工具：旧结构 → v1 基础版。

用法（板端或开发机）：

    python backend/tools/migrate_v1.py            # 先备份，再迁移
    python backend/tools/migrate_v1.py --dry-run  # 只看会做什么，不改库

顺序很重要：
    1. 备份（用 SQLite 在线备份 API，WAL 下直接拷文件会丢事务）；
    2. 迁移（一个事务里完成，出错整体回滚）；
    3. 校验（行数、integrity_check、foreign_key_check）。

迁移完成后旧表会改名成 `*_legacy_20261013` 保留，不删除。
注意：迁移后旧接口（/api/auth/users、/api/history）就找不到 users 表了，
必须在"接口已切到新表"的版本上执行（见《数据库设计 v1》§9）。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app import db  # noqa: E402
from app.migrations import legacy_to_v1  # noqa: E402


def backup(path: Path) -> Path:
    """用在线备份 API 做一致性快照（不能直接拷文件）。"""
    target_dir = path.parent / "backup"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"pre-migrate-{datetime.now():%Y%m%d-%H%M%S}.db"
    src = sqlite3.connect(str(path))
    dst = sqlite3.connect(str(target))
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    return target


def verify(conn: sqlite3.Connection) -> list[str]:
    problems = []
    if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        problems.append("quick_check 未通过")
    bad = conn.execute("PRAGMA foreign_key_check").fetchall()
    if bad:
        problems.append(f"外键校验发现 {len(bad)} 条问题")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="电梯评估系统：旧结构迁移到 v1")
    parser.add_argument("--db", default=None, help="数据库路径（默认取配置）")
    parser.add_argument("--dry-run", action="store_true", help="只检查，不改库")
    args = parser.parse_args(argv)

    path = Path(args.db) if args.db else db.DB_PATH
    if not path.exists():
        print(f"数据库不存在：{path}")
        return 1

    db.DB_PATH = path
    version = db.user_version()
    print(f"数据库：{path}")
    print(f"当前 user_version = {version}")
    if version >= 1:
        print("已是 v1，无需迁移。")
        return 0

    if args.dry_run:
        with db.get_conn() as conn:
            tables = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                      for t in ("users", "sessions", "report_history", "form_draft")
                      if t in tables}
        print(f"将要迁移的数据量：{counts}")
        print("（--dry-run，未做任何修改）")
        return 0

    snapshot = backup(path)
    print(f"已备份到：{snapshot}")

    try:
        with db.get_conn() as conn:
            result = legacy_to_v1.run(conn)
            problems = verify(conn)
    except Exception as e:  # noqa: BLE001
        print(f"迁移失败：{type(e).__name__}: {e}")
        print(f"数据库未被改动（事务已回滚）。备份仍在：{snapshot}")
        return 1

    print(f"迁移结果：{result}")
    if problems:
        print("校验未通过，请用备份恢复：")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("校验通过（quick_check / foreign_key_check）。")
    print("旧表已改名为 *_legacy_20261013 保留；确认无误后可自行删除。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

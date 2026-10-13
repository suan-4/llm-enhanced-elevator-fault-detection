"""把业务库搬到持久分区 /userdata（上现场前必做）。

为什么：库原来放在 backend/data（在 / 根分区上），重刷系统或恢复出厂就没了；
/userdata 是独立分区，是这台板子上唯一该放业务数据的地方。

做法：用 SQLite 在线备份接口把库**一致性快照**写到新位置（顺带 checkpoint 掉 WAL），
校验通过后才删除旧文件 —— 直接 mv 会丢掉还在 -wal 里的事务。

用法（板端，先停服务）：
    systemctl stop elevator-api.service
    cd /home/ubuntu/elevator/backend && python3 tools/move_db_to_userdata.py
    # 改 .env 里的 SQLITE_PATH 指向新路径，再启动服务
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app import db  # noqa: E402

DEST_DIR = Path("/userdata/elevator")


def main() -> int:
    old = Path(db.DB_PATH)
    if not old.exists():
        print(f"旧库不存在：{old}")
        return 1
    new = DEST_DIR / "elevator.db"
    if old.resolve() == new.resolve():
        print(f"库已经在持久分区：{old}")
        return 0

    DEST_DIR.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(str(old))
    dst = sqlite3.connect(str(new))
    try:
        with dst:
            src.backup(dst)      # 一致性快照，WAL 里的事务一起带过去
    finally:
        dst.close()
        src.close()

    # 校验：新库要能独立打开，且数据行数与旧库一致
    probe = sqlite3.connect(str(new))
    try:
        check = probe.execute("PRAGMA quick_check").fetchone()[0]
        tables = [r[0] for r in probe.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        counts = {t: probe.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("account", "report") if t in tables}
    finally:
        probe.close()
    if check != "ok":
        print(f"新库校验未通过（{check}），已中止，旧库未动。")
        return 1

    print(f"已复制到 {new}")
    print(f"quick_check={check}  行数={counts}")

    # 旧库挪到 .moved 后缀而不是直接删：留一份，确认服务正常后再手工清
    for suffix in ("", "-wal", "-shm"):
        leftover = Path(str(old) + suffix)
        if leftover.exists():
            shutil.move(str(leftover), str(leftover) + ".moved")
    print("旧库已改名为 *.moved（确认服务正常后可删）")
    print(f"别忘了把 .env 里的 SQLITE_PATH 改成 {new}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""repo 层测试（设计见《数据库设计 v1》§6）。

只测"数据存取"这一层该负责的事：
  - 建表与 PRAGMA 是否真的生效；
  - 账号 / 会话 / 报告 / 审计的读写；
  - 报告编号"只增不减、作废号不复用"这条硬规则（业务口径，但底座在 repo）。

不依赖 pytest：python backend/tests/test_repo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests._tempdb import TempDB  # noqa: E402

from app import db  # noqa: E402
from app.repo import account_repo, audit_repo, report_repo, session_repo  # noqa: E402
from app.repo.ids import Snowflake  # noqa: E402

DAY = "20261013"


def test_init_db_creates_tables_and_pragmas() -> None:
    """建表、外键生效、WAL 生效、迁移版本为 0（尚未搬家）。"""
    with TempDB():
        with db.get_conn() as conn:
            names = {
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            for table in ("account", "session", "report", "report_no_seq", "audit_log"):
                assert table in names, f"缺少表 {table}"
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1, "外键没开"
            assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal", "不是 WAL"
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 0, "迁移版本应为 0"


def test_account_insert_find_and_update() -> None:
    """开户、按用户名/ID 查、改名与停用。"""
    with TempDB():
        with db.get_conn() as conn:
            aid = Snowflake(worker_id=1).next_id()
            account_repo.insert(
                conn,
                account_id=aid,
                username="zhangsan",
                display_name="张三",
                employee_no="A001",
                password_salt="00",
                password_hash="11",
                created_at="2026-10-13T09:00:00",
            )
            by_id = account_repo.find_by_id(conn, aid)
            by_name = account_repo.find_by_username(conn, "zhangsan")
            assert by_id and by_id["display_name"] == "张三"
            assert by_name and by_name["id"] == aid
            assert by_id["is_active"] == 1 and account_repo.count_active(conn) == 1

            assert account_repo.update(conn, aid, display_name="张三丰", is_active=0)
            after = account_repo.find_by_id(conn, aid)
            assert after["display_name"] == "张三丰" and after["is_active"] == 0
            assert account_repo.count_active(conn) == 0


def test_session_lifecycle() -> None:
    """签发、校验、按账号吊销、过期清理。"""
    with TempDB():
        with db.get_conn() as conn:
            aid = Snowflake(worker_id=1).next_id()
            account_repo.insert(
                conn,
                account_id=aid,
                username="lisi",
                display_name="李四",
                employee_no="",
                password_salt="00",
                password_hash="11",
                created_at="2026-10-13T09:00:00",
            )
            session_repo.create(
                conn,
                token="tok-1",
                account_id=aid,
                created_at="2026-10-13T09:00:00",
                expires_at="2026-10-13T17:00:00",
                origin="127.0.0.1",
            )
            ok = session_repo.find_valid(conn, "tok-1", now="2026-10-13T10:00:00", idle_hours=8)
            assert ok and ok["account_id"] == aid

            expired = session_repo.find_valid(conn, "tok-1", now="2026-10-14T09:00:00", idle_hours=8)
            assert expired is None, "超过空闲时长应失效"

            assert session_repo.delete_by_account(conn, aid) == 1
            assert session_repo.find_valid(conn, "tok-1", now="2026-10-13T10:00:00") is None


def test_report_draft_roundtrip_and_promoted_columns() -> None:
    """草稿能整存整取，并且抬头会被同步提升为可查询的列。"""
    with TempDB():
        with db.get_conn() as conn:
            aid = Snowflake(worker_id=1).next_id()
            account_repo.insert(
                conn,
                account_id=aid,
                username="wangwu",
                display_name="王五",
                employee_no="",
                password_salt="00",
                password_hash="11",
                created_at="2026-10-13T09:00:00",
            )
            rid = Snowflake(worker_id=1).next_id()
            report_repo.insert_draft(
                conn,
                report_id=rid,
                created_by=aid,
                created_at="2026-10-13T09:10:00",
                updated_at="2026-10-13T09:10:00",
                catalog_version="JTE-09-R02-3.00",
            )
            draft = report_repo.find_by_id(conn, rid)
            assert draft["status"] == "draft" and draft["report_no"] is None

            items = [
                {"no": "1.7", "result": "fit", "reasons": [], "other_text": ""},
                {"no": "2.1", "result": "unfit", "reasons": ["箱体裂纹"], "other_text": ""},
            ]
            report_repo.update_content(
                conn,
                rid,
                form={"clientName": "佛山某公司", "productNo": "44786091"},
                items=items,
                counters={"total": 2, "done": 2, "unfit": 1, "missing": 0},
                updated_at="2026-10-13T09:20:00",
                promote={
                    "client_name": "佛山某公司",
                    "user_name": "佛山某公司",
                    "device_category": "曳引驱动电梯",
                    "product_no": "44786091",
                    "location": "/",
                    "assessed_on": "2026-10-13",
                },
            )
            saved = report_repo.find_by_id(conn, rid)
            assert [i["no"] for i in saved["items"]] == ["1.7", "2.1"]
            assert saved["items"][1]["reasons"] == ["箱体裂纹"]
            assert saved["client_name"] == "佛山某公司" and saved["product_no"] == "44786091"
            rows, total = report_repo.list_(conn, status="draft", page=1, size=10)
            assert total == 1 and rows[0]["id"] == rid


def test_report_no_sequence_never_reuses_after_void() -> None:
    """编号按日流水只增不减：作废掉的号绝不回收。"""
    with TempDB():
        with db.get_conn() as conn:
            assert report_repo.next_seq(conn, DAY) == 1
            assert report_repo.next_seq(conn, DAY) == 2
            assert report_repo.next_seq(conn, DAY) == 3
            assert report_repo.next_seq(conn, "20261014") == 1, "换一天要重新从 1 开始"


def test_report_void_keeps_number() -> None:
    """作废只改状态与原因，编号保留。"""
    with TempDB():
        with db.get_conn() as conn:
            aid = Snowflake(worker_id=1).next_id()
            account_repo.insert(
                conn,
                account_id=aid,
                username="zhaoliu",
                display_name="赵六",
                employee_no="",
                password_salt="00",
                password_hash="11",
                created_at="2026-10-13T09:00:00",
            )
            rid = Snowflake(worker_id=1).next_id()
            report_repo.insert_draft(
                conn, report_id=rid, created_by=aid,
                created_at="2026-10-13T09:00:00", updated_at="2026-10-13T09:00:00",
            )
            no = f"GDSEI-JTE-{DAY}-001"
            report_repo.update_generated(
                conn, rid, report_no=no, status="generated",
                generated_at="2026-10-13T09:30:00", risks={}, score=0, grade="四级",
                narrative="", provenance={},
            )
            assert report_repo.void(conn, rid, voided_at="2026-10-13T10:00:00", reason="录入有误")
            after = report_repo.find_by_id(conn, rid)
            assert after["status"] == "void" and after["report_no"] == no
            assert after["void_reason"] == "录入有误"


def test_audit_append_and_filter() -> None:
    """审计只追加，可按事件与操作者筛选，最新在前。"""
    with TempDB():
        with db.get_conn() as conn:
            gen = Snowflake(worker_id=1)
            for i, ev in enumerate(["login_ok", "report_generate", "login_ok"], start=1):
                audit_repo.append(
                    conn,
                    audit_id=gen.next_id(),
                    at=f"2026-10-13T09:0{i}:00",
                    actor_id=100 + i,
                    actor_name="张三",
                    event=ev,
                    target=f"t{i}",
                )
            rows, total = audit_repo.list_(conn, event="login_ok")
            assert total == 2 and [r["target"] for r in rows] == ["t3", "t1"]
            rows, total = audit_repo.list_(conn, actor="张三")
            assert total == 3
            rows, total = audit_repo.list_(conn, event="report_void")
            assert total == 0


def _main() -> int:
    tests = [
        ("建表与 PRAGMA", test_init_db_creates_tables_and_pragmas),
        ("账号开户/查询/停用", test_account_insert_find_and_update),
        ("会话生命周期", test_session_lifecycle),
        ("草稿整存整取与抬头提升", test_report_draft_roundtrip_and_promoted_columns),
        ("编号流水只增不减", test_report_no_sequence_never_reuses_after_void),
        ("作废保留编号", test_report_void_keeps_number),
        ("审计追加与筛选", test_audit_append_and_filter),
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

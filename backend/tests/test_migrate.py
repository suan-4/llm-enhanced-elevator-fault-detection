"""v0（旧 4 张表）→ v1（基础版 5 张表）迁移测试。

迁移是"只能跑一次、跑错很难回头"的操作，所以每条硬要求都给用例：
  - 账号搬过去、角色统一成 inspector；
  - 历史记录变成"已生成"报告，**并且补上报告编号**（否则老报告在列表里对不上纸面件）；
  - 草稿搬过去；
  - 旧表改名保留、版本号置 1、可以重复执行。

不依赖 pytest：python backend/tests/test_migrate.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests._tempdb import TempDB  # noqa: E402

from app import db  # noqa: E402
from app.migrations import legacy_to_v1  # noqa: E402
from app.repo import report_repo  # noqa: E402

DAY = "20261013"


def seed_legacy(conn) -> None:
    """造一份贴近旧版真实结构的数据。"""
    conn.executescript(
        """
        INSERT INTO users (id, username, display_name, password_salt, password_hash,
                           role, is_active, created_at, last_login_at)
        VALUES (1, 'admin', '系统管理员', '00', '11', 'admin', 1,
                '2026-10-01T08:00:00', '2026-10-13T08:30:00');

        INSERT INTO users (id, username, display_name, password_salt, password_hash,
                           role, is_active, created_at)
        VALUES (2, 'zhangsan', '张三', '22', '33', 'inspector', 1,
                '2026-10-02T08:00:00');

        INSERT INTO sessions (token, user_id, created_at, expires_at)
        VALUES ('tok-1', 2, '2026-10-13T08:00:00', '2026-10-20T08:00:00');

        INSERT INTO report_history (id, user_id, created_at, time_label, reg, location,
                                    items_count, states_count, report_text, fault_chain,
                                    form_data, items_data)
        VALUES (7, 2, '2026-10-13T10:00:00', '2026-10-13', 'R-001', '3号楼',
                66, 1, '这是一段旧报告正文', '[]',
                '{"clientName":"佛山某公司","userName":"佛山某公司","deviceCategory":"曳引驱动电梯","productNo":"44786091","assessDate":"2026-10-13"}',
                '{"1.7":{"result":"符合"},"2.1":{"result":"不符合","reasons":["箱体出现裂纹"]}}');

        INSERT INTO form_draft (user_id, form_data, items_data, updated_at)
        VALUES (2, '{"clientName":"草稿单位"}', '{"1.7":{"result":"符合"}}',
                '2026-10-13T11:00:00');
        """
    )


def _run(conn) -> dict:
    return legacy_to_v1.run(conn)


def test_accounts_migrated_with_single_role() -> None:
    """账号搬过去，admin 也统一成 inspector（单角色）。"""
    with TempDB():
        with db.get_conn() as conn:
            seed_legacy(conn)
            _run(conn)
            rows = conn.execute(
                "SELECT id, username, display_name, role, is_active FROM account ORDER BY username"
            ).fetchall()
            assert len(rows) == 2, f"应搬过去 2 个账号，实际 {len(rows)}"
            admin = [r for r in rows if r["username"] == "admin"][0]
            zhang = [r for r in rows if r["username"] == "zhangsan"][0]
            assert admin["role"] == "inspector" and zhang["role"] == "inspector"
            assert zhang["display_name"] == "张三"
            assert admin["id"] > 10**15, "新主键应是雪花 ID，而不是旧的 1、2"


def test_history_becomes_generated_report_with_number() -> None:
    """历史记录 → 已生成报告，且必须补上编号、提升抬头、转换条目结构。"""
    with TempDB():
        with db.get_conn() as conn:
            seed_legacy(conn)
            _run(conn)
            row = conn.execute("SELECT * FROM report WHERE status = 'generated'").fetchone()
            assert row is not None, "历史记录没有变成报告"
            assert row["report_no"] == f"GDSEI-JTE-{DAY}-001", row["report_no"]
            assert row["narrative"] == "这是一段旧报告正文"
            assert row["client_name"] == "佛山某公司" and row["product_no"] == "44786091"
            assert row["assessed_on"] == "2026-10-13"
            items = report_repo.find_by_id(conn, row["id"])["items"]
            assert [i["no"] for i in items] == ["1.7", "2.1"], items
            assert items[0]["result"] == "fit"
            assert items[1]["result"] == "unfit" and items[1]["reasons"] == ["箱体出现裂纹"]
            prov = report_repo.find_by_id(conn, row["id"])["provenance"]
            assert prov.get("legacy_id") == 7, "旧 id 要留痕以便追溯"


def test_form_draft_becomes_draft_report() -> None:
    """旧草稿 → 草稿报告（没有编号）。"""
    with TempDB():
        with db.get_conn() as conn:
            seed_legacy(conn)
            _run(conn)
            drafts = report_repo.list_drafts(
                conn, conn.execute("SELECT id FROM account WHERE username='zhangsan'").fetchone()["id"]
            )
            assert len(drafts) == 1, f"应有 1 份草稿，实际 {len(drafts)}"
            assert drafts[0]["report_no"] is None


def test_renames_legacy_tables_and_sets_version() -> None:
    """旧表改名保留（不删），版本号置 1。"""
    with TempDB():
        with db.get_conn() as conn:
            seed_legacy(conn)
            _run(conn)
            names = {
                r["name"]
                for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            assert "users" not in names, "旧 users 表应已改名"
            assert any(n.startswith("users_legacy_") for n in names), names
            assert any(n.startswith("report_history_legacy_") for n in names), names
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 1


def test_migration_is_idempotent() -> None:
    """重复执行不重复搬数据。"""
    with TempDB():
        with db.get_conn() as conn:
            seed_legacy(conn)
            _run(conn)
            before = conn.execute("SELECT COUNT(*) AS c FROM account").fetchone()["c"]
            second = _run(conn)
            after = conn.execute("SELECT COUNT(*) AS c FROM account").fetchone()["c"]
            assert before == after == 2
            assert second.get("skipped") is True, second


def test_numbering_continues_after_migration() -> None:
    """迁移用过 001，之后取号必须从 002 继续（不能重号）。"""
    with TempDB():
        with db.get_conn() as conn:
            seed_legacy(conn)
            _run(conn)
            assert report_repo.next_seq(conn, DAY) == 2


def test_fresh_database_needs_no_data_migration() -> None:
    """全新库（没有旧数据）跑迁移：不报错，直接置版本。"""
    with TempDB():
        with db.get_conn() as conn:
            result = _run(conn)
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
            assert result.get("accounts", 0) == 0


def test_migration_creates_target_tables_by_itself() -> None:
    """只给旧结构、不给新表，迁移也要能跑通。

    （上板首次部署就是这种情况：服务停着，init_db 没跑过，新表不存在。
    第一次上板时确实栽在这里 —— 报 no such table: account。）
    """
    fd, path = tempfile.mkstemp(prefix="elevator-legacy-only-", suffix=".db")
    os.close(fd)
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.executescript(db.SCHEMA_LEGACY)   # 只有旧表
        seed_legacy(conn)
        conn.commit()

        result = legacy_to_v1.run(conn)
        assert result["accounts"] == 2, result
        accounts = conn.execute("SELECT COUNT(*) FROM account").fetchone()[0]
        reports = conn.execute("SELECT COUNT(*) FROM report").fetchone()[0]
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert accounts == 2, f"账号 {accounts}"
        # 1 条 history → 已生成报告，1 条 form_draft → 草稿报告，共 2 份
        assert reports == 2, f"报告 {reports}"
        assert version == 1, f"user_version {version}"
        conn.close()
    finally:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(path + suffix)
            except OSError:
                pass


def _main() -> int:
    tests = [
        ("账号搬迁且角色统一", test_accounts_migrated_with_single_role),
        ("历史记录→已生成+补编号", test_history_becomes_generated_report_with_number),
        ("旧草稿→草稿报告", test_form_draft_becomes_draft_report),
        ("旧表改名+版本置1", test_renames_legacy_tables_and_sets_version),
        ("可重复执行", test_migration_is_idempotent),
        ("迁移后编号继续", test_numbering_continues_after_migration),
        ("全新库直接置版本", test_fresh_database_needs_no_data_migration),
        ("迁移自建目标结构", test_migration_creates_target_tables_by_itself),
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
import sqlite3
import tempfile
import os

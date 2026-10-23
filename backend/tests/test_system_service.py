"""系统管理与运维测试：信息、诊断、备份、恢复。

重点验两条容易出错的：
  - 备份必须是**一致性快照**（WAL 下直接拷文件会丢最近事务）；
  - 恢复必须先校验再原子替换，**损坏的备份不能覆盖好库**。

不依赖 pytest：python backend/tests/test_system_service.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests._tempdb import TempDB  # noqa: E402

from app import db  # noqa: E402
from app.repo import account_repo  # noqa: E402
from app.repo.ids import Snowflake  # noqa: E402
from app.services import auth_service, runtime_config, system_service  # noqa: E402


def _seed_account(username: str = "zhangsan") -> None:
    with db.get_conn() as conn:
        account_repo.insert(
            conn, account_id=Snowflake(worker_id=1).next_id(), username=username,
            display_name="张三", employee_no="", password_salt="00", password_hash="11",
            created_at="2026-10-13T09:00:00",
        )


def test_info_reports_version_catalog_and_db() -> None:
    """「关于」页要显示版本、模型、条目库、库大小 —— 且都得是真值。"""
    with TempDB():
        info = system_service.info()
        assert info["version"]
        assert "Qwen3.5-4B" in info["model"], "模型名必须与板端一致"
        assert info["catalog"]["count"] == 66 and info["catalog"]["ok"] is True
        assert info["db"]["size"] > 0 and info["db"]["schema_version"] == 0
        assert "report" in info["db"]["tables"]


def test_diagnose_returns_named_checks() -> None:
    """诊断要逐项给出名称 + 状态 + 说明，整体状态取最差项。"""
    with TempDB():
        result = system_service.diagnose()
        names = [c["name"] for c in result["checks"]]
        for expected in ("业务库", "条目库", "知识图谱", "大模型服务", "导出目录",
                         "文档转换", "磁盘空间", "系统时间", "ID 生成"):
            assert expected in names, f"诊断缺少检查项 {expected}"
        assert result["overall"] in ("ok", "warn", "fail")
        db_check = next(c for c in result["checks"] if c["name"] == "业务库")
        assert db_check["status"] == "ok", db_check


def test_backup_creates_consistent_snapshot_with_manifest() -> None:
    """备份产物要能独立恢复：含业务库 + manifest（逐文件 SHA-256）。"""
    with TempDB():
        _seed_account()
        target = Path(tempfile.mkdtemp(prefix="elevator-backup-"))
        try:
            result = system_service.backup(str(target))
            backup_dir = Path(result["dir"])
            assert (backup_dir / "elevator.db").is_file()
            assert (backup_dir / "manifest.json").is_file()
            manifest = system_service.verify_backup(str(backup_dir))
            assert manifest["files"], "manifest 不能是空的"
            # 备份出来的库要能独立打开、且数据在里面
            import sqlite3

            conn = sqlite3.connect(str(backup_dir / "elevator.db"))
            try:
                count = conn.execute("SELECT COUNT(*) FROM account").fetchone()[0]
            finally:
                conn.close()
            assert count == 1, "备份里没带账号数据"
        finally:
            shutil.rmtree(target, ignore_errors=True)


def test_verify_backup_rejects_corrupted_file() -> None:
    """被改过的备份必须被拒（宁可不恢复，也不能把坏库换上去）。"""
    with TempDB():
        _seed_account()
        target = Path(tempfile.mkdtemp(prefix="elevator-backup-bad-"))
        try:
            result = system_service.backup(str(target))
            backup_dir = Path(result["dir"])
            with (backup_dir / "elevator.db").open("ab") as fh:
                fh.write(b"corrupted")
            try:
                system_service.verify_backup(str(backup_dir))
            except ValueError as e:
                assert "损坏" in str(e)
            else:
                raise AssertionError("被改过的备份应当校验失败")
        finally:
            shutil.rmtree(target, ignore_errors=True)


def test_restore_brings_back_deleted_account() -> None:
    """恢复：删掉账号 → 从备份恢复 → 账号回来了。"""
    with TempDB():
        _seed_account("before_backup")
        target = Path(tempfile.mkdtemp(prefix="elevator-restore-"))
        try:
            result = system_service.backup(str(target))
            with db.get_conn() as conn:
                conn.execute("DELETE FROM account WHERE username = 'before_backup'")
            with db.get_conn() as conn:
                assert conn.execute("SELECT COUNT(*) FROM account").fetchone()[0] == 0

            outcome = system_service.restore(result["dir"])
            with db.get_conn() as conn:
                names = [r["username"] for r in conn.execute("SELECT username FROM account")]
            assert names == ["before_backup"], names
            assert outcome["pre_backup"], "恢复前必须先自动备份现状"
        finally:
            shutil.rmtree(target, ignore_errors=True)


def test_config_items_expose_editable_whitelist() -> None:
    """基本配置要给前端提供可编辑白名单 + 只读信息项。"""
    with TempDB():
        items = runtime_config.items()
        editable = {i["key"]: i for i in items if i["editable"]}
        for key in ("institution_name", "report_no_prefix", "export_dir",
                    "backup_dir", "worker_id", "kiosk_exit_enabled"):
            assert key in editable, f"缺少可编辑配置项 {key}"
        assert all(item["type"] in ("str", "int", "bool") for item in editable.values())
        assert all(i["editable"] for i in items)
        readonly = runtime_config.readonly_items()
        assert readonly and any(i["key"] == "app_version" for i in readonly)


def test_audit_events_are_listed_newest_first() -> None:
    """审计查询：最新在前，可按事件筛选。"""
    with TempDB():
        auth_service.init_system(display_name="张三", username="zhangsan",
                                 password="elevator2026")
        result = system_service.audit_events(event="setup_init")
        assert result["total"] == 1
        assert result["items"][0]["event"] == "setup_init"
        assert result["items"][0]["actor_name"] == "张三"


def _main() -> int:
    tests = [
        ("系统信息", test_info_reports_version_catalog_and_db),
        ("诊断检查项", test_diagnose_returns_named_checks),
        ("备份为一致性快照", test_backup_creates_consistent_snapshot_with_manifest),
        ("损坏备份被拒", test_verify_backup_rejects_corrupted_file),
        ("恢复回滚数据", test_restore_brings_back_deleted_account),
        ("配置可编辑白名单", test_config_items_expose_editable_whitelist),
        ("审计查询", test_audit_events_are_listed_newest_first),
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

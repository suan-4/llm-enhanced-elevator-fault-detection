"""基本配置（运行时配置）测试：白名单、类型校验、持久化、重启标记与副作用。

不依赖 pytest：python backend/tests/test_runtime_config.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests._tempdb import TempDB  # noqa: E402

from app import db  # noqa: E402
from app.config import load_runtime_overrides, settings  # noqa: E402
from app.services import export_service, runtime_config  # noqa: E402

EDITABLE_KEYS = (
    "institution_name", "report_no_prefix", "export_dir", "backup_dir",
    "backup_keep", "session_ttl_hours", "session_idle_hours", "worker_id",
    "kiosk_exit_enabled",
)
_ORIGINAL = {key: getattr(settings, key) for key in EDITABLE_KEYS}


def _restore() -> None:
    for key, value in _ORIGINAL.items():
        setattr(settings, key, value)
    export_service.EXPORT_DIR = Path(str(settings.export_dir))


def test_items_have_editable_whitelist_and_readonly_info() -> None:
    items = runtime_config.items()
    editable = {i["key"]: i for i in items if i["editable"]}
    assert set(EDITABLE_KEYS) <= set(editable), "可编辑白名单不完整"
    for key, item in editable.items():
        assert item["label"] and item["type"] in ("str", "int", "bool")
        assert item["value"] == getattr(settings, key), key
    assert all(i["editable"] for i in items), "基本配置只应包含可编辑项"
    readonly = runtime_config.readonly_items()
    assert {i["key"] for i in readonly} >= {"app_version", "model", "sqlite_path"}
    assert all(not i["editable"] for i in readonly)
    assert not ({i["key"] for i in readonly} & set(editable)), "只读信息不应混入基本配置"


def test_update_applies_persists_and_audits() -> None:
    _restore()
    try:
        with TempDB():
            with tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "runtime_config.json"
                result = runtime_config.update(
                    {"institution_name": "测试机构", "backup_keep": 7,
                     "kiosk_exit_enabled": False},
                    path=target,
                )
                assert settings.institution_name == "测试机构"
                assert settings.backup_keep == 7
                assert settings.kiosk_exit_enabled is False
                assert result["updated"] == ["institution_name", "backup_keep", "kiosk_exit_enabled"]
                assert result["restart_required"] == []

                saved = json.loads(target.read_text(encoding="utf-8"))
                assert saved["institution_name"] == "测试机构"
                assert load_runtime_overrides(target)["backup_keep"] == 7

                with db.get_conn() as conn:
                    count = conn.execute(
                        "SELECT COUNT(*) FROM audit_log WHERE event = 'config_update'"
                    ).fetchone()[0]
                assert count == 1, "配置修改必须写审计"
    finally:
        _restore()


def test_update_validation_rejects_bad_values_without_partial_write() -> None:
    _restore()
    try:
        cases = [
            ({"__unknown__": 1}, "未知配置项"),
            ({"backup_keep": 0}, "不能小于"),
            ({"backup_keep": "abc"}, "必须是整数"),
            ({"report_no_prefix": "含中文-1"}, "格式不正确"),
            ({"institution_name": "   "}, "不能为空"),
            ({"kiosk_exit_enabled": "maybe"}, "必须是布尔值"),
        ]
        for values, expected in cases:
            try:
                runtime_config.update(values)
                raise AssertionError(f"应当拒绝 {values}")
            except ValueError as e:
                assert expected in str(e), (values, str(e))
        assert settings.institution_name == _ORIGINAL["institution_name"]
        assert settings.backup_keep == _ORIGINAL["backup_keep"]
    finally:
        _restore()


def test_worker_id_change_requires_restart() -> None:
    _restore()
    try:
        with TempDB():
            with tempfile.TemporaryDirectory() as tmp:
                result = runtime_config.update({"worker_id": 5}, path=Path(tmp) / "config.json")
                assert result["restart_required"] == ["worker_id"]
                assert settings.worker_id == 5
    finally:
        _restore()


def test_export_dir_change_updates_export_service_constant() -> None:
    _restore()
    try:
        with TempDB():
            with tempfile.TemporaryDirectory() as tmp:
                new_dir = str(Path(tmp) / "exports")
                runtime_config.update({"export_dir": new_dir}, path=Path(tmp) / "config.json")
                assert settings.export_dir == new_dir
                assert export_service.EXPORT_DIR == Path(new_dir), "导出模块要立刻用新目录"
    finally:
        _restore()


def test_unchanged_values_are_noop() -> None:
    _restore()
    try:
        with TempDB():
            current = settings.institution_name
            with tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "config.json"
                result = runtime_config.update({"institution_name": current}, path=target)
                assert result["updated"] == []
                assert not target.exists(), "没有变化时不应该写文件"
    finally:
        _restore()


def _main() -> int:
    tests = [
        ("配置项白名单", test_items_have_editable_whitelist_and_readonly_info),
        ("保存/持久化/审计", test_update_applies_persists_and_audits),
        ("非法值拒绝", test_update_validation_rejects_bad_values_without_partial_write),
        ("工作节点重启标记", test_worker_id_change_requires_restart),
        ("导出目录副作用", test_export_dir_change_updates_export_service_constant),
        ("无变化不写盘", test_unchanged_values_are_noop),
    ]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  [PASS] {name}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {name}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} 通过")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(_main())

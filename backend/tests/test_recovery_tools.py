"""口令找回的两条兜底路径。

为什么必须有：界面的「忘记口令」依赖板端 /userdata/elevator/recovery.key，
那个文件没生成或丢了，如果又没有命令行重置，**系统就彻底进不去了**。
（第一次上板时就是：recovery_available=false，而 reset_password.py 根本还没写。）

不依赖 pytest：python backend/tests/test_recovery_tools.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests._tempdb import TempDB  # noqa: E402

from app import db  # noqa: E402
from app.services import auth_service  # noqa: E402
from tools import make_recovery_key, reset_password  # noqa: E402


def test_reset_password_cli_changes_password_and_kills_sessions() -> None:
    """命令行重置：新口令可用、旧口令失效、该账号会话被踢掉。"""
    with TempDB():
        account, session = auth_service.init_system(
            display_name="张三", username="zhangsan", password="elevator2026"
        )
        assert auth_service.resolve_session(session["token"]) is not None

        code = reset_password.main(["zhangsan", "--password", "elevator2027", "--yes"])
        assert code == 0
        assert auth_service.resolve_session(session["token"]) is None, "重置后旧会话要失效"
        assert auth_service.login("zhangsan", "elevator2027") is not None
        assert auth_service.login("zhangsan", "elevator2026") is None


def test_reset_password_cli_rejects_weak_and_unknown() -> None:
    """弱口令与不存在的账号都要被拒，并且给出可读原因。"""
    with TempDB():
        auth_service.init_system(display_name="张三", username="zhangsan",
                                 password="elevator2026")
        assert reset_password.main(["zhangsan", "--password", "12345678", "--yes"]) != 0
        assert reset_password.main(["nobody", "--password", "elevator2027", "--yes"]) != 0
        # 口令没被改坏
        assert auth_service.login("zhangsan", "elevator2026") is not None


def test_reset_password_writes_audit() -> None:
    """命令行重置也要留痕（否则"谁把口令改了"就查不到）。"""
    with TempDB():
        auth_service.init_system(display_name="张三", username="zhangsan",
                                 password="elevator2026")
        reset_password.main(["zhangsan", "--password", "elevator2027", "--yes"])
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT event, actor_name, target, note FROM audit_log WHERE event='password_reset'"
            ).fetchall()
        assert rows, "命令行重置必须写审计"
        assert rows[0]["target"] == "zhangsan"
        assert "命令行" in (rows[0]["actor_name"] + rows[0]["note"])


def test_make_recovery_key_writes_file_and_key_works() -> None:
    """生成恢复口令文件 → 用它就能重置口令（界面上的「忘记口令」走同一条路）。"""
    with TempDB():
        auth_service.init_system(display_name="张三", username="zhangsan",
                                 password="elevator2026")
        target = Path(os.environ["TEMP"]) / f"recovery-{os.getpid()}.key"
        try:
            assert make_recovery_key.main(["--path", str(target), "--force"]) == 0
            assert target.is_file(), "恢复口令文件没生成"
            key = target.read_text(encoding="utf-8").strip()
            assert len(key) >= 24, f"恢复口令太短：{key!r}"
            if os.name != "nt":  # Windows 上 chmod 只能改只读位，权限断言没意义
                assert (target.stat().st_mode & 0o777) == 0o600, "权限必须是 600"

            auth_service.forgot_password(key, "zhangsan", "elevator2028", recovery_key=key)
            assert auth_service.login("zhangsan", "elevator2028") is not None
        finally:
            target.unlink(missing_ok=True)


def test_make_recovery_key_refuses_to_overwrite_without_force() -> None:
    """已经有恢复口令文件时不覆盖 —— 免得把交付单上那个口令悄悄换掉。"""
    target = Path(os.environ["TEMP"]) / f"recovery-keep-{os.getpid()}.key"
    try:
        assert make_recovery_key.main(["--path", str(target)]) == 0
        first = target.read_text(encoding="utf-8").strip()
        assert make_recovery_key.main(["--path", str(target)]) != 0, "不该覆盖已有文件"
        assert target.read_text(encoding="utf-8").strip() == first
    finally:
        target.unlink(missing_ok=True)


def _main() -> int:
    tests = [
        ("命令行重置口令", test_reset_password_cli_changes_password_and_kills_sessions),
        ("弱口令与未知账号被拒", test_reset_password_cli_rejects_weak_and_unknown),
        ("命令行重置留痕", test_reset_password_writes_audit),
        ("恢复口令文件可用", test_make_recovery_key_writes_file_and_key_works),
        ("不覆盖已有恢复口令", test_make_recovery_key_refuses_to_overwrite_without_force),
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

"""账号这条线的业务规则测试（切到新表之后）。

覆盖的是"业务大脑"该管的事，而不是 SQL：
  - 单角色下的开户 / 停用 / 重置口令 / 删除约束；
  - 登录：口令校验、失败锁定、成功后记账；
  - 会话：改密即踢下线、停用即失效；
  - 初始化向导与恢复口令。

不依赖 pytest：python backend/tests/test_auth_service.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests._tempdb import TempDB  # noqa: E402

from app.repo import audit_repo, report_repo  # noqa: E402
from app.repo.ids import Snowflake  # noqa: E402
from app.services import auth_service  # noqa: E402
from app.services.login_guard import LoginGuard  # noqa: E402


def _fresh_guard() -> LoginGuard:
    return LoginGuard(max_fail=5, lock_minutes=10)


def test_setup_status_and_init() -> None:
    """空库 → 未初始化；初始化后能直接用返回的令牌登录。"""
    with TempDB():
        assert auth_service.setup_status()["initialized"] is False
        account, session = auth_service.init_system(
            display_name="张三", username="zhangsan", password="elevator2026"
        )
        assert account["username"] == "zhangsan" and account["role"] == "inspector"
        assert isinstance(account["id"], str), "接口里的 id 必须是字符串（雪花 ID 超出 JS 安全整数）"
        assert session["token"]
        assert auth_service.setup_status()["initialized"] is True
        # 再次初始化必须被拒绝
        try:
            auth_service.init_system(display_name="李四", username="lisi", password="elevator2026")
        except ValueError:
            pass
        else:
            raise AssertionError("已初始化后不应允许再次初始化")


def test_password_policy() -> None:
    """口令强度：≥8 位、含字母与数字、不得与用户名相同。"""
    with TempDB():
        cases = [
            ("zhangsan", "short1"),      # 太短
            ("zhangsan", "12345678"),    # 没有字母
            ("zhangsan", "abcdefgh"),    # 没有数字
            ("abc12345", "abc12345"),    # 与用户名相同
        ]
        for username, pwd in cases:
            try:
                auth_service.init_system(display_name="张三", username=username, password=pwd)
            except ValueError:
                continue
            raise AssertionError(f"弱口令 {username}/{pwd} 应当被拒绝")


def test_login_success_records_events() -> None:
    """登录成功：返回会话、更新最后登录时间、写审计。"""
    with TempDB():
        auth_service.init_system(display_name="张三", username="zhangsan", password="elevator2026")
        result = auth_service.login("zhangsan", "elevator2026", guard=_fresh_guard())
        assert result["token"] and result["user"]["username"] == "zhangsan"
        with auth_service.db.get_conn() as conn:
            events = [r["event"] for r in audit_repo.list_(conn, size=50)[0]]
        assert "login_ok" in events and "setup_init" in events


def test_login_lockout_after_failures() -> None:
    """连续 5 次失败后锁定，锁定期间即使口令正确也拒绝。"""
    with TempDB():
        auth_service.init_system(display_name="张三", username="zhangsan", password="elevator2026")
        guard = _fresh_guard()
        for _ in range(4):
            assert auth_service.login("zhangsan", "wrong-pass1", guard=guard) is None
        # 第 5 次失败 → 触发锁定
        assert auth_service.login("zhangsan", "wrong-pass1", guard=guard) is None
        try:
            auth_service.login("zhangsan", "elevator2026", guard=guard)
        except auth_service.LoginLocked as e:
            assert e.remaining_seconds > 0
        else:
            raise AssertionError("锁定期间不应允许登录")


def test_change_password_kills_all_sessions() -> None:
    """改密后该账号所有会话立即失效。"""
    with TempDB():
        account, session = auth_service.init_system(
            display_name="张三", username="zhangsan", password="elevator2026"
        )
        assert auth_service.resolve_session(session["token"]) is not None
        auth_service.change_password(account["id"], "elevator2027")
        assert auth_service.resolve_session(session["token"]) is None, "改密后旧令牌应失效"
        assert auth_service.login("zhangsan", "elevator2027", guard=_fresh_guard()) is not None


def test_disable_account_invalidates_session() -> None:
    """停用后已签发的会话立即失效，且不能再登录。"""
    with TempDB():
        account, session = auth_service.init_system(
            display_name="张三", username="zhangsan", password="elevator2026"
        )
        auth_service.create_account(
            display_name="李四", username="lisi", password="elevator2026"
        )
        # 还有 lisi 是启用的，所以停用 zhangsan 是允许的
        auth_service.update_account(account["id"], is_active=False)
        assert auth_service.resolve_session(session["token"]) is None
        assert auth_service.login("zhangsan", "elevator2026", guard=_fresh_guard()) is None


def test_cannot_disable_or_delete_last_active_account() -> None:
    """单角色下最要紧的一条：不能把最后一个启用账号停用/删掉，否则没人能登录。"""
    with TempDB():
        account, _ = auth_service.init_system(
            display_name="张三", username="zhangsan", password="elevator2026"
        )
        for call in (
            lambda: auth_service.update_account(account["id"], is_active=False),
            lambda: auth_service.delete_account(account["id"]),
        ):
            try:
                call()
            except ValueError:
                continue
            raise AssertionError("最后一个启用账号不应允许停用或删除")


def test_delete_account_with_reports_is_rejected() -> None:
    """有报告的账号只能停用，不能删除（保留可追溯性）。"""
    with TempDB():
        account, _ = auth_service.init_system(
            display_name="张三", username="zhangsan", password="elevator2026"
        )
        auth_service.create_account(display_name="李四", username="lisi", password="elevator2026")
        with auth_service.db.get_conn() as conn:
            report_repo.insert_draft(
                conn, report_id=Snowflake(worker_id=1).next_id(), created_by=account["id"],
                created_at="2026-10-13T09:00:00", updated_at="2026-10-13T09:00:00",
            )
        try:
            auth_service.delete_account(account["id"])
        except ValueError as e:
            assert "报告" in str(e)
        else:
            raise AssertionError("有报告的账号不应允许删除")


def test_username_must_be_unique() -> None:
    with TempDB():
        auth_service.init_system(display_name="张三", username="zhangsan", password="elevator2026")
        try:
            auth_service.create_account(
                display_name="另一个张三", username="zhangsan", password="elevator2026"
            )
        except ValueError:
            pass
        else:
            raise AssertionError("重复用户名应当被拒绝")


def test_guard_lock_expires_and_resets() -> None:
    """锁定到点自动解除；登录成功清零失败计数。"""
    ticks = {"t": 1000.0}
    guard = LoginGuard(max_fail=3, lock_minutes=1, clock=lambda: ticks["t"])
    for _ in range(3):
        guard.record_failure("zhangsan")
    assert guard.remaining("zhangsan") > 0, "3 次失败后应锁定"
    ticks["t"] += 61  # 过了一分钟
    assert guard.remaining("zhangsan") == 0, "锁定应自动过期"

    guard.record_failure("zhangsan")
    guard.reset("zhangsan")
    assert guard.remaining("zhangsan") == 0


def test_reset_password_forces_change_and_kills_sessions() -> None:
    """重置口令：可要求首登改密，并踢掉该账号所有会话。"""
    with TempDB():
        account, session = auth_service.init_system(
            display_name="张三", username="zhangsan", password="elevator2026"
        )
        auth_service.reset_password(account["id"], "elevator2028", require_change=True)
        assert auth_service.resolve_session(session["token"]) is None
        result = auth_service.login("zhangsan", "elevator2028", guard=_fresh_guard())
        assert result["must_change_password"] is True


def test_forgot_password_with_recovery_key() -> None:
    """恢复口令正确才能重置；错误一律拒绝。"""
    with TempDB():
        account, _ = auth_service.init_system(
            display_name="张三", username="zhangsan", password="elevator2026"
        )
        key = "RECOVERY-KEY-123"
        try:
            auth_service.forgot_password("WRONG", "zhangsan", "elevator2029", recovery_key=key)
        except PermissionError:
            pass
        else:
            raise AssertionError("恢复口令错误应被拒绝")
        auth_service.forgot_password(key, "zhangsan", "elevator2029", recovery_key=key)
        assert auth_service.login("zhangsan", "elevator2029", guard=_fresh_guard()) is not None


def _main() -> int:
    tests = [
        ("初始化向导", test_setup_status_and_init),
        ("口令强度", test_password_policy),
        ("登录成功记账", test_login_success_records_events),
        ("失败锁定", test_login_lockout_after_failures),
        ("改密踢下线", test_change_password_kills_all_sessions),
        ("停用即失效", test_disable_account_invalidates_session),
        ("最后一个启用账号保护", test_cannot_disable_or_delete_last_active_account),
        ("有报告不可删除", test_delete_account_with_reports_is_rejected),
        ("用户名唯一", test_username_must_be_unique),
        ("锁定自动过期与清零", test_guard_lock_expires_and_resets),
        ("重置口令", test_reset_password_forces_change_and_kills_sessions),
        ("恢复口令找回", test_forgot_password_with_recovery_key),
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

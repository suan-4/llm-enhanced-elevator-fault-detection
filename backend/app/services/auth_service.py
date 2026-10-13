"""账号与会话的业务规则（单角色：检验员）。

本模块**只调 repo，不写 SQL**（《数据库设计 v1》§6）。这里负责的是判断：
口令强度、最后一个启用账号不能停用、改密即踢下线、失败锁定、审计留痕。

口令仍用标准库 hashlib.pbkdf2_hmac 加盐哈希，全程不引入第三方库。
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta

from app import db
from app.config import settings
from app.repo import account_repo, audit_repo, report_repo, session_repo
from app.repo.base import now_iso
from app.repo.ids import next_id
from app.services.login_guard import LoginGuard

PBKDF2_ITERATIONS = 120_000
ROLES = ("inspector",)          # 单角色；字段保留是为将来扩展
PASSWORD_MIN = 8
PASSWORD_MAX = 128
_HAS_LETTER_AND_DIGIT = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).+$")

# 进程内共享的失败计数器（重启清零）
_guard = LoginGuard(max_fail=5, lock_minutes=10)


class LoginLocked(Exception):
    """连续失败被锁定。带上剩余秒数，前端好提示。"""

    def __init__(self, remaining_seconds: int) -> None:
        super().__init__(f"口令错误次数过多，请 {max(1, remaining_seconds // 60)} 分钟后再试")
        self.remaining_seconds = remaining_seconds


# ── 口令 ────────────────────────────────────────────────
def hash_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return salt.hex(), dk.hex()


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    _, candidate = hash_password(password, salt_hex)
    return hmac.compare_digest(candidate, hash_hex)


def check_password_policy(username: str, password: str) -> None:
    """不满足就抛 ValueError，消息要能直接显示给现场人员。"""
    if len(password) < PASSWORD_MIN:
        raise ValueError(f"口令至少 {PASSWORD_MIN} 位")
    if len(password) > PASSWORD_MAX:
        raise ValueError(f"口令不能超过 {PASSWORD_MAX} 位")
    if not _HAS_LETTER_AND_DIGIT.match(password):
        raise ValueError("口令需要同时包含字母和数字")
    if password.lower() == username.strip().lower():
        raise ValueError("口令不能与用户名相同")


# ── 序列化 ──────────────────────────────────────────────
def public_account(row: dict | None) -> dict | None:
    """对外结构：**id 转字符串**（雪花 ID 超出 JS 安全整数，不转就会失真）。"""
    if row is None:
        return None
    out = dict(row)
    for key in ("id", "created_by", "disabled_by"):
        if out.get(key) is not None:
            out[key] = str(out[key])
    if "is_active" in out:
        out["is_active"] = bool(out["is_active"])
    if "must_change_password" in out:
        out["must_change_password"] = bool(out["must_change_password"])
    return out


def _audit(conn, event: str, *, actor_id: int | None = None, actor_name: str = "",
           target: str = "", before=None, after=None, result: str = "ok",
           note: str = "") -> None:
    audit_repo.append(
        conn, audit_id=next_id(), at=now_iso(), actor_id=actor_id, actor_name=actor_name,
        event=event, target=target, before=before, after=after, result=result, note=note,
    )


# ── 初始化与查询 ────────────────────────────────────────
def setup_status() -> dict:
    """前端启动时问：要不要走初始化向导？能不能用恢复口令？"""
    with db.get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM account").fetchone()["c"]
    import os

    return {
        "initialized": int(total) > 0,
        "recovery_available": os.path.isfile(settings.recovery_key_path),
        "version": settings.app_version,
    }


def init_system(display_name: str, username: str, password: str) -> tuple[dict, dict]:
    """创建第一个账号（只能在账号表为空时）。返回 (账号, 会话)。"""
    username = username.strip()
    display_name = display_name.strip()
    if not display_name:
        raise ValueError("请填写姓名")
    if not username:
        raise ValueError("请填写登录用户名")
    check_password_policy(username, password)

    created_at = now_iso()
    with db.get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM account").fetchone()["c"]
        if int(total) > 0:
            raise ValueError("系统已经初始化过了")
        salt, digest = hash_password(password)
        account = account_repo.insert(
            conn, account_id=next_id(), username=username, display_name=display_name,
            password_salt=salt, password_hash=digest, created_at=created_at,
        )
        _audit(conn, "setup_init", actor_id=account["id"], actor_name=display_name,
               target=username)
        session = create_session(conn, account["id"])
    return public_account(account), session


def list_accounts(*, status: str | None = None, q: str | None = None,
                  page: int = 1, size: int = 20) -> dict:
    with db.get_conn() as conn:
        rows, total = account_repo.list_(conn, status=status, q=q, page=page, size=size)
    return {"total": total, "page": page, "size": size,
            "items": [public_account(r) for r in rows]}


def get_account(account_id: int | str) -> dict | None:
    with db.get_conn() as conn:
        return public_account(account_repo.find_by_id(conn, int(account_id)))


def count_active(exclude_id: int | str | None = None) -> int:
    with db.get_conn() as conn:
        return account_repo.count_active(conn, int(exclude_id) if exclude_id else None)


# ── 登录 / 会话 ─────────────────────────────────────────
def login(username: str, password: str, *, guard: LoginGuard | None = None,
          origin: str = "") -> dict | None:
    """口令正确返回会话，否则 None；被锁定抛 LoginLocked。"""
    guard = guard or _guard
    left = guard.remaining(username)
    if left > 0:
        raise LoginLocked(left)

    created_at = now_iso()
    with db.get_conn() as conn:
        cred = account_repo.find_credentials(conn, username)
        ok = (
            cred is not None
            and bool(cred["is_active"])
            and verify_password(password, cred["password_salt"], cred["password_hash"])
        )
        if not ok:
            _audit(conn, "login_fail", target=username, result="fail",
                   note="口令错误或账号停用")
            guard.record_failure(username)
            return None

        guard.reset(username)
        account_repo.touch_last_login(conn, cred["id"], created_at)
        _audit(conn, "login_ok", actor_id=cred["id"], actor_name=cred["display_name"],
               target=username)
        session = create_session(conn, cred["id"], created_at=created_at, origin=origin)
        account = account_repo.find_by_id(conn, cred["id"])
        must_change = bool(cred["must_change_password"])

    return {
        **session,
        "user": public_account(account),
        "must_change_password": must_change,
    }


def create_session(conn, account_id: int, *, created_at: str | None = None,
                   origin: str = "") -> dict:
    issued = created_at or now_iso()
    expires = (datetime.fromisoformat(issued)
               + timedelta(hours=settings.session_ttl_hours)).isoformat(timespec="seconds")
    token = secrets.token_urlsafe(32)
    session_repo.create(conn, token=token, account_id=account_id, created_at=issued,
                        expires_at=expires, origin=origin)
    return {"token": token, "expires_at": expires}


def resolve_session(token: str) -> dict | None:
    """令牌 → 账号。顺带做空闲超时、账号停用检查。"""
    if not token:
        return None
    current = now_iso()
    with db.get_conn() as conn:
        session = session_repo.find_valid(
            conn, token, now=current, idle_hours=settings.session_idle_hours
        )
        if session is None:
            return None
        account = account_repo.find_by_id(conn, session["account_id"])
        if account is None or not account["is_active"]:
            return None
        # 每 60 秒才写一次 last_seen_at：既能做空闲超时，又不磨损 eMMC
        last_seen = session.get("last_seen_at") or ""
        if last_seen < current[:16] + ":00":
            try:
                if (datetime.fromisoformat(current) - datetime.fromisoformat(last_seen)
                        ).total_seconds() >= 60:
                    session_repo.touch(conn, token, current)
            except ValueError:
                session_repo.touch(conn, token, current)
    return public_account(account)


def revoke_session(token: str, *, actor_id: int | None = None,
                   actor_name: str = "") -> None:
    with db.get_conn() as conn:
        if session_repo.delete(conn, token) and actor_id:
            _audit(conn, "logout", actor_id=actor_id, actor_name=actor_name)


def change_password(account_id: int | str, new_password: str, *,
                    actor: dict | None = None) -> None:
    """改自己的口令：改完该账号所有会话失效（含当前）。"""
    aid = int(account_id)
    with db.get_conn() as conn:
        account = account_repo.find_by_id(conn, aid)
        if account is None:
            raise LookupError("账号不存在")
        check_password_policy(account["username"], new_password)
        salt, digest = hash_password(new_password)
        account_repo.update(conn, aid, password_salt=salt, password_hash=digest,
                            must_change_password=0)
        session_repo.delete_by_account(conn, aid)
        _audit(conn, "password_change", actor_id=aid,
               actor_name=(actor or account)["display_name"], target=account["username"])


def verify_password_of(account_id: int | str, password: str) -> bool:
    with db.get_conn() as conn:
        account = account_repo.find_by_id(conn, int(account_id))
        if account is None:
            return False
        cred = account_repo.find_credentials(conn, account["username"])
        if cred is None:
            return False
        return verify_password(password, cred["password_salt"], cred["password_hash"])


# ── 账号管理（单角色：登录即可操作）─────────────────────
def create_account(*, display_name: str, username: str, password: str,
                   employee_no: str = "", require_change: bool = False,
                   actor: dict | None = None) -> dict:
    username = username.strip()
    if not username or not display_name.strip():
        raise ValueError("姓名与登录用户名都必须填写")
    check_password_policy(username, password)
    with db.get_conn() as conn:
        if account_repo.find_by_username(conn, username) is not None:
            raise ValueError(f"用户名 {username} 已存在")
        salt, digest = hash_password(password)
        account = account_repo.insert(
            conn, account_id=next_id(), username=username,
            display_name=display_name.strip(), employee_no=employee_no,
            password_salt=salt, password_hash=digest, created_at=now_iso(),
            created_by=int(actor["id"]) if actor else None,
            must_change_password=1 if require_change else 0,
        )
        _audit(conn, "account_create", actor_id=int(actor["id"]) if actor else None,
               actor_name=(actor or {}).get("display_name", ""), target=username,
               after={"display_name": account["display_name"],
                      "employee_no": account["employee_no"]})
    return public_account(account)


def update_account(account_id: int | str, *, display_name: str | None = None,
                   employee_no: str | None = None, is_active: bool | None = None,
                   actor: dict | None = None) -> dict:
    aid = int(account_id)
    with db.get_conn() as conn:
        account = account_repo.find_by_id(conn, aid)
        if account is None:
            raise LookupError("账号不存在")

        fields: dict = {}
        if display_name is not None:
            fields["display_name"] = display_name.strip()
        if employee_no is not None:
            fields["employee_no"] = employee_no
        if is_active is not None:
            turning_off = bool(account["is_active"]) and not is_active
            if turning_off and account_repo.count_active(conn, exclude_id=aid) == 0:
                raise ValueError("至少需要保留一个启用状态的账号，否则没人能登录")
            fields["is_active"] = 1 if is_active else 0
            if not is_active:
                fields["disabled_at"] = now_iso()
                fields["disabled_by"] = int(actor["id"]) if actor else None

        if not account_repo.update(conn, aid, **fields):
            raise LookupError("账号不存在")
        if is_active is False:
            session_repo.delete_by_account(conn, aid)
        event = ("account_disable" if is_active is False
                 else "account_enable" if is_active is True else "account_update")
        _audit(conn, event, actor_id=int(actor["id"]) if actor else None,
               actor_name=(actor or {}).get("display_name", ""),
               target=account["username"],
               before={"display_name": account["display_name"],
                       "is_active": bool(account["is_active"])},
               after={"display_name": fields.get("display_name", account["display_name"]),
                      "is_active": bool(fields.get("is_active", account["is_active"]))})
        return public_account(account_repo.find_by_id(conn, aid))


def delete_account(account_id: int | str, *, actor: dict | None = None) -> None:
    """只有"没有报告、且不是最后一个启用账号"的账号才能物理删除。"""
    aid = int(account_id)
    with db.get_conn() as conn:
        account = account_repo.find_by_id(conn, aid)
        if account is None:
            raise LookupError("账号不存在")
        reports = report_repo.count_by_creator(conn, aid)
        if reports:
            raise ValueError(f"该账号已有 {reports} 份报告，只能停用，不能删除")
        if account["is_active"] and account_repo.count_active(conn, exclude_id=aid) == 0:
            raise ValueError("至少需要保留一个启用状态的账号，否则没人能登录")
        account_repo.delete(conn, aid)
        _audit(conn, "account_delete", actor_id=int(actor["id"]) if actor else None,
               actor_name=(actor or {}).get("display_name", ""), target=account["username"])


def reset_password(account_id: int | str, new_password: str, *,
                   require_change: bool = False, actor: dict | None = None,
                   note: str = "") -> None:
    """代设新口令：踢掉该账号所有会话；可要求对方首次登录改密。"""
    aid = int(account_id)
    with db.get_conn() as conn:
        account = account_repo.find_by_id(conn, aid)
        if account is None:
            raise LookupError("账号不存在")
        check_password_policy(account["username"], new_password)
        salt, digest = hash_password(new_password)
        account_repo.update(conn, aid, password_salt=salt, password_hash=digest,
                            must_change_password=1 if require_change else 0)
        session_repo.delete_by_account(conn, aid)
        _audit(conn, "password_reset", actor_id=int(actor["id"]) if actor else None,
               actor_name=(actor or {}).get("display_name", ""), target=account["username"],
               note=note)


def forgot_password(input_key: str, username: str, new_password: str, *,
                    recovery_key: str) -> None:
    """用恢复口令重置。recovery_key 由调用方从板端文件读出后传入（便于测试）。"""
    if not recovery_key or not hmac.compare_digest(input_key or "", recovery_key):
        raise PermissionError("恢复口令不正确")
    with db.get_conn() as conn:
        account = account_repo.find_by_username(conn, username)
        if account is None:
            raise LookupError("账号不存在")
        check_password_policy(account["username"], new_password)
        salt, digest = hash_password(new_password)
        account_repo.update(conn, account["id"], password_salt=salt, password_hash=digest,
                            must_change_password=0)
        session_repo.delete_by_account(conn, account["id"])
        _audit(conn, "password_reset", target=account["username"], note="恢复口令")


def purge_expired_sessions() -> int:
    with db.get_conn() as conn:
        return session_repo.purge_expired(conn, now_iso())

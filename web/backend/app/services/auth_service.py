"""用户账号与登录会话管理。

口令使用标准库 hashlib.pbkdf2_hmac 加盐哈希，会话令牌使用 secrets 随机生成，
全程不引入 passlib / bcrypt / jwt 等第三方库，保证板端可离线安装。
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from app.config import settings
from app.db import get_conn

PBKDF2_ITERATIONS = 120_000
ROLES = ("admin", "inspector")


def _now() -> datetime:
    return datetime.now()


def _ts(dt: datetime | None = None) -> str:
    return (dt or _now()).isoformat(timespec="seconds")


# ── 口令 ────────────────────────────────────────────────
def hash_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return salt.hex(), dk.hex()


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    _, candidate = hash_password(password, salt_hex)
    return hmac.compare_digest(candidate, hash_hex)


# ── 序列化 ──────────────────────────────────────────────
def _public_user(row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
        "last_login_at": row["last_login_at"],
    }


# ── 初始化 ──────────────────────────────────────────────
def ensure_admin() -> dict | None:
    """库里一个用户都没有时，创建预置管理员。返回新建用户信息（已存在则返回 None）。"""
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        if total:
            return None
        salt, pwd_hash = hash_password(settings.admin_password)
        cur = conn.execute(
            "INSERT INTO users (username, display_name, password_salt, password_hash, role,"
            " is_active, created_at) VALUES (?,?,?,?,?,1,?)",
            (settings.admin_username, settings.admin_display_name, salt, pwd_hash, "admin", _ts()),
        )
        row = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _public_user(row)


# ── 认证 ────────────────────────────────────────────────
def authenticate(username: str, password: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username.strip(),)
        ).fetchone()
        if row is None or not row["is_active"]:
            return None
        if not verify_password(password, row["password_salt"], row["password_hash"]):
            return None
        conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (_ts(), row["id"]))
        return _public_user(row)


def purge_expired_sessions() -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (_ts(),))


def create_session(user_id: int) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    expires = _now() + timedelta(hours=settings.session_ttl_hours)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
            (token, user_id, _ts(), _ts(expires)),
        )
    return token, _ts(expires)


def resolve_session(token: str) -> dict | None:
    """令牌 -> 用户。已过期或用户被停用则返回 None（并顺手清理过期会话）。"""
    if not token:
        return None
    with get_conn() as conn:
        row = conn.execute(
            "SELECT u.*, s.expires_at AS s_expires FROM sessions s"
            " JOIN users u ON u.id = s.user_id WHERE s.token = ?",
            (token,),
        ).fetchone()
        if row is None:
            return None
        if row["s_expires"] < _ts():
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            return None
        if not row["is_active"]:
            return None
        return _public_user(row)


def revoke_session(token: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def change_password(user_id: int, new_password: str) -> None:
    salt, pwd_hash = hash_password(new_password)
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET password_salt = ?, password_hash = ? WHERE id = ?",
            (salt, pwd_hash, user_id),
        )


# ── 用户管理 ────────────────────────────────────────────
def list_users() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
        return [_public_user(r) for r in rows]


def get_user(user_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _public_user(row) if row else None


def create_user(username: str, password: str, display_name: str = "", role: str = "inspector") -> dict:
    username = username.strip()
    if not username:
        raise ValueError("用户名不能为空")
    if role not in ROLES:
        raise ValueError(f"角色必须是 {'/'.join(ROLES)} 之一")
    salt, pwd_hash = hash_password(password)
    with get_conn() as conn:
        exists = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
        if exists:
            raise ValueError(f"用户名 {username} 已存在")
        cur = conn.execute(
            "INSERT INTO users (username, display_name, password_salt, password_hash, role,"
            " is_active, created_at) VALUES (?,?,?,?,?,1,?)",
            (username, display_name or username, salt, pwd_hash, role, _ts()),
        )
        row = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _public_user(row)


def update_user(user_id: int, *, display_name=None, role=None, is_active=None, password=None) -> dict:
    sets, args = [], []
    if display_name is not None:
        sets.append("display_name = ?"); args.append(display_name)
    if role is not None:
        if role not in ROLES:
            raise ValueError(f"角色必须是 {'/'.join(ROLES)} 之一")
        sets.append("role = ?"); args.append(role)
    if is_active is not None:
        sets.append("is_active = ?"); args.append(1 if is_active else 0)
    if password:
        salt, pwd_hash = hash_password(password)
        sets += ["password_salt = ?", "password_hash = ?"]
        args += [salt, pwd_hash]
    if not sets:
        raise ValueError("没有需要更新的字段")

    args.append(user_id)
    with get_conn() as conn:
        cur = conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = ?", args)
        if cur.rowcount == 0:
            raise LookupError("用户不存在")
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if password or is_active is False:
            # 改密或停用后，强制该用户已登录的会话失效
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        return _public_user(row)


def count_active_admins(exclude_user_id: int | None = None) -> int:
    sql = "SELECT COUNT(*) AS c FROM users WHERE role = 'admin' AND is_active = 1"
    args: list = []
    if exclude_user_id is not None:
        sql += " AND id != ?"
        args.append(exclude_user_id)
    with get_conn() as conn:
        return conn.execute(sql, args).fetchone()["c"]


def delete_user(user_id: int) -> None:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        if cur.rowcount == 0:
            raise LookupError("用户不存在")

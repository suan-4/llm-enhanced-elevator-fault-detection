"""账号表数据访问（单表，无业务规则）。"""
from __future__ import annotations

from typing import Any

from app.repo.base import row_to_dict, rows_to_dicts

# 对外返回的字段（不含口令）；需要口令时才用 find_credentials
_PUBLIC = (
    "id, username, display_name, employee_no, role, is_active, "
    "must_change_password, created_at, created_by, last_login_at, disabled_at, disabled_by"
)

# update 允许改的列（白名单，防拼接注入）
_WRITABLE = (
    "display_name",
    "employee_no",
    "password_salt",
    "password_hash",
    "password_algo",
    "role",
    "is_active",
    "must_change_password",
    "last_login_at",
    "disabled_at",
    "disabled_by",
)


def insert(
    conn: Any,
    *,
    account_id: int,
    username: str,
    display_name: str,
    password_salt: str,
    password_hash: str,
    created_at: str,
    employee_no: str = "",
    role: str = "inspector",
    created_by: int | None = None,
    must_change_password: int = 0,
) -> dict:
    conn.execute(
        "INSERT INTO account (id, username, display_name, employee_no, password_salt,"
        " password_hash, role, is_active, must_change_password, created_at, created_by)"
        " VALUES (?,?,?,?,?,?,?,1,?,?,?)",
        (
            account_id, username, display_name, employee_no, password_salt,
            password_hash, role, must_change_password, created_at, created_by,
        ),
    )
    return find_by_id(conn, account_id)  # type: ignore[return-value]


def find_by_id(conn: Any, account_id: int) -> dict | None:
    row = conn.execute(f"SELECT {_PUBLIC} FROM account WHERE id = ?", (account_id,)).fetchone()
    return row_to_dict(row)


def find_by_username(conn: Any, username: str) -> dict | None:
    row = conn.execute(
        f"SELECT {_PUBLIC} FROM account WHERE username = ?", (username.strip(),)
    ).fetchone()
    return row_to_dict(row)


def find_credentials(conn: Any, username: str) -> dict | None:
    """登录校验专用：带上口令哈希与状态。"""
    row = conn.execute(
        "SELECT id, username, display_name, is_active, password_salt, password_hash,"
        " password_algo, must_change_password FROM account WHERE username = ?",
        (username.strip(),),
    ).fetchone()
    return row_to_dict(row)


def list_(conn: Any, *, status: str | None = None, q: str | None = None,
          page: int = 1, size: int = 20) -> tuple[list[dict], int]:
    where, args = [], []
    if status == "active":
        where.append("is_active = 1")
    elif status == "disabled":
        where.append("is_active = 0")
    if q:
        where.append("(username LIKE ? OR display_name LIKE ?)")
        args += [f"%{q}%", f"%{q}%"]
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    total = conn.execute(f"SELECT COUNT(*) AS c FROM account{clause}", args).fetchone()["c"]
    offset = max(0, (max(1, page) - 1) * size)
    rows = conn.execute(
        f"SELECT {_PUBLIC} FROM account{clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        [*args, size, offset],
    ).fetchall()
    return rows_to_dicts(rows), int(total)


def update(conn: Any, account_id: int, **fields: Any) -> bool:
    sets, args = [], []
    for key, value in fields.items():
        if key not in _WRITABLE:
            raise ValueError(f"不允许修改字段 {key}")
        sets.append(f"{key} = ?")
        args.append(value)
    if not sets:
        return False
    args.append(account_id)
    cur = conn.execute(f"UPDATE account SET {', '.join(sets)} WHERE id = ?", args)
    return cur.rowcount > 0


def delete(conn: Any, account_id: int) -> bool:
    return conn.execute("DELETE FROM account WHERE id = ?", (account_id,)).rowcount > 0


def count_active(conn: Any, exclude_id: int | None = None) -> int:
    sql = "SELECT COUNT(*) AS c FROM account WHERE is_active = 1"
    args: list = []
    if exclude_id is not None:
        sql += " AND id != ?"
        args.append(exclude_id)
    return int(conn.execute(sql, args).fetchone()["c"])


def touch_last_login(conn: Any, account_id: int, at: str) -> None:
    conn.execute("UPDATE account SET last_login_at = ? WHERE id = ?", (at, account_id))

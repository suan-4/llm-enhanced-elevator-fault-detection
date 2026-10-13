"""会话表数据访问。"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.repo.base import row_to_dict, rows_to_dicts


def create(conn: Any, *, token: str, account_id: int, created_at: str,
           expires_at: str, origin: str = "") -> dict:
    conn.execute(
        "INSERT INTO session (token, account_id, created_at, expires_at, last_seen_at, origin)"
        " VALUES (?,?,?,?,?,?)",
        (token, account_id, created_at, expires_at, created_at, origin),
    )
    return row_to_dict(
        conn.execute("SELECT * FROM session WHERE token = ?", (token,)).fetchone()
    )  # type: ignore[return-value]


def _plus_hours(at: str, hours: int) -> str:
    try:
        base = datetime.fromisoformat(at)
    except ValueError:
        return at
    return (base + timedelta(hours=hours)).isoformat(timespec="seconds")


def find_valid(conn: Any, token: str, *, now: str,
               idle_hours: int | None = None) -> dict | None:
    """令牌有效才返回会话行：既要没到期，也要没超空闲时长。"""
    if not token:
        return None
    row = conn.execute("SELECT * FROM session WHERE token = ?", (token,)).fetchone()
    if row is None:
        return None
    if row["expires_at"] <= now:
        return None
    if idle_hours:
        base = row["last_seen_at"] or row["created_at"]
        if _plus_hours(base, idle_hours) <= now:
            return None
    return row_to_dict(row)


def touch(conn: Any, token: str, at: str) -> None:
    conn.execute("UPDATE session SET last_seen_at = ? WHERE token = ?", (at, token))


def delete(conn: Any, token: str) -> bool:
    return conn.execute("DELETE FROM session WHERE token = ?", (token,)).rowcount > 0


def delete_by_account(conn: Any, account_id: int) -> int:
    """改密 / 停用 / 重置口令后调用：该账号所有会话立即失效。"""
    return conn.execute("DELETE FROM session WHERE account_id = ?", (account_id,)).rowcount


def purge_expired(conn: Any, now: str) -> int:
    return conn.execute("DELETE FROM session WHERE expires_at <= ?", (now,)).rowcount


def list_(conn: Any, *, page: int = 1, size: int = 50) -> tuple[list[dict], int]:
    total = conn.execute("SELECT COUNT(*) AS c FROM session").fetchone()["c"]
    offset = max(0, (max(1, page) - 1) * size)
    rows = conn.execute(
        "SELECT s.*, a.username, a.display_name FROM session s"
        " LEFT JOIN account a ON a.id = s.account_id"
        " ORDER BY s.created_at DESC LIMIT ? OFFSET ?",
        (size, offset),
    ).fetchall()
    return rows_to_dicts(rows), int(total)

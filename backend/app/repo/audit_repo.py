"""审计日志数据访问。只追加，不提供删除。"""
from __future__ import annotations

from typing import Any

from app.repo.base import dumps, loads, row_to_dict, rows_to_dicts


def append(conn: Any, *, audit_id: int, at: str, actor_id: int | None, actor_name: str,
           event: str, target: str = "", before: Any = None, after: Any = None,
           result: str = "ok", note: str = "") -> dict:
    conn.execute(
        "INSERT INTO audit_log (id, at, actor_id, actor_name, event, target,"
        " before_json, after_json, result, note) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            audit_id, at, actor_id, actor_name, event, target,
            dumps(before) if before is not None else None,
            dumps(after) if after is not None else None,
            result, note,
        ),
    )
    return row_to_dict(
        conn.execute("SELECT * FROM audit_log WHERE id = ?", (audit_id,)).fetchone()
    )  # type: ignore[return-value]


def list_(conn: Any, *, from_: str | None = None, to: str | None = None,
          event: str | None = None, actor: str | None = None, result: str | None = None,
          page: int = 1, size: int = 50) -> tuple[list[dict], int]:
    where, args = [], []
    if from_:
        where.append("at >= ?")
        args.append(from_)
    if to:
        where.append("at <= ?")
        args.append(to + "T23:59:59" if len(to) == 10 else to)
    if event:
        where.append("event = ?")
        args.append(event)
    if actor:
        where.append("(actor_name LIKE ? OR actor_id = ?)")
        args += [f"%{actor}%", actor if str(actor).isdigit() else -1]
    if result:
        where.append("result = ?")
        args.append(result)
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    total = conn.execute(f"SELECT COUNT(*) AS c FROM audit_log{clause}", args).fetchone()["c"]
    offset = max(0, (max(1, page) - 1) * size)
    rows = conn.execute(
        f"SELECT * FROM audit_log{clause} ORDER BY at DESC, id DESC LIMIT ? OFFSET ?",
        [*args, size, offset],
    ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["before"] = loads(item.pop("before_json"), None)
        item["after"] = loads(item.pop("after_json"), None)
        out.append(item)
    return out, int(total)


def count(conn: Any) -> int:
    return int(conn.execute("SELECT COUNT(*) AS c FROM audit_log").fetchone()["c"])

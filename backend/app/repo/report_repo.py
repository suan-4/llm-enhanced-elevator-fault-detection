"""报告表数据访问（含编号按日流水）。"""
from __future__ import annotations

from typing import Any

from app.repo.base import dumps, parse_json_fields, row_to_dict, rows_to_dicts

_JSON_FIELDS = ("form_json", "items_json", "counters_json", "risks_json",
                "files_json", "provenance_json")

# 从 form_json 提升出来、供检索与排序的列（见设计 §4.3）
_PROMOTED = ("client_name", "user_name", "device_category", "product_no",
             "location", "assessed_on")


def _one(conn: Any, report_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM report WHERE id = ?", (report_id,)).fetchone()
    return parse_json_fields(row_to_dict(row), _JSON_FIELDS)


def insert_draft(conn: Any, *, report_id: int, created_by: int, created_at: str,
                 updated_at: str, catalog_version: str = "",
                 template_version: str = "") -> dict:
    conn.execute(
        "INSERT INTO report (id, status, created_by, created_at, updated_at,"
        " catalog_version, template_version) VALUES (?, 'draft', ?, ?, ?, ?, ?)",
        (report_id, created_by, created_at, updated_at, catalog_version, template_version),
    )
    return _one(conn, report_id)  # type: ignore[return-value]


def find_by_id(conn: Any, report_id: int) -> dict | None:
    return _one(conn, report_id)


def lock_for_generation(conn: Any, report_id: int) -> dict | None:
    """Take a short write lock only after model work, then re-read the report."""
    return lock_for_update(conn, report_id)


def lock_for_update(conn: Any, report_id: int) -> dict | None:
    """Read/check/write must share one write transaction, including draft saves."""
    conn.execute("BEGIN IMMEDIATE")
    return _one(conn, report_id)


def invalidate_content(conn: Any, report_id: int) -> None:
    """Advance the edit version once; changed generated input becomes a draft."""
    conn.execute(
        "UPDATE report SET version = version + 1,"
        " status = CASE WHEN status = 'generated' THEN 'draft' ELSE status END WHERE id = ?",
        (report_id,),
    )


def update_content(conn: Any, report_id: int, *, form: dict, items: list,
                   counters: dict, updated_at: str, promote: dict | None = None) -> bool:
    """保存填写内容。

    promote 里的 6 个抬头字段必须与 form 同步写入 —— 它们是 form_json 的投影，
    只改 JSON 不改列会导致列表页搜不到（设计 §4.3 要点 3）。
    """
    sets = ["form_json = ?", "items_json = ?", "counters_json = ?", "updated_at = ?"]
    args: list = [dumps(form), dumps(items), dumps(counters), updated_at]
    for key, value in (promote or {}).items():
        if key not in _PROMOTED:
            raise ValueError(f"不允许提升字段 {key}")
        sets.append(f"{key} = ?")
        args.append(value)
    args.append(report_id)
    return conn.execute(f"UPDATE report SET {', '.join(sets)} WHERE id = ?", args).rowcount > 0


def update_generated(conn: Any, report_id: int, *, report_no: str, status: str,
                     generated_at: str, risks: dict, score: int | None, grade: str | None,
                     narrative: str, provenance: dict,
                     files: list | None = None) -> bool:
    sets = ["report_no = ?", "status = ?", "generated_at = ?", "risks_json = ?",
            "score = ?", "grade = ?", "narrative = ?", "provenance_json = ?",
            "updated_at = ?"]
    args: list = [report_no, status, generated_at, dumps(risks), score, grade,
                  narrative, dumps(provenance), generated_at]
    if files is not None:
        sets.append("files_json = ?")
        args.append(dumps(files))
    args.append(report_id)
    return conn.execute(f"UPDATE report SET {', '.join(sets)} WHERE id = ?", args).rowcount > 0


def list_(conn: Any, *, status: str | None = None, q: str | None = None,
          from_: str | None = None, to: str | None = None, mine: int | None = None,
          page: int = 1, size: int = 20) -> tuple[list[dict], int]:
    where, args = [], []
    if status:
        where.append("status = ?")
        args.append(status)
    if mine:
        where.append("created_by = ?")
        args.append(mine)
    if q:
        where.append("(report_no LIKE ? OR client_name LIKE ? OR user_name LIKE ?)")
        args += [f"%{q}%", f"%{q}%", f"%{q}%"]
    if from_:
        where.append("created_at >= ?")
        args.append(from_)
    if to:
        where.append("created_at <= ?")
        args.append(to + "T23:59:59" if len(to) == 10 else to)
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    total = conn.execute(f"SELECT COUNT(*) AS c FROM report{clause}", args).fetchone()["c"]
    offset = max(0, (max(1, page) - 1) * size)
    rows = conn.execute(
        f"SELECT * FROM report{clause} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
        [*args, size, offset],
    ).fetchall()
    return rows_to_dicts(rows), int(total)


def list_drafts(conn: Any, created_by: int, *, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM report WHERE status = 'draft' AND created_by = ?"
        " ORDER BY updated_at DESC LIMIT ?",
        (created_by, limit),
    ).fetchall()
    return [parse_json_fields(row_to_dict(r), ("counters_json",)) for r in rows]  # type: ignore[misc]


def next_seq(conn: Any, day: str) -> int:
    """取当天编号流水，只增不减（作废号不复用）。必须在事务里调用。"""
    conn.execute(
        "INSERT INTO report_no_seq (day, last_seq) VALUES (?, 1)"
        " ON CONFLICT(day) DO UPDATE SET last_seq = last_seq + 1",
        (day,),
    )
    return int(conn.execute("SELECT last_seq FROM report_no_seq WHERE day = ?", (day,)).fetchone()[0])


def void(conn: Any, report_id: int, *, voided_at: str, reason: str) -> bool:
    return conn.execute(
        "UPDATE report SET status = 'void', voided_at = ?, void_reason = ?, updated_at = ?"
        " WHERE id = ? AND status IN ('generated', 'filed')",
        (voided_at, reason, voided_at, report_id),
    ).rowcount > 0


def mark_exported(conn: Any, report_id: int, *, exported_at: str, files: list) -> bool:
    return conn.execute(
        "UPDATE report SET status = 'filed', exported_at = ?, files_json = ?, updated_at = ?"
        " WHERE id = ?",
        (exported_at, dumps(files), exported_at, report_id),
    ).rowcount > 0


def delete(conn: Any, report_id: int) -> bool:
    """只允许删草稿或作废件；已生成/已归档只能作废（保留编号与痕迹）。"""
    return conn.execute(
        "DELETE FROM report WHERE id = ? AND status IN ('draft', 'void')", (report_id,)
    ).rowcount > 0


def max_id(conn: Any) -> int | None:
    """重启时用来反推雪花 ID 的下界。"""
    row = conn.execute("SELECT MAX(id) AS m FROM report").fetchone()
    return int(row["m"]) if row and row["m"] is not None else None


def count_by_creator(conn: Any, account_id: int) -> int:
    """某账号有多少份报告 —— 决定他能不能被物理删除。"""
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM report WHERE created_by = ?", (account_id,)
    ).fetchone()
    return int(row["c"])

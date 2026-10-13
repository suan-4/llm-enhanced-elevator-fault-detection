"""repo 层的公共设施：连接、JSON、时间、row → dict。

各 repo 统一从这里取东西（而不是直接 import app.db），这样"数据访问"
只有一个入口，将来换存储或加埋点只改这里。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Iterable, Mapping

from app.db import get_conn, set_user_version, user_version  # noqa: F401  统一出口


def row_to_dict(row: Any) -> dict | None:
    """sqlite3.Row → 普通 dict。

    刻意不把 Row 传到上层：底层类型泄漏出去，将来换存储就要改一大片。
    """
    return dict(row) if row is not None else None


def rows_to_dicts(rows: Iterable[Any]) -> list[dict]:
    return [dict(r) for r in rows]


def loads(raw: Any, default: Any = None) -> Any:
    """解析 JSON 列：空值或坏值都退回 default，不让读取炸掉。"""
    if raw is None or raw == "":
        return default
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def dumps(value: Any) -> str:
    """序列化 JSON 列：不转义中文，方便人看库。"""
    return json.dumps(value, ensure_ascii=False)


def parse_json_fields(row: Mapping[str, Any] | None, fields: Iterable[str]) -> dict | None:
    """把 _json 列就地解析成 Python 对象（读取时统一在这里处理）。"""
    if row is None:
        return None
    out = dict(row)
    for name in fields:
        if name in out:
            default = [] if name in ("items_json", "files_json") else {}
            out[name[: -len("_json")]] = loads(out.pop(name), default)
    return out


def now_iso() -> str:
    """本地时间字符串，秒级（与库里的约定一致）。"""
    return datetime.now().isoformat(timespec="seconds")


def today_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def day_key(at: str | None = None) -> str:
    """取编号流水用的日期键 YYYYMMDD。"""
    if not at:
        return datetime.now().strftime("%Y%m%d")
    return at[:10].replace("-", "")


def paged(conn: Any, base_sql: str, where: list[str], args: list, page: int, size: int) -> tuple[list, int]:
    """列表查询的统一分页：先数总数，再取本页。"""
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    total = conn.execute(f"SELECT COUNT(*) AS c{base_sql}{clause}", args).fetchone()["c"]
    offset = max(0, (max(1, page) - 1) * size)
    rows = conn.execute(
        f"{base_sql}{clause} LIMIT ? OFFSET ?".replace("SELECT *", "SELECT *", 1),
        [*args, size, offset],
    ).fetchall()
    return list(rows), int(total)

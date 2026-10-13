"""审计留痕的统一入口。

各个 service 都从这里写日志，保证字段口径一致（谁 / 何时 / 对谁 / 前值 / 后值 / 结果）。
注意：审计写入失败不应影响主流程 —— 调用方在同一个事务里，写失败会一起回滚，
这是有意的（宁可业务重试，也不留一条"做了但没记"的记录）。
"""
from __future__ import annotations

from typing import Any

from app.repo import audit_repo
from app.repo.base import now_iso
from app.repo.ids import next_id


def record(
    conn: Any,
    event: str,
    *,
    actor: dict | None = None,
    actor_id: int | None = None,
    actor_name: str = "",
    target: str = "",
    before: Any = None,
    after: Any = None,
    result: str = "ok",
    note: str = "",
) -> None:
    """写一条审计事件。actor 传账号 dict 时自动取其 id 与姓名。"""
    return audit_repo.append(
        conn,
        audit_id=next_id(),
        at=now_iso(),
        actor_id=int(actor["id"]) if actor else actor_id,
        actor_name=(actor or {}).get("display_name", "") or actor_name,
        event=event,
        target=target,
        before=before,
        after=after,
        result=result,
        note=note,
    )

"""报告历史与填写记录（草稿）接口。

所有数据按登录用户隔离：任何查询都带 user_id 条件，
不存在通过猜 id 读到他人记录的路径。
"""
import json

from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.db import get_conn
from app.deps import get_current_user
from app.models.schemas import DraftPayload, HistoryCreate, HistoryUpdate

router = APIRouter(prefix="/api", tags=["历史记录"])


def _loads(raw, default=None):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _summary(row) -> dict:
    return {
        "id": row["id"],
        "time_label": row["time_label"],
        "reg": row["reg"],
        "location": row["location"],
        "items_count": row["items_count"],
        "states_count": row["states_count"],
        "created_at": row["created_at"],
    }


def _detail(row) -> dict:
    d = _summary(row)
    d.update({
        "report_text": row["report_text"],
        "fault_chain": _loads(row["fault_chain"]),
        "form_data": _loads(row["form_data"], {}),
        "items_data": _loads(row["items_data"], {}),
    })
    return d


def _trim(user_id: int, conn) -> None:
    """只保留最近 N 条，避免板端存储无限增长。"""
    conn.execute(
        "DELETE FROM report_history WHERE user_id = ? AND id NOT IN ("
        "  SELECT id FROM report_history WHERE user_id = ? ORDER BY id DESC LIMIT ?"
        ")",
        (user_id, user_id, settings.history_limit),
    )


# ── 报告历史 ────────────────────────────────────────────
@router.get("/history")
def list_history(user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM report_history WHERE user_id = ? ORDER BY id DESC",
            (user["id"],),
        ).fetchall()
    return {"success": True, "history": [_summary(r) for r in rows]}


@router.post("/history")
def create_history(payload: HistoryCreate, user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO report_history (user_id, created_at, time_label, reg, location,"
            " items_count, states_count, report_text, fault_chain, form_data, items_data)"
            " VALUES (?, datetime('now','localtime'), ?,?,?,?,?,?,?,?,?)",
            (
                user["id"], payload.time_label, payload.reg, payload.location,
                payload.items_count, payload.states_count, payload.report_text,
                json.dumps(payload.fault_chain, ensure_ascii=False) if payload.fault_chain else None,
                json.dumps(payload.form_data, ensure_ascii=False) if payload.form_data else None,
                json.dumps(payload.items_data, ensure_ascii=False) if payload.items_data else None,
            ),
        )
        new_id = cur.lastrowid
        _trim(user["id"], conn)
        row = conn.execute("SELECT * FROM report_history WHERE id = ?", (new_id,)).fetchone()
    return {"success": True, "id": new_id, "entry": _summary(row)}


@router.get("/history/{history_id}")
def get_history(history_id: int, user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM report_history WHERE id = ? AND user_id = ?",
            (history_id, user["id"]),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    return {"success": True, "entry": _detail(row)}


@router.patch("/history/{history_id}")
def update_history(history_id: int, payload: HistoryUpdate, user: dict = Depends(get_current_user)):
    """AI 报告是流式生成完才完整的，先用图谱摘要入库，再回填正文。"""
    if payload.report_text is None:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE report_history SET report_text = ? WHERE id = ? AND user_id = ?",
            (payload.report_text, history_id, user["id"]),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="记录不存在")
    return {"success": True}


@router.delete("/history/{history_id}")
def delete_history(history_id: int, user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM report_history WHERE id = ? AND user_id = ?",
            (history_id, user["id"]),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="记录不存在")
    return {"success": True}


# ── 填写记录（草稿）──────────────────────────────────────
@router.get("/draft")
def get_draft(user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM form_draft WHERE user_id = ?", (user["id"],)
        ).fetchone()
    if row is None:
        return {"success": True, "draft": None}
    return {
        "success": True,
        "draft": {
            "form_data": _loads(row["form_data"], {}),
            "items_data": _loads(row["items_data"], {}),
            "updated_at": row["updated_at"],
        },
    }


@router.put("/draft")
def save_draft(payload: DraftPayload, user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO form_draft (user_id, form_data, items_data, updated_at)"
            " VALUES (?,?,?, datetime('now','localtime'))"
            " ON CONFLICT(user_id) DO UPDATE SET"
            " form_data = excluded.form_data,"
            " items_data = excluded.items_data,"
            " updated_at = excluded.updated_at",
            (
                user["id"],
                json.dumps(payload.form_data, ensure_ascii=False),
                json.dumps(payload.items_data, ensure_ascii=False),
            ),
        )
    return {"success": True}


@router.delete("/draft")
def clear_draft(user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        conn.execute("DELETE FROM form_draft WHERE user_id = ?", (user["id"],))
    return {"success": True}

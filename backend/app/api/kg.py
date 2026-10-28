"""知识图谱 v2 检索/选择接口（MVP：只读检索 + 选择日志，不改报告生成）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.deps import get_current_user
from app.services import kg_prompt, kg_validation
from app.services.kg_v2 import kg_v2
from app.services.llm_service import llm_service

router = APIRouter(prefix="/api/kg", tags=["知识图谱检索"])


class CandidateRequest(BaseModel):
    item_no: str = Field(..., description="JTE 项目编号，如 5.1")
    item_name: str = ""
    reasons: list[str] = Field(default_factory=list, description="勾选的不符合情形原文")
    other_text: str = Field(default="", description="「其他」自行填写原文")
    top_k: int = Field(3, ge=1, le=10)


class Top3Item(BaseModel):
    rank: int = 0
    path_id: str = ""
    path_summary: str = ""
    component: str = ""
    system: str = ""
    score: float = 0


class SelectRequest(BaseModel):
    report_id: str | None = None
    item_no: str
    item_name: str = ""
    query: str = ""
    path_id: str | None = None
    decision: str = Field("selected", pattern="^(selected|no_candidate)$")
    rank: int | None = None
    top3: list[Top3Item] = Field(default_factory=list)
    selection_source: str = Field("human", pattern="^(human|model|human_override)$")
    model_path_id: str | None = None
    model_reason: str = ""


class EvidenceRequest(BaseModel):
    path_ids: list[str] = Field(default_factory=list)


@router.get("/status")
def status(user: dict = Depends(get_current_user)) -> dict:
    return {"success": True, **kg_v2.status()}


@router.post("/candidates")
def candidates(req: CandidateRequest, user: dict = Depends(get_current_user)) -> dict:
    try:
        result = kg_v2.retrieve(
            item_no=req.item_no,
            item_name=req.item_name,
            reasons=req.reasons,
            other_text=req.other_text,
            top_k=req.top_k,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, **result}


@router.post("/recommend")
async def recommend(req: CandidateRequest, user: dict = Depends(get_current_user)) -> dict:
    """AI 推荐：只从本次 TopK 候选中选一条；最终仍由操作员确认。"""
    try:
        result = kg_v2.retrieve(
            item_no=req.item_no, item_name=req.item_name,
            reasons=req.reasons, other_text=req.other_text, top_k=req.top_k,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    candidates = result.get("candidates") or []
    if not candidates:
        return {"success": True, "recommendation": {"path_id": None, "rank": None,
                                                    "reason": "无候选路径", "none": True}}
    try:
        prompt = kg_prompt.build_t2_rerank_prompt(
            item_no=req.item_no, item_name=req.item_name,
            query=result.get("query") or "", candidates=candidates,
        )
        raw = await llm_service.generate(prompt)
        parsed = kg_validation.parse_json_output(raw)
        allowed = {str(c.get("path_id")): c for c in candidates}
        selected = parsed.get("selected") if isinstance(parsed, dict) else None
        if not isinstance(selected, list) or not selected:
            return {"success": True, "recommendation": {"path_id": None, "rank": None,
                                                        "reason": "模型未选出合适候选", "none": True}}
        chosen = selected[0] if isinstance(selected[0], dict) else {}
        path_id = str(chosen.get("path_id") or "")
        if path_id not in allowed:
            return {"success": True, "recommendation": {"path_id": None, "rank": None,
                                                        "reason": "模型推荐不在候选范围", "none": True}}
        return {"success": True, "recommendation": {
            "path_id": path_id,
            "rank": allowed[path_id].get("rank"),
            "reason": str(chosen.get("reason") or "")[:80],
            "none": False,
        }}
    except Exception:
        return {"success": False, "recommendation": None,
                "error": "AI 推荐暂不可用，请人工选择"}


@router.post("/select")
def select(req: SelectRequest, user: dict = Depends(get_current_user)) -> dict:
    if req.decision == "selected" and not req.path_id:
        raise HTTPException(status_code=400, detail="selected 必须提供 path_id")
    try:
        log_id = kg_v2.log_selection(
            report_id=req.report_id,
            item_no=req.item_no,
            item_name=req.item_name,
            query=req.query,
            path_id=req.path_id if req.decision == "selected" else None,
            decision=req.decision,
            rank=req.rank,
            top3=[item.model_dump() for item in req.top3],
            operator=str(user.get("name") or user.get("username") or ""),
            selection_source=req.selection_source,
            model_path_id=req.model_path_id,
            model_reason=req.model_reason,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"success": True, "id": log_id}


@router.post("/evidence")
def evidence(req: EvidenceRequest, user: dict = Depends(get_current_user)) -> dict:
    try:
        return {"success": True, **kg_v2.evidence(req.path_ids)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

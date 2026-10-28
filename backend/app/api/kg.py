"""知识图谱 v2 检索/选择接口（MVP：只读检索 + 选择日志，不改报告生成）。"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.deps import get_current_user
from app.services import kg_prompt, kg_validation
from app.services.kg_v2 import kg_v2
from app.services.llm_service import llm_service

router = APIRouter(prefix="/api/kg", tags=["知识图谱检索"])


class CandidateRequest(BaseModel):
    item_no: str = Field(..., description="JTE 项目编号，如 5.1")
    fast_only: bool = Field(False, description="只跑规则快路径；不命中时不调用模型")
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
    selection_source: str = Field("human", pattern="^(human|model|rule|human_override)$")
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


_REC_CACHE: dict[str, tuple[float, dict]] = {}
_REC_TTL = 3600
_GENERIC_MATCHES = {"工作", "系统", "装置", "检查", "安全", "电梯", "运行", "正常",
                    "状态", "保护", "开关", "部件", "要求", "功能", "设备"}


def _lcs(a: str, b: str) -> str:
    """最长公共子串；用于部件名与现场描述的确定性匹配。"""
    a = "".join(str(a or "").split()).lower()
    b = "".join(str(b or "").split()).lower()
    if not a or not b:
        return ""
    dp = [0] * (len(b) + 1)
    best = 0
    end = 0
    for i in range(1, len(a) + 1):
        prev = 0
        for j in range(1, len(b) + 1):
            old = dp[j]
            if a[i - 1] == b[j - 1]:
                dp[j] = prev + 1
                if dp[j] > best:
                    best = dp[j]
                    end = j
            else:
                dp[j] = 0
            prev = old
    return b[end - best:end]


def _rule_recommend(candidates: list[dict], query: str) -> dict | None:
    """部件名直接命中时秒选；不命中或候选打平则返回 None 交给模型。"""
    if not candidates:
        return {"path_id": None, "rank": None, "reason": "无候选路径",
                "none": True, "source": "rule"}
    if len(candidates) == 1:
        c = candidates[0]
        return {"path_id": c.get("path_id"), "rank": c.get("rank"),
                "reason": "仅一个候选路径", "none": False, "source": "rule"}
    scored = []
    for c in candidates:
        matched = _lcs(c.get("component") or "", query)
        matched = matched.strip()
        if len(matched) >= 2 and matched not in _GENERIC_MATCHES:
            scored.append((len(matched), matched, c))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    best_len, best_match, best = scored[0]
    if best_len < 2:
        return None
    if sum(1 for item in scored if item[0] == best_len) != 1:
        return None
    return {"path_id": best.get("path_id"), "rank": best.get("rank"),
            "reason": f"部件名称直接匹配：{best_match}", "none": False, "source": "rule"}


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
    query = result.get("query") or ""
    key = "|".join([req.item_no, req.item_name, " ".join(req.reasons),
                    req.other_text, ",".join(str(c.get("path_id")) for c in candidates)])
    now = time.time()
    cached = _REC_CACHE.get(key)
    if cached and now - cached[0] < _REC_TTL:
        return {"success": True, "recommendation": {**cached[1], "cached": True}}
    rule = _rule_recommend(candidates, query)
    if rule is not None:
        _REC_CACHE[key] = (now, rule)
        return {"success": True, "recommendation": rule}
    if req.fast_only:
        return {"success": True, "recommendation": None, "needs_model": True}
    try:
        prompt = kg_prompt.build_t2_recommend_prompt(
            item_no=req.item_no, item_name=req.item_name,
            query=query, candidates=candidates,
        )
        raw = await llm_service.generate(prompt, max_tokens=96)
        parsed = kg_validation.parse_json_output(raw)
        allowed = {str(c.get("path_id")): c for c in candidates}
        path_id = str((parsed or {}).get("path_id") or "")
        if (parsed or {}).get("none") or not path_id:
            rec = {"path_id": None, "rank": None, "reason": "模型未选出合适候选",
                   "none": True, "source": "model"}
        elif path_id not in allowed:
            rec = {"path_id": None, "rank": None, "reason": "模型推荐不在候选范围",
                   "none": True, "source": "model"}
        else:
            rec = {"path_id": path_id, "rank": allowed[path_id].get("rank"),
                   "reason": str((parsed or {}).get("reason") or "")[:40],
                   "none": False, "source": "model"}
        # 控制缓存条目数量，避免长跑进程无限增长
        if len(_REC_CACHE) > 500:
            _REC_CACHE.clear()
        _REC_CACHE[key] = (now, rec)
        return {"success": True, "recommendation": rec}
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

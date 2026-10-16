import json
import traceback
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.deps import get_current_user
from app.models.schemas import ReportRequest, ReportResponse
from app.services.report_service import generate_report, generate_prompt_only
from app.services.kg_service import kg_service
from app.services.llm_service import llm_service
from app.services import expert_risk

router = APIRouter(prefix="/api/report", tags=["报告生成"])

# JTE-09-R02-3.00 模板条目目录，由 tools/gen_jte_items.py 从模板 docx 抽取生成。
# 条目是模板结构，不来自知识图谱，因此单独存 JSON 而不查 Neo4j。
JTE_ITEMS_PATH = Path(__file__).resolve().parent.parent / "data" / "jte_items.json"


@router.get("/jte-items")
async def list_jte_items(user: dict = Depends(get_current_user)):
    """返回模板的评价条目目录（66 条，顺序与模板评价结果表一致）。"""
    if not JTE_ITEMS_PATH.is_file():
        raise HTTPException(
            status_code=503,
            detail="条目目录未生成，请在仓库根目录执行 tools/gen_jte_items.py",
        )
    try:
        payload = json.loads(JTE_ITEMS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=500, detail=f"条目目录读取失败：{e}")
    try:
        items = expert_risk.enrich_items(payload.get("items", []))
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=503, detail=f"专家风险清单不可用：{e}")
    return {"success": True, "count": len(items), "items": items,
            "risk_catalog_version": expert_risk.knowledge()["version"]}


@router.get("/inspection-items")
async def list_inspection_items(user: dict = Depends(get_current_user)):
    """返回所有检测项目，按系统分组，供前端动态渲染。"""
    try:
        items = kg_service.get_inspection_items()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {"success": True, "systems": items}


@router.get("/assessment-basis")
async def get_assessment_basis(user: dict = Depends(get_current_user)):
    """返回评估依据，从 Neo4j 标准条款节点获取。"""
    try:
        basis = kg_service.get_assessment_basis()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {"success": True, "basis": basis}


@router.post("/generate", response_model=ReportResponse)
async def generate_fault_report(request: ReportRequest,
                                user: dict = Depends(get_current_user)) -> ReportResponse:
    try:
        result = await generate_report(request)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")
    return result


@router.post("/generate-stream")
async def generate_stream(request: ReportRequest, user: dict = Depends(get_current_user)):
    """流式生成报告。"""
    try:
        raw_chain = kg_service.query_fault_chain(request.inspection_item_ids, request.abnormal_states)
        if not raw_chain:
            raise HTTPException(status_code=400, detail="未查询到关联的故障链路信息")
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    prompt = generate_prompt_only(raw_chain, request.elevator_info)

    async def stream():
        yield "data: {\"t\":\"\"}\n\n"
        try:
            async for chunk in llm_service.generate_stream(prompt):
                yield f"data: {json.dumps({'t': chunk})}\n\n"
        except Exception:
            yield "data: {\"t\":\"[模型调用失败]\"}\n\n"
        yield "data: {\"t\":\"[DONE]\"}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

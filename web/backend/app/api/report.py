import json
import traceback

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.deps import get_current_user
from app.models.schemas import ReportRequest, ReportResponse
from app.services.report_service import generate_report, generate_prompt_only
from app.services.kg_service import kg_service
from app.services.llm_service import llm_service

router = APIRouter(prefix="/api/report", tags=["报告生成"])


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

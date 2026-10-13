"""报告作业接口。

一条报告记录贯穿 草稿 → 已生成 → 已归档 → 已作废（设计 §4.3），
所以没有单独的"草稿接口"——草稿就是 status=draft 的报告。

约定：
  - 路径里的 id 一律是字符串形式的雪花 ID；
  - 破坏性操作要求 confirm=true；
  - 业务规则失败返回 400 并给出可直接显示的中文原因。
"""
from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_current_user
from app.models.schemas import (
    ReportCreateRequest,
    ReportGenerateRequest,
    ReportSaveRequest,
    ReportVoidRequest,
)
from app.services import report_workflow as wf

router = APIRouter(prefix="/api/reports", tags=["报告作业"])


def _report_id(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="报告不存在")


def _translate(err: Exception) -> HTTPException:
    if isinstance(err, LookupError):
        return HTTPException(status_code=404, detail=str(err))
    if isinstance(err, wf.VersionConflict):
        return HTTPException(status_code=409, detail=str(err))
    return HTTPException(status_code=400, detail=str(err))


@router.get("")
def list_reports(status: str | None = None, q: str | None = None,
                 date_from: str | None = None, date_to: str | None = None,
                 mine: bool = False, page: int = 1, size: int = 20,
                 user: dict = Depends(get_current_user)) -> dict:
    result = wf.list_reports(
        status=status, q=q, from_=date_from, to=date_to,
        mine=user["id"] if mine else None, page=page, size=size,
    )
    return {"success": True, **result}


@router.post("")
def create_report(req: ReportCreateRequest, user: dict = Depends(get_current_user)) -> dict:
    try:
        report = wf.create_draft(actor=user, form=req.form)
    except (LookupError, ValueError) as e:
        raise _translate(e)
    return {"success": True, "report": report}


@router.get("/{report_id}")
def get_report(report_id: str, user: dict = Depends(get_current_user)) -> dict:
    report = wf.get_report(_report_id(report_id))
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    return {"success": True, "report": report}


@router.get("/{report_id}/draft")
def get_draft(report_id: str, user: dict = Depends(get_current_user)) -> dict:
    try:
        return {"success": True, **wf.get_draft(_report_id(report_id))}
    except (LookupError, ValueError) as e:
        raise _translate(e)


@router.put("/{report_id}")
def save_report(report_id: str, req: ReportSaveRequest,
                user: dict = Depends(get_current_user)) -> dict:
    try:
        result = wf.save_content(
            _report_id(report_id),
            form=req.form,
            items=[item.model_dump() for item in req.items],
            version=req.version,
            actor=user,
        )
    except (LookupError, ValueError, wf.VersionConflict) as e:
        raise _translate(e)
    return {"success": True, **result}


@router.post("/{report_id}/generate")
async def generate_report(report_id: str, req: ReportGenerateRequest,
                          user: dict = Depends(get_current_user)) -> dict:
    try:
        report = await wf.generate(_report_id(report_id), use_llm=req.use_llm, actor=user)
    except (LookupError, ValueError, wf.VersionConflict) as e:
        raise _translate(e)
    return {"success": True, "report": report}


@router.post("/{report_id}/void")
def void_report(report_id: str, req: ReportVoidRequest,
                user: dict = Depends(get_current_user)) -> dict:
    if not req.confirm:
        raise HTTPException(status_code=400, detail="作废需要二次确认")
    try:
        report = wf.void_report(_report_id(report_id), reason=req.reason, actor=user)
    except (LookupError, ValueError) as e:
        raise _translate(e)
    return {"success": True, "report": report}


@router.post("/{report_id}/clone")
def clone_report(report_id: str, user: dict = Depends(get_current_user)) -> dict:
    try:
        report = wf.clone_report(_report_id(report_id), actor=user)
    except (LookupError, ValueError) as e:
        raise _translate(e)
    return {"success": True, "report": report}


@router.delete("/{report_id}")
def delete_report(report_id: str, confirm: bool = False,
                  user: dict = Depends(get_current_user)) -> dict:
    if not confirm:
        raise HTTPException(status_code=400, detail="删除需要二次确认")
    try:
        wf.delete_report(_report_id(report_id), actor=user)
    except (LookupError, ValueError) as e:
        raise _translate(e)
    return {"success": True}

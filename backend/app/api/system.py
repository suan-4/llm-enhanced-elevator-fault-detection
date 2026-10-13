"""系统管理接口：信息、配置（只读）、审计日志、诊断、备份、恢复。

单角色下这些接口**只要求登录**（PRD §3）；破坏性操作额外要求 confirm=true。
"""
from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_current_user
from app.services import system_service

router = APIRouter(prefix="/api/system", tags=["系统管理"])


@router.get("/info")
def info(user: dict = Depends(get_current_user)) -> dict:
    return {"success": True, **system_service.info()}


@router.get("/config")
def config(user: dict = Depends(get_current_user)) -> dict:
    return {"success": True, "items": system_service.config_items()}


@router.get("/audit")
def audit(date_from: str | None = None, date_to: str | None = None,
          event: str | None = None, actor: str | None = None,
          page: int = 1, size: int = 50,
          user: dict = Depends(get_current_user)) -> dict:
    result = system_service.audit_events(from_=date_from, to=date_to, event=event,
                                        actor=actor, page=page, size=size)
    return {"success": True, **result}


@router.get("/diagnose")
def diagnose(user: dict = Depends(get_current_user)) -> dict:
    return {"success": True, **system_service.diagnose()}


@router.post("/backup")
def backup(target_dir: str | None = None, user: dict = Depends(get_current_user)) -> dict:
    try:
        result = system_service.backup(target_dir, actor=user)
    except OSError as e:
        raise HTTPException(status_code=503,
                            detail=f"备份目录不可用（{e.strerror or e}）：{target_dir or ''}")
    return {"success": True, **result}


@router.get("/backups")
def list_backups(user: dict = Depends(get_current_user)) -> dict:
    items = system_service.list_backups()
    return {"success": True, "total": len(items), "items": items}


@router.post("/restore")
def restore(source_dir: str, confirm: bool = False,
            user: dict = Depends(get_current_user)) -> dict:
    if not confirm:
        raise HTTPException(status_code=400, detail="恢复备份需要二次确认")
    try:
        result = system_service.restore(source_dir, actor=user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OSError as e:
        raise HTTPException(status_code=503, detail=f"恢复失败：{e.strerror or e}")
    return {"success": True, **result}

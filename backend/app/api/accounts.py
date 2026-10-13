"""账号管理接口（单角色：登录即可操作）。

取代旧的 /api/auth/users（那套要求管理员角色，且返回的 id 是自增数字）。
"""
from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_current_user
from app.models.schemas import (
    CreateAccountRequest,
    ResetPasswordRequest,
    UpdateAccountRequest,
)
from app.services import auth_service

router = APIRouter(prefix="/api/accounts", tags=["账号管理"])


@router.get("")
def list_accounts(status: str | None = None, q: str | None = None,
                  page: int = 1, size: int = 20,
                  user: dict = Depends(get_current_user)) -> dict:
    return {"success": True, **auth_service.list_accounts(status=status, q=q,
                                                          page=page, size=size)}


@router.post("")
def create_account(req: CreateAccountRequest, user: dict = Depends(get_current_user)) -> dict:
    try:
        account = auth_service.create_account(
            display_name=req.display_name, username=req.username, password=req.password,
            employee_no=req.employee_no, require_change=req.require_change, actor=user,
        )
    except ValueError as e:
        status = 409 if "已存在" in str(e) else 422
        raise HTTPException(status_code=status, detail=str(e))
    return {"success": True, "account": account}


@router.patch("/{account_id}")
def update_account(account_id: str, req: UpdateAccountRequest,
                   user: dict = Depends(get_current_user)) -> dict:
    if req.is_active is False and not req.confirm:
        raise HTTPException(status_code=400, detail="停用账号需要二次确认")
    try:
        account = auth_service.update_account(
            account_id, display_name=req.display_name, employee_no=req.employee_no,
            is_active=req.is_active, actor=user,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True, "account": account}


@router.delete("/{account_id}")
def delete_account(account_id: str, confirm: bool = False,
                   user: dict = Depends(get_current_user)) -> dict:
    if not confirm:
        raise HTTPException(status_code=400, detail="删除账号需要二次确认")
    try:
        auth_service.delete_account(account_id, actor=user)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True}


@router.post("/{account_id}/reset-password")
def reset_password(account_id: str, req: ResetPasswordRequest,
                   user: dict = Depends(get_current_user)) -> dict:
    if not req.confirm:
        raise HTTPException(status_code=400, detail="重置口令需要二次确认")
    try:
        auth_service.reset_password(account_id, req.new_password,
                                    require_change=req.require_change, actor=user)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"success": True, "message": "口令已重置，该账号已下线"}

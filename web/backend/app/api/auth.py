"""认证与用户管理接口。"""
from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_bearer_token, get_current_user, require_admin
from app.models.schemas import (
    ChangePasswordRequest,
    CreateUserRequest,
    LoginRequest,
    UpdateUserRequest,
)
from app.services import auth_service

router = APIRouter(prefix="/api/auth", tags=["认证"])


@router.post("/login")
def login(req: LoginRequest):
    """校验口令并签发登录令牌。"""
    user = auth_service.authenticate(req.username, req.password)
    if user is None:
        raise HTTPException(status_code=401, detail="用户名或口令不正确，或账号已被停用")
    auth_service.purge_expired_sessions()
    token, expires_at = auth_service.create_session(user["id"])
    return {"success": True, "token": token, "expires_at": expires_at, "user": user}


@router.post("/logout")
def logout(token: str = Depends(get_bearer_token)):
    auth_service.revoke_session(token)
    return {"success": True}


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    return {"success": True, "user": user}


@router.post("/change-password")
def change_password(req: ChangePasswordRequest, token: str = Depends(get_bearer_token),
                    user: dict = Depends(get_current_user)):
    # 用旧口令再验一次，避免令牌被盗后直接改密
    if auth_service.authenticate(user["username"], req.old_password) is None:
        raise HTTPException(status_code=400, detail="原口令不正确")
    auth_service.change_password(user["id"], req.new_password)
    auth_service.revoke_session(token)
    return {"success": True, "message": "口令已修改，请重新登录"}


@router.get("/users")
def list_users(_: dict = Depends(require_admin)):
    return {"success": True, "users": auth_service.list_users()}


@router.post("/users")
def create_user(req: CreateUserRequest, _: dict = Depends(require_admin)):
    try:
        user = auth_service.create_user(
            req.username, req.password, req.display_name, req.role
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True, "user": user}


@router.patch("/users/{user_id}")
def update_user(user_id: int, req: UpdateUserRequest, admin: dict = Depends(require_admin)):
    # 保护措施：不能让系统失去最后一个可用的管理员
    if user_id == admin["id"] and (req.is_active is False or (req.role and req.role != "admin")):
        raise HTTPException(status_code=400, detail="不能停用或降级当前登录的管理员账号")
    if req.is_active is False:
        target = auth_service.get_user(user_id)
        if target and target["role"] == "admin" and auth_service.count_active_admins(exclude_user_id=user_id) == 0:
            raise HTTPException(status_code=400, detail="至少需要保留一个启用状态的管理员")
    try:
        user = auth_service.update_user(
            user_id,
            display_name=req.display_name,
            role=req.role,
            is_active=req.is_active,
            password=req.password,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True, "user": user}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, admin: dict = Depends(require_admin)):
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="不能删除当前登录的账号")
    target = auth_service.get_user(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if target["role"] == "admin" and auth_service.count_active_admins(exclude_user_id=user_id) == 0:
        raise HTTPException(status_code=400, detail="至少需要保留一个启用状态的管理员")
    auth_service.delete_user(user_id)
    return {"success": True}

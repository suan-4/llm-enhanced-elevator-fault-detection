"""认证接口：登录、注销、当前账号、改密、忘记口令。

账号管理（开户/停用/重置口令）在 api/accounts.py。

要点：
  - 登录失败统一文案「用户名或口令不正确」，不区分账号不存在 / 口令错误 / 已停用，
    避免被用来枚举账号；
  - 连续失败会被锁定（内存计数），返回 429；
  - 返回体里的 id 一律是**字符串**（雪花 ID 超出 JS 安全整数）。
"""
import os

from fastapi import APIRouter, Depends, HTTPException, Request

from app.config import settings
from app.deps import get_bearer_token, get_current_user
from app.models.schemas import ChangePasswordRequest, ForgotPasswordRequest, LoginRequest
from app.services import auth_service

router = APIRouter(prefix="/api/auth", tags=["认证"])


def _client_host(request: Request) -> str:
    return request.client.host if request.client else ""


def _read_recovery_key() -> str:
    """恢复口令放在板端文件里（权限 600）；文件不存在则视为未配置。"""
    path = settings.recovery_key_path
    if not os.path.isfile(path):
        raise HTTPException(status_code=503, detail="本机未配置恢复口令，请联系维护人员")
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read().strip()


@router.post("/login")
def login(req: LoginRequest, request: Request) -> dict:
    try:
        result = auth_service.login(req.username, req.password,
                                    origin=_client_host(request))
    except auth_service.LoginLocked as e:
        raise HTTPException(status_code=429, detail=str(e))
    if result is None:
        raise HTTPException(status_code=401, detail="用户名或口令不正确")
    return {"success": True, **result}


@router.post("/logout")
def logout(token: str = Depends(get_bearer_token),
           user: dict = Depends(get_current_user)) -> dict:
    auth_service.revoke_session(token, actor_id=int(user["id"]),
                               actor_name=user["display_name"])
    return {"success": True}


@router.get("/me")
def me(user: dict = Depends(get_current_user)) -> dict:
    return {"success": True, "user": user}


@router.post("/change-password")
def change_password(req: ChangePasswordRequest, token: str = Depends(get_bearer_token),
                    user: dict = Depends(get_current_user)) -> dict:
    # 用旧口令再验一次，避免令牌被盗后直接改密
    if not auth_service.verify_password_of(user["id"], req.old_password):
        raise HTTPException(status_code=400, detail="原口令不正确")
    try:
        auth_service.change_password(user["id"], req.new_password, actor=user)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"success": True, "message": "口令已修改，请重新登录"}


@router.post("/forgot-password")
def forgot_password(req: ForgotPasswordRequest) -> dict:
    """公开接口：用板端恢复口令重置某账号的口令（PRD Q14）。"""
    recovery_key = _read_recovery_key()
    try:
        auth_service.forgot_password(req.recovery_key, req.username, req.new_password,
                                     recovery_key=recovery_key)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"success": True, "message": "口令已重置，请用新口令登录"}

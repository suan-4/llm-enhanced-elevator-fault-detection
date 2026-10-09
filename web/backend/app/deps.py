"""FastAPI 公共依赖：解析登录态。"""
from fastapi import Depends, Header, HTTPException

from app.services import auth_service


def get_bearer_token(authorization: str | None = Header(default=None)) -> str:
    """从 Authorization 头取出令牌，兼容带/不带 Bearer 前缀两种写法。"""
    if not authorization:
        return ""
    parts = authorization.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return authorization.strip()


def get_current_user(token: str = Depends(get_bearer_token)) -> dict:
    user = auth_service.resolve_session(token)
    if user is None:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user

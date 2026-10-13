"""FastAPI 公共依赖：解析登录态。

单角色之后不再有"仅管理员"这一档（PRD §3）：登录即可调用全部接口。
"""
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

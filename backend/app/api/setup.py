"""初始化向导接口。

账号表为空时前端必须走这里创建第一个账号 —— 取代过去"预置 admin/admin123"的做法
（设备上不再存在默认口令）。未初始化前，其余业务接口都会被前端拦在向导页。
"""
from fastapi import APIRouter, HTTPException

from app.models.schemas import SetupInitRequest
from app.services import auth_service

router = APIRouter(prefix="/api/setup", tags=["初始化"])


@router.get("/status")
def setup_status() -> dict:
    """前端启动第一问：要不要走向导、能不能用恢复口令。**公开接口**。"""
    return {"success": True, **auth_service.setup_status()}


@router.post("/init")
def setup_init(req: SetupInitRequest) -> dict:
    """创建第一个账号并直接登录。已初始化则 409。"""
    try:
        account, session = auth_service.init_system(
            display_name=req.display_name, username=req.username, password=req.password
        )
    except ValueError as e:
        status = 409 if "初始化过" in str(e) else 422
        raise HTTPException(status_code=status, detail=str(e))
    return {"success": True, "user": account, **session}

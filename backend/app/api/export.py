"""报告导出接口：生成 Word(.docx) / PDF 并保存到板端。

保存目录是 GUI 用户家目录下的「导出」，退出到桌面即可取走；
接口同时返回文件名与完整路径，前端会展示给用户。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
import shlex
import subprocess
from pathlib import Path

from app.deps import get_current_user
from app.services import export_service

router = APIRouter(prefix="/api/report", tags=["报告导出"])

# 桌面用户，与 app/api/ime.py 的 KIOSK_USER 一致。
# 服务以 root 运行，桌面会话属于该用户，所以打开文件必须 su 过去。
DESKTOP_USER = "user"
DESKTOP_UID = 1002


class ExportRequest(BaseModel):
    fmt: str = Field(..., description="导出格式：pdf 或 docx")
    title: str = Field(default="电梯安全评估报告", max_length=120)
    subtitle: str = Field(default="", max_length=200)
    meta: list[list[str]] = Field(default_factory=list, description="[[标签, 值], ...]")
    body_html: str = Field(default="", description="报告正文 HTML（前端已渲染，避免后端重复实现 markdown）")
    footer: str = Field(default="", max_length=200)
    filename: str = Field(default="", max_length=80, description="不带扩展名的文件名，留空则用标题")


class OpenRequest(BaseModel):
    target: str = Field(..., max_length=500, description="要打开的路径，必须位于导出目录内")


@router.post("/open")
def open_export(req: OpenRequest, user: dict = Depends(get_current_user)):
    """在板端用系统默认程序打开导出产物（文件或所在目录）。

    安全边界：只允许打开导出目录内的路径，避免被用作任意文件读取/执行入口。
    """
    export_dir = Path(export_service.EXPORT_DIR).resolve()
    try:
        target = Path(req.target).resolve()
    except (OSError, ValueError):
        raise HTTPException(status_code=400, detail="路径无效")

    if target != export_dir and export_dir not in target.parents:
        raise HTTPException(status_code=400, detail="只允许打开导出目录内的文件")
    if not target.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    cmd = (
        "DISPLAY=:0 "
        "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus "
        "XDG_RUNTIME_DIR=/run/user/{uid} "
        "xdg-open {path}"
    ).format(uid=DESKTOP_UID, path=shlex.quote(str(target)))

    try:
        # 不等待：某些查看器会一直占用进程
        subprocess.Popen(
            ["su", DESKTOP_USER, "-c", cmd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"无法打开：{e}")

    return {"success": True, "target": str(target)}


@router.post("/export")
def export_report(req: ExportRequest, user: dict = Depends(get_current_user)):
    """把当前报告导出为 PDF 或 Word。

    注意：这里用同步 def —— LibreOffice 转换是阻塞的（数秒），
    FastAPI 会把同步路由丢到线程池执行，不会卡住事件循环。
    """
    try:
        html = export_service.build_html(
            title=req.title,
            meta_rows=req.meta,
            body_html=req.body_html,
            subtitle=req.subtitle,
            footer=req.footer,
        )
        info = export_service.export(
            html_str=html,
            fmt=req.fmt,
            stem=req.filename or req.title,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="%s: %s" % (type(e).__name__, e))

    return {
        "success": True,
        "fmt": info["fmt"],
        "filename": info["filename"],
        "path": info["path"],
        "dir": info["dir"],
        "size": info["size"],
    }

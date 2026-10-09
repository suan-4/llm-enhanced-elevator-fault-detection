"""报告导出接口：生成 Word(.docx) / PDF 并保存到板端。

保存目录是 GUI 用户家目录下的「导出」，退出到桌面即可取走；
接口同时返回文件名与完整路径，前端会展示给用户。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.deps import get_current_user
from app.services import export_service

router = APIRouter(prefix="/api/report", tags=["报告导出"])


class ExportRequest(BaseModel):
    fmt: str = Field(..., description="导出格式：pdf 或 docx")
    title: str = Field(default="电梯安全评估报告", max_length=120)
    subtitle: str = Field(default="", max_length=200)
    meta: list[list[str]] = Field(default_factory=list, description="[[标签, 值], ...]")
    body_html: str = Field(default="", description="报告正文 HTML（前端已渲染，避免后端重复实现 markdown）")
    footer: str = Field(default="", max_length=200)
    filename: str = Field(default="", max_length=80, description="不带扩展名的文件名，留空则用标题")


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

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response

from app.api.auth import router as auth_router
from app.api.export import router as export_router
from app.api.history import router as history_router
from app.api.ime import router as ime_router
from app.api.kiosk import router as kiosk_router
from app.api.report import router as report_router
from app.db import init_db
from app.services import auth_service
from app.services.kg_service import kg_service
from app.services.llm_service import llm_service

ROOT_DIR = Path(__file__).parent.parent.parent
WEB_DIR = ROOT_DIR / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 业务数据库（SQLite）：建表 + 首次启动预置管理员
    init_db()
    created = auth_service.ensure_admin()
    if created:
        print(
            f"[init] 已创建预置管理员 '{created['username']}'，请登录后立即修改口令。",
            flush=True,
        )
    auth_service.purge_expired_sessions()
    yield
    kg_service.close()
    await llm_service.close()


app = FastAPI(
    title="电梯故障报告系统",
    description="基于 Neo4j 知识图谱 + RKLLM 大模型的电梯故障智能分析与报告生成系统",
    version="1.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(history_router)
app.include_router(kiosk_router)
app.include_router(report_router)
app.include_router(export_router)
app.include_router(ime_router)


@app.get("/marked.min.js", response_class=Response)
async def serve_marked():
    p = WEB_DIR / "marked.min.js"
    if p.exists():
        return Response(content=p.read_bytes(), media_type="application/javascript")
    return Response(status_code=404)


@app.get("/fslogo.png", response_class=Response)
async def serve_logo():
    p = WEB_DIR / "fslogo.png"
    if p.exists():
        return Response(content=p.read_bytes(), media_type="image/png")
    return Response(status_code=404)


@app.get("/NotoSansSymbols2.ttf", response_class=Response)
async def serve_font():
    # 优先 web/，回退项目根目录（历史上字体曾放在仓库根目录）
    for p in (WEB_DIR / "NotoSansSymbols2.ttf", ROOT_DIR / "NotoSansSymbols2.ttf"):
        if p.exists():
            return Response(content=p.read_bytes(), media_type="font/ttf")
    return Response(status_code=404)


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    index_path = WEB_DIR / "index.html"
    if index_path.exists():
        return index_path.read_text(encoding="utf-8")
    return "<h1>Frontend not found</h1>"


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "elevator-report-api"}


@app.get("/api/health/ready")
def health_ready():
    """就绪探针：后端在跑 **且** 依赖的 Neo4j 可用，才算就绪。

    背景：开机时 Neo4j 由 systemd 拉起后，还需 20~30 秒才真正开放 Bolt 端口。
    /api/health 在 Neo4j 未就绪时也会返回 200，因此前端与 kiosk 启动器
    必须轮询本接口，否则会在开机瞬间撞上「图谱查询失败」。
    """
    try:
        kg_service.driver.verify_connectivity()
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"ready": False, "neo4j": "down", "detail": type(e).__name__},
        )
    return {"ready": True, "neo4j": "up", "service": "elevator-report-api"}

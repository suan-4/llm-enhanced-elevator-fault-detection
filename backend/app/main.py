from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api.accounts import router as accounts_router
from app.api.auth import router as auth_router
from app.api.export import router as export_router
from app.api.ime import router as ime_router
from app.api.kiosk import router as kiosk_router
from app.api.report import router as report_router
from app.api.setup import router as setup_router
from app.config import settings
from app.db import get_conn, init_db, max_business_id
from app.repo import ids as id_gen
from app.services import auth_service
from app.services.kg_service import kg_service
from app.services.llm_service import llm_service

ROOT_DIR = Path(__file__).parent.parent.parent
WEB_DIR = ROOT_DIR / "web"
# 前端构建产物目录（Vite 输出）。未构建时回退到 WEB_DIR 下的旧版平铺文件。
DIST_DIR = WEB_DIR / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 业务数据库（SQLite）：建表（幂等）
    init_db()
    # 雪花 ID 生成器就位：用各业务表 MAX(id) 当下界。
    # 这台板子每次开机 RTC 都会回到 2021 年，没有这道保护就会发重号。
    id_gen.configure(settings.worker_id, max_business_id())
    removed = auth_service.purge_expired_sessions()
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM account").fetchone()["c"]
    if int(total) == 0:
        print("[init] 尚未创建账号，请打开界面完成初始化向导。", flush=True)
    elif removed:
        print(f"[init] 已清理 {removed} 个过期会话。", flush=True)
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
app.include_router(accounts_router)
app.include_router(setup_router)
app.include_router(kiosk_router)
app.include_router(report_router)
app.include_router(export_router)
app.include_router(ime_router)


@app.get("/marked.min.js", response_class=Response)
async def serve_marked():
    for p in (DIST_DIR / "marked.min.js", WEB_DIR / "marked.min.js"):
        if p.exists():
            return Response(content=p.read_bytes(), media_type="application/javascript")
    return Response(status_code=404)


@app.get("/fslogo.png", response_class=Response)
async def serve_logo():
    for p in (DIST_DIR / "fslogo.png", WEB_DIR / "fslogo.png"):
        if p.exists():
            return Response(content=p.read_bytes(), media_type="image/png")
    return Response(status_code=404)


@app.get("/fosulogo.png", response_class=Response)
async def serve_logo_fosu():
    # 启动页联合署名里的"佛山大学"logo，与 fslogo.png 一样按白名单单独放行
    for p in (DIST_DIR / "fosulogo.png", WEB_DIR / "fosulogo.png"):
        if p.exists():
            return Response(content=p.read_bytes(), media_type="image/png")
    return Response(status_code=404)


@app.get("/NotoSansSymbols2.ttf", response_class=Response)
async def serve_font():
    # 依次尝试：构建产物 → web/ → 项目根目录（历史上字体曾放在仓库根目录）
    for p in (
        DIST_DIR / "NotoSansSymbols2.ttf",
        WEB_DIR / "NotoSansSymbols2.ttf",
        WEB_DIR / "public" / "NotoSansSymbols2.ttf",
        ROOT_DIR / "NotoSansSymbols2.ttf",
    ):
        if p.exists():
            return Response(content=p.read_bytes(), media_type="font/ttf")
    return Response(status_code=404)


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    # 优先伺服前端构建产物；未构建时回退到旧版单文件前端
    for index_path in (DIST_DIR / "index.html", WEB_DIR / "index.html"):
        if index_path.exists():
            # 必须禁缓存：部署新版本后，一体机若沿用缓存的 index.html
            # 会继续加载旧的 assets，表现为「改了没生效」。
            # assets 带内容哈希，可以长缓存；入口 HTML 不能。
            return HTMLResponse(
                content=index_path.read_text(encoding="utf-8"),
                headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
            )
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


# ── 前端构建产物挂载（必须放在所有 /api 路由之后）──
# Vite 把 JS/CSS 输出到 dist/assets。挂载点只匹配 /assets/*，不会影响 API；
# 放在最后注册是为了让任何新增的 /assets 前缀路由都能优先匹配。
#
# 目录先建出来再挂载：产物尚未构建时若跳过挂载，之后构建完也得重启才生效，
# 更要紧的是——漏挂载会让所有 JS/CSS 变成 404，页面直接变成一片纯背景色
# 且没有任何提示（实测已复现），板端上就是"开机白屏"。
(DIST_DIR / "assets").mkdir(parents=True, exist_ok=True)
app.mount("/assets", StaticFiles(directory=str(DIST_DIR / "assets")), name="assets")

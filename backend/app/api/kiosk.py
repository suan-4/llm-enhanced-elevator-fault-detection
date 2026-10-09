"""自助终端（kiosk）控制接口。

板端以 Chromium 全屏运行本系统（见仓库 kiosk/ 目录）。正常情况下用户
看不到也退不出桌面；需要维护或交接时，由界面上的「退出系统」按钮关闭
kiosk 窗口，桌面随即显现。

登录页与主界面都有该按钮，因此**本模块的两个接口都不要求登录** ——
否则「进不去系统时想退回桌面」这条最需要出口的路径就断了。

安全边界改用「仅允许本机调用」：kiosk 浏览器就运行在板子上，请求来自
127.0.0.1；局域网内其他机器即使知道接口也无法关闭界面。

为什么退出要连启动器一起杀
--------------------------
启动器（elevator-kiosk.sh）默认**永远重开** Chromium。因为全屏时从屏幕
上边缘下滑会呼出 GNOME 顶栏，顶栏带当前窗口的关闭按钮(×)，点它就能关掉
界面 —— 把「关掉窗口」当作退出信号是堵不完这类旁路的。

所以只有本接口能真正终止：先杀启动器，再杀 Chromium；两者都没了才
不会重开，桌面才会显现。
"""
import subprocess

from fastapi import APIRouter, HTTPException, Request

from app.config import settings

router = APIRouter(prefix="/api/kiosk", tags=["自助终端"])

# kiosk 可能以两种形态运行，两种都要能识别与终止：
#   1) Chromium 方案：启动器 elevator-kiosk.sh + 专用 profile elevator-kiosk-profile
#   2) GTK 原生方案：elevator_app.py（见仓库 native/）
# 都用 kiosk 相关命名精确匹配，不会误伤用户自己打开的浏览器或其它 python 程序。
LAUNCHER_PATTERN = r"elevator-kiosk\.sh"
PROFILE_PATTERN = "elevator-kiosk-profile"
NATIVE_APP_PATTERN = r"elevator_app\.py"
ALL_PATTERNS = (LAUNCHER_PATTERN, PROFILE_PATTERN, NATIVE_APP_PATTERN)

LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"}


def _is_local(request: Request) -> bool:
    client = request.client
    return bool(client) and client.host in LOCAL_HOSTS


def _kiosk_running() -> bool:
    """Chromium 方案或 GTK 原生方案，任一在运行即视为 kiosk 模式。"""
    for pattern in (PROFILE_PATTERN, NATIVE_APP_PATTERN):
        result = subprocess.run(["pgrep", "-f", pattern],
                                capture_output=True, text=True)
        if result.returncode == 0:
            return True
    return False


@router.get("/status")
def kiosk_status(request: Request):
    """当前是否运行在 kiosk 模式下。前端据此决定是否显示「退出系统」按钮。

    非本机访问一律返回 kiosk_running=False，避免远程用户看到/触发退出按钮。
    """
    if not _is_local(request):
        return {"success": True, "kiosk_running": False,
                "exit_enabled": False, "local": False}
    return {
        "success": True,
        "kiosk_running": _kiosk_running(),
        "exit_enabled": settings.kiosk_exit_enabled,
        "local": True,
    }


@router.post("/exit")
def exit_kiosk(request: Request):
    """关闭 kiosk 界面并返回系统桌面。"""
    if not _is_local(request):
        raise HTTPException(status_code=403, detail="仅允许在本机操作")
    if not settings.kiosk_exit_enabled:
        raise HTTPException(status_code=403, detail="退出功能已在本机禁用")

    # 顺序很重要：先杀 Chromium 的启动器，否则它会立刻把窗口拉回来。
    # GTK 原生方案没有启动器，直接杀进程即可。
    killed = False
    try:
        for pattern in ALL_PATTERNS:
            r = subprocess.run(["pkill", "-f", pattern],
                               capture_output=True, text=True, timeout=10)
            killed = killed or r.returncode == 0
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="系统缺少 pkill 命令")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="关闭 kiosk 超时")

    if not killed:
        # 没有 kiosk 进程：说明当前不在 kiosk 模式（例如开发时用普通浏览器打开）
        return {"success": True, "kiosk_running": False,
                "message": "当前不在自助终端模式，无需退出"}

    return {"success": True, "kiosk_running": True,
            "message": "已退出，正在返回桌面"}

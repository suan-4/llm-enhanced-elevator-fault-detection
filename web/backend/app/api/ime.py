"""输入法（fcitx5）状态与切换。

背景：板端 kiosk 上**本来就有完整的中文输入法** ——
fcitx5 + libpinyin（/usr/share/fcitx5/inputmethod/pinyin.conf，
profile 里 DefaultIM=pinyin），GTK 的 im-fcitx5.so 也在，
应用环境里 GTK_IM_MODULE=fcitx、XMODIFIERS=@im=fcitx 都齐全。
实测：输入框获得焦点后 fcitx5 立即建立输入上下文（状态 1 = 英文），
输入 nihao 能正常弹出「1.你好 2.你 …」候选窗并上屏。

**唯一缺的是"切到中文"这个动作**：fcitx5 默认处于英文态，
而 GNOME 软键盘上按不出 Ctrl+Space（触发键），
所以这里提供接口，让界面上的「中/英」按钮去调 fcitx5-remote。

注意：API 服务是 root 跑的，而 fcitx5 是用户会话里的进程，
必须 su 到 GUI 用户并带上会话总线地址才能操作它。
"""
import subprocess

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/ime", tags=["输入法"])

# ★ 不要求登录 ★
# 登录页也需要这个按钮（用户名/口令是 ASCII，但用户可能先在别处用了中文），
# 而且切换输入法是纯粹的本机动作，和 /api/kiosk/* 一样按"仅限本机"来管：
# 局域网里的其他机器即使知道接口也会被 403 挡掉。
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"}


def _require_local(request: Request) -> None:
    host = (request.client.host if request.client else "") or ""
    if host not in LOCAL_HOSTS:
        raise HTTPException(status_code=403, detail="仅允许在本机操作")

KIOSK_USER = "user"
KIOSK_UID = 1002
FCITX_REMOTE = "/usr/bin/fcitx5-remote"
TIMEOUT = 8

# fcitx5-remote 的返回值：0=关闭(无输入上下文) 1=英文 2=中文
STATE_LABEL = {0: "英", 1: "英", 2: "中"}


class ImeState(BaseModel):
    success: bool = True
    state: int = 0
    label: str = "英"
    available: bool = True


def _run_remote(*args) -> int:
    """以 GUI 用户身份执行 fcitx5-remote，返回其状态码。"""
    cmd = ("DISPLAY=:0 "
           "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/%d/bus "
           "XMODIFIERS=@im=fcitx HOME=/home/%s %s %s"
           % (KIOSK_UID, KIOSK_USER, FCITX_REMOTE, " ".join(args)))
    try:
        p = subprocess.run(["su", KIOSK_USER, "-c", cmd],
                           capture_output=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return -1
    out = (p.stdout or b"").decode("utf-8", "replace").strip()
    try:
        return int(out.splitlines()[-1])
    except (ValueError, IndexError):
        return -1


def _state() -> ImeState:
    st = _run_remote()
    if st < 0:
        return ImeState(state=0, label="英", available=False)
    return ImeState(state=st, label=STATE_LABEL.get(st, "英"))


@router.get("/status", response_model=ImeState)
def ime_status(request: Request):
    _require_local(request)
    return _state()


@router.post("/toggle", response_model=ImeState)
def ime_toggle(request: Request):
    _require_local(request)
    """中英切换。

    前端必须用 onmousedown="event.preventDefault()" 保住输入框焦点 ——
    否则点按钮的一瞬间输入框失焦，fcitx5 就没有输入上下文了，
    toggle 会落空（实测）。
    """
    _run_remote("-t")
    return _state()

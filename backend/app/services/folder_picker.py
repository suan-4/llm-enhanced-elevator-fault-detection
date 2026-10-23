"""服务端所在机器的目录选择框（Linux / Windows 适配）。

为什么在服务端弹框：导出目录、备份目录是后端进程要写入的绝对路径；
浏览器的 <input webkitdirectory> 只能得到相对路径，板端 WebKit 也没有
File System Access API。因此由后端调用本机 GUI 目录选择器，前端只收结果。

平台策略（按顺序尝试）：
  Windows: python(tkinter) 目录对话框；
  Linux:   zenity → kdialog → python(tkinter)（需要 DISPLAY）。
为避免 Tk 与 Web 服务事件循环互相干扰，对话框统一放进**子进程**并设超时：
用户取消/不操作都不会把 FastAPI 线程卡死。
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

TITLE = "选择目录"
TIMEOUT_SECONDS = 180


def _desktop_context() -> tuple[dict, dict]:
    """Reuse the known kiosk user's display credentials, never an arbitrary process."""
    environment = os.environ.copy()
    identity = {}
    if os.name != 'posix' or not Path('/proc').is_dir():
        return environment, identity
    try:
        import pwd
        desktop = pwd.getpwnam('user')
        for directory in Path('/proc').iterdir():
            if not directory.name.isdecimal() or directory.stat().st_uid != desktop.pw_uid:
                continue
            try:
                arguments = (directory / 'cmdline').read_bytes().split(b'\0')
                if not any(arg.endswith(b'/elevator_app.py')
                           or (arg.startswith(b'--user-data-dir=') and b'elevator-kiosk-profile' in arg)
                           for arg in arguments):
                    continue
                fields = dict(part.split(b'=', 1) for part in (directory / 'environ').read_bytes().split(b'\0')
                              if b'=' in part)
                for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY',
                            'DBUS_SESSION_BUS_ADDRESS', 'XDG_RUNTIME_DIR'):
                    if key.encode() in fields:
                        environment[key] = os.fsdecode(fields[key.encode()])
                environment['HOME'] = desktop.pw_dir
                if os.geteuid() == 0:
                    identity = {'user': desktop.pw_uid, 'group': desktop.pw_gid, 'extra_groups': []}
                return environment, identity
            except (OSError, ValueError):
                continue
    except (OSError, KeyError):
        pass
    return environment, identity


def _tk_available() -> bool:
    try:
        import tkinter  # noqa: F401
    except Exception:  # 板端常见：python 未装 tkinter
        return False
    return True


def _windows_plan(*, has_tk: bool | None = None) -> dict:
    has = _tk_available() if has_tk is None else has_tk
    if has:
        return {"available": True, "method": "tkinter", "platform": "windows"}
    return {"available": False, "method": "none", "platform": "windows"}


def _linux_plan(*, which=None, has_tk: bool | None = None,
                display: str | None = None) -> dict:
    which = which or shutil.which
    environment, _ = _desktop_context() if display is None else ({'DISPLAY': display}, {})
    disp = environment.get('DISPLAY') or environment.get('WAYLAND_DISPLAY')
    if not disp:
        return {"available": False, "method": "none", "platform": "linux"}
    for exe, method in (("zenity", "zenity"), ("kdialog", "kdialog")):
        if which(exe):
            return {"available": True, "method": method, "platform": "linux"}
    has = _tk_available() if has_tk is None else has_tk
    if has and environment.get('DISPLAY'):
        return {"available": True, "method": "tkinter", "platform": "linux"}
    return {"available": False, "method": "none", "platform": "linux"}


def plan(system: str | None = None, **kwargs) -> dict:
    """返回当前平台的目录选择器可用性（纯函数，便于跨平台测试）。"""
    name = (system or platform.system()).lower()
    if name.startswith("win"):
        return _windows_plan(**kwargs)
    if name.startswith("linux"):
        return _linux_plan(**kwargs)
    has = _tk_available() if kwargs.get("has_tk") is None else kwargs["has_tk"]
    return {"available": bool(has), "method": "tkinter" if has else "none", "platform": name}


def available() -> dict:
    return plan()


def _tk_script(initial: str) -> str:
    return (
        "import tkinter as tk\n"
        "from tkinter import filedialog\n"
        "root = tk.Tk()\n"
        "root.withdraw()\n"
        "root.attributes('-topmost', True)\n"
        "path = filedialog.askdirectory("
        f"initialdir={json.dumps(initial)}, title={json.dumps(TITLE)})\n"
        "root.destroy()\n"
        "print(path or '')\n"
    )


def _run(args: list[str]) -> str | None:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        environment, identity = _desktop_context()
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
            creationflags=creationflags, env=environment, **identity,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"目录选择窗口超过 {TIMEOUT_SECONDS} 秒未操作，请重试") from e
    except OSError as e:
        raise RuntimeError(f"无法启动目录选择程序：{e}") from e
    if proc.returncode != 0:
        detail = (proc.stderr or '').strip()
        if proc.returncode == 1 and not detail:
            return None  # GUI cancellation; startup/authentication errors must remain visible.
        raise RuntimeError('无法打开系统目录选择窗口：' + (detail[:300] or f'程序退出码 {proc.returncode}'))
    lines = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _start_dir(initial: str | None) -> str:
    raw = (initial or "").strip()
    if raw:
        return str(Path(raw).expanduser())
    return str(Path.home())


def pick(initial: str | None = None) -> str | None:
    """弹出系统目录选择框；返回绝对路径，用户取消返回 None。"""
    info = available()
    if not info["available"]:
        raise RuntimeError(
            "当前环境无法打开系统目录选择窗口："
            "Linux 需要 zenity/kdialog，或带图形界面（DISPLAY）的 tkinter"
        )
    start = _start_dir(initial)
    method = info["method"]
    if method == "zenity":
        args = [
            "zenity", "--file-selection", "--directory",
            "--title=" + TITLE, "--filename=" + start.rstrip("/") + "/",
        ]
        return _run(args) or None
    if method == "kdialog":
        return _run(["kdialog", "--getexistingdirectory", start]) or None
    # Windows / 带 DISPLAY 的 Linux：统一用子进程 tkinter，避免阻塞事件循环
    result = _run([sys.executable, "-c", _tk_script(start)])
    return result or None

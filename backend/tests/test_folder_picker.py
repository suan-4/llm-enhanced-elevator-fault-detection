"""目录选择器测试：Linux/Windows 平台策略与不可用时的可读错误。

不真正弹窗（CI/无人值守环境无图形界面），只验证选择策略与错误提示。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import folder_picker as fp  # noqa: E402


def test_available_reports_platform_and_method() -> None:
    info = fp.available()
    assert set(info) == {"available", "method", "platform"}
    assert isinstance(info["available"], bool)
    assert info["method"] in ("tkinter", "zenity", "kdialog", "none")


def test_windows_requires_tkinter() -> None:
    assert fp._windows_plan(has_tk=True)["method"] == "tkinter"
    off = fp._windows_plan(has_tk=False)
    assert off["available"] is False and off["method"] == "none"


def test_linux_prefers_zenity_then_kdialog() -> None:
    zenity = fp._linux_plan(
        which=lambda name: "/usr/bin/zenity" if name == "zenity" else None,
        has_tk=False,
        display=":0",
    )
    assert zenity["available"] and zenity["method"] == "zenity"

    kdialog = fp._linux_plan(
        which=lambda name: "/usr/bin/kdialog" if name == "kdialog" else None,
        has_tk=False,
        display=":0",
    )
    assert kdialog["available"] and kdialog["method"] == "kdialog"


def test_linux_tkinter_needs_display() -> None:
    off = fp._linux_plan(which=lambda name: None, has_tk=True, display="")
    assert off["available"] is False and off["method"] == "none"
    on = fp._linux_plan(which=lambda name: None, has_tk=True, display=":0")
    assert on["available"] and on["method"] == "tkinter"


def test_pick_without_backend_gives_readable_error() -> None:
    original = fp.available
    fp.available = lambda: {"available": False, "method": "none", "platform": "linux"}
    try:
        try:
            fp.pick()
            raise AssertionError("没有可用的选择器时必须抛错")
        except RuntimeError as e:
            assert "无法打开系统目录选择窗口" in str(e)
    finally:
        fp.available = original


def test_pick_returns_none_on_cancel(monkeypatch=None) -> None:
    """取消选择（子进程返回非 0）应表现成 None，而不是异常。"""
    original_pick_available = fp.available
    original_run = fp._run
    fp.available = lambda: {"available": True, "method": "zenity", "platform": "linux"}
    fp._run = lambda args: None
    try:
        assert fp.pick() is None
    finally:
        fp.available = original_pick_available
        fp._run = original_run


def _main() -> int:
    tests = [
        ("平台信息", test_available_reports_platform_and_method),
        ("Windows 依赖 tkinter", test_windows_requires_tkinter),
        ("Linux 优先 zenity/kdialog", test_linux_prefers_zenity_then_kdialog),
        ("Linux tkinter 需要 DISPLAY", test_linux_tkinter_needs_display),
        ("无选择器时报错可读", test_pick_without_backend_gives_readable_error),
        ("取消返回 None", test_pick_returns_none_on_cancel),
    ]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  [PASS] {name}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {name}: {e}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(_main())

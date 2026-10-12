"""导出服务的错误处理回归测试。

对应验收中发现并修复的两个缺陷：

1. 缺少 LibreOffice 时，`subprocess.run` 抛出的 OSError 未被翻译，
   `api/export.py` 的兜底把它原样透出为 `FileNotFoundError: [WinError 2] …`，
   用户无法据此判断问题。
2. `ensure_export_dir` 用 `except OSError: pass` 把「目录建不出来」也一起吞掉，
   失败被推迟到更难定位的位置。

不依赖 pytest 也能运行：
    python backend/tests/test_export_service.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import export_service  # noqa: E402


class _temp_export_dir:
    """临时替换导出目录；Windows 上没有 os.chown，补一个空实现以模拟板端。"""

    def __init__(self, export_dir: Path) -> None:
        self.export_dir = export_dir

    def __enter__(self) -> None:
        self._dir = export_service.EXPORT_DIR
        self._chown = getattr(os, "chown", None)
        export_service.EXPORT_DIR = self.export_dir
        if self._chown is None:
            os.chown = lambda *a, **k: None  # type: ignore[attr-defined]

    def __exit__(self, *exc) -> None:
        export_service.EXPORT_DIR = self._dir
        if self._chown is None and hasattr(os, "chown"):
            del os.chown  # type: ignore[attr-defined]


def test_missing_libreoffice_message_is_actionable() -> None:
    """本机若无 LibreOffice，抛出的提示必须可定位、不泄漏内部异常。"""
    with _temp_export_dir(Path(tempfile.mkdtemp(prefix="test_export_"))):
        try:
            export_service.export("<p>x</p>", "pdf", "用例")
        except Exception as e:  # noqa: BLE001 - 这里就是要检查任意异常的内容
            msg = str(e)
            assert ("LibreOffice" in msg) or ("soffice" in msg), msg
            assert "FileNotFoundError" not in msg, msg
            assert not any(k in msg for k in ("WinError", "Traceback", "AttributeError")), msg
            return
        raise AssertionError("本机没有 LibreOffice，理应抛出异常")


def test_export_dir_failure_is_visible() -> None:
    """导出目录无法创建时必须立刻报错，不能静默继续。"""
    bad = Path("Z:/不存在的盘符/导出") if os.name == "nt" else Path("/proc/1/不存在的目录/导出")
    with _temp_export_dir(bad):
        try:
            export_service.ensure_export_dir()
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            assert "导出目录" in msg, msg
            assert not any(k in msg for k in ("WinError", "Traceback", "AttributeError")), msg
            return
        raise AssertionError("目录无法创建时不应静默返回")


def _main() -> int:
    tests = [
        ("缺少 LibreOffice 时提示可读", test_missing_libreoffice_message_is_actionable),
        ("导出目录不可用时必须报错", test_export_dir_failure_is_visible),
    ]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  [PASS] {name}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {name}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  [ERROR] {name}: {type(e).__name__}: {e}")
    print()
    print(f"合计 {len(tests)} 项，通过 {len(tests) - failed}，失败 {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())

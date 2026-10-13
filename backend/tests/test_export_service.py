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


PAPER_BODY = (
    '<div class="paper"><h1>在用曳引驱动电梯安全评估报告</h1>'
    '<table class="info"><tbody>'
    "<tr><th>委托单位名称</th><td>某某公司</td></tr>"
    "<tr><th>使用单位名称</th><td>某某公司</td></tr>"
    "</tbody></table></div>"
)


def test_build_html_keeps_the_document_as_is() -> None:
    """正文已经是完整文档时，不能再自己补标题和抬头信息表。

    现场反馈：导出的 PDF/Word 开头多出一张「委托单位/使用单位/设备类别/产品编号」
    的表格，而且抬头标签带淡蓝底 —— 那是 build_html 拿 meta_rows 另起了一张表，
    于是同一份抬头在文件里出现两次，样式也和 JTE 文档不一致。
    """
    html = export_service.build_html(
        title="在用曳引驱动电梯安全评估报告",
        meta_rows=[["委托单位名称", "某某公司"], ["使用单位名称", "某某公司"]],
        body_html=PAPER_BODY,
    )
    assert html.count("<h1>") == 1, html.count("<h1>")
    assert 'class="meta"' not in html
    # 官方模板 JTE-09-R02-3.00 的 w:shd 填充全是 FFFFFF，一处底色都没有；
    # 导出件也必须一个 background 都不加（淡蓝 #eef3f6、浅灰 #f2f2f2 都算多加）。
    assert "background" not in html
    # 纸张里的表格按 JTE 文档：黑框
    assert "1px solid #000" in html


def test_build_html_still_works_without_body() -> None:
    """没有正文时（理论上不会发生）仍要能出一份可读的标题 + 抬头表。"""
    html = export_service.build_html(
        title="电梯安全评估报告",
        meta_rows=[["委托单位名称", "某某公司"]],
        body_html="",
    )
    assert "<h1>电梯安全评估报告</h1>" in html
    assert 'class="meta"' in html


def _main() -> int:
    tests = [
        ("正文已是完整文档时不再补标题/抬头表", test_build_html_keeps_the_document_as_is),
        ("没有正文时仍能出标题+抬头表", test_build_html_still_works_without_body),
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

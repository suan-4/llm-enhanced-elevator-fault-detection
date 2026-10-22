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
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import export_service  # noqa: E402


class _temp_export_dir:
    """只替换导出目录，不伪造操作系统具备的能力。"""

    def __init__(self, export_dir: Path) -> None:
        self.export_dir = export_dir

    def __enter__(self) -> None:
        self._dir = export_service.EXPORT_DIR
        export_service.EXPORT_DIR = self.export_dir

    def __exit__(self, *exc) -> None:
        export_service.EXPORT_DIR = self._dir


def test_missing_libreoffice_message_is_actionable() -> None:
    """本机若无 LibreOffice，抛出的提示必须可定位、不泄漏内部异常。"""
    with tempfile.TemporaryDirectory(prefix="test_export_") as tmp, \
            _temp_export_dir(Path(tmp)), \
            patch.object(export_service, "SOFFICE", str(Path(tmp) / "missing-soffice")):
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
    with tempfile.TemporaryDirectory(prefix="test_export_bad_") as tmp:
        blocked = Path(tmp) / "not-a-directory"
        blocked.touch()
        bad = blocked / "exports"
        with _temp_export_dir(bad):
            try:
                export_service.ensure_export_dir()
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                assert "导出目录" in msg, msg
                assert not any(k in msg for k in ("WinError", "Traceback", "AttributeError")), msg
                return
            raise AssertionError("目录无法创建时不应静默返回")


def test_export_directory_does_not_require_posix_chown() -> None:
    """没有chown的平台也能创建可写导出目录，不能用测试替身补上该能力。"""
    with tempfile.TemporaryDirectory(prefix="test_export_caps_") as tmp, \
            _temp_export_dir(Path(tmp) / "exports"), \
            patch.object(export_service, "os", SimpleNamespace(chmod=os.chmod)):
        export_service.ensure_export_dir()
        probe = export_service.EXPORT_DIR / "probe"
        probe.write_bytes(b"writable")
        assert probe.read_bytes() == b"writable"


def test_completed_export_does_not_require_posix_chown() -> None:
    """外部转换器产出文件后，不得在最终文件权限设置阶段再次崩溃。"""
    def converted(cmd, **kwargs):
        out = Path(cmd[cmd.index("--outdir") + 1])
        fmt = cmd[cmd.index("--convert-to") + 1]
        (out / (Path(cmd[-1]).stem + "." + fmt)).write_bytes(b"converter-fixture")
        return SimpleNamespace(stdout=b"", stderr=b"", returncode=0)

    with tempfile.TemporaryDirectory(prefix="test_export_output_") as tmp, \
            _temp_export_dir(Path(tmp) / "exports"), \
            patch.object(export_service, "os", SimpleNamespace(chmod=os.chmod)), \
            patch.object(export_service.subprocess, "run", converted):
        result = export_service.export("<p>fixture</p>", "docx", "report")
        final = Path(result["path"])
        assert final.parent == export_service.EXPORT_DIR
        assert final.read_bytes() == b"converter-fixture"
        assert result["fmt"] == "docx" and result["size"] > 0
        timings = result.get('performance', {})
        assert {'convert_ms','publish_ms','cleanup_ms','export_total_ms'} <= set(timings), timings
        assert timings['export_total_ms'] >= timings['convert_ms'] + timings['publish_ms']


def test_posix_ownership_is_still_attempted() -> None:
    """兼容Windows不能取消板端原本需要的目录属主设置。"""
    calls = []
    with tempfile.TemporaryDirectory(prefix="test_export_posix_") as tmp, \
            _temp_export_dir(Path(tmp) / "exports"), \
            patch.object(export_service, "os", SimpleNamespace(
                chown=lambda *args: calls.append(args), chmod=os.chmod)):
        export_service.ensure_export_dir()
        assert calls == [(export_service.EXPORT_DIR, 1002, 1002)]


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


def test_document_sections_and_header_columns_survive_export() -> None:
    """导出HTML须显式传递分节和列宽，不能依赖没有随正文传入的网页CSS。"""
    class Tags(HTMLParser):
        def __init__(self):
            super().__init__()
            self.columns = []
            self.breaks = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'col':
                self.columns.append(attrs.get('width'))
            if tag == 'p' and 'page-break-before' in attrs.get('style', ''):
                self.breaks.append(attrs['style'])

    body = PAPER_BODY + '<div class="paper"><p>Evaluation</p></div><div class="paper"><p>Appendix</p></div>'
    parser = Tags()
    html = export_service.build_html('Report', [], body)
    parser.feed(html)
    assert parser.columns == ['15%', '35%', '15%', '35%'], parser.columns
    assert len(parser.breaks) == 2, parser.breaks
    assert html.count('class="paper"') == 3
    assert html.index('page-break-before') > html.index('某某公司')


def test_existing_header_columns_are_not_duplicated() -> None:
    body = PAPER_BODY.replace('<tbody>', '<colgroup><col width="25%"><col width="75%"></colgroup><tbody>')
    html = export_service.build_html('Report', [], body)
    assert html.count('<colgroup>') == 1
    assert '<col width="25%">' in html


def _main() -> int:
    tests = [
        ("正文已是完整文档时不再补标题/抬头表", test_build_html_keeps_the_document_as_is),
        ("没有正文时仍能出标题+抬头表", test_build_html_still_works_without_body),
        ("缺少 LibreOffice 时提示可读", test_missing_libreoffice_message_is_actionable),
        ("导出目录不可用时必须报错", test_export_dir_failure_is_visible),
        ("缺少chown也能创建导出目录", test_export_directory_does_not_require_posix_chown),
        ("转换完成后无chown也能发布文件", test_completed_export_does_not_require_posix_chown),
        ("板端仍设置POSIX属主", test_posix_ownership_is_still_attempted),
        ("导出保留分节与抬头表列宽", test_document_sections_and_header_columns_survive_export),
        ("已有列宽不重复注入", test_existing_header_columns_are_not_duplicated),
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

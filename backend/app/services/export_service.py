"""报告导出：把评估报告产出为 Word(.docx) 与 PDF。

实现方式：先生成一份自包含的 HTML（内联样式 + 中文 Noto CJK 字体），
再交给板端本来就有的 LibreOffice 无头转换：

    HTML --(--infilter "HTML (StarWriter)")-->  .docx   (MS Word 2007 XML)
                                            +-->  .pdf    (writer_pdf_Export)

为什么走 HTML 而不是手写 OOXML：
  - 版式（标题层级、表格边框、A4 分页、页边距）交给 LibreOffice 处理，
    比自己拼 word/document.xml 可靠得多；
  - 同一份内容天然得到两种格式，不会出现"Word 和 PDF 长得不一样"；
  - 中文由系统里的 Noto Sans CJK 正常输出，无需在 PDF 里嵌字体子集；
  - **零新增依赖**（板端完全离线，apt 不可用，这点是硬约束）。

实测踩过的坑：
  1) 必须加 --infilter="HTML (StarWriter)"。
     否则 LibreOffice 会按 Writer/Web 模块打开 HTML，而那个模块**没有
     DOCX 导出过滤器**，直接报
         Error: no export filter for xxx.docx found, aborting.
  2) 必须给独立的 -env:UserInstallation。
     否则会和用户/桌面上正在跑的 LibreOffice 实例抢 profile 而卡死。
"""
import os
import re
import shutil
import subprocess
import tempfile
from time import perf_counter
from datetime import datetime
from pathlib import Path

SOFFICE = "/usr/bin/soffice"
# 导出目录放在 GUI 用户家目录下，方便退出到桌面后取走文件。
# 统一从配置取（config.py 的 export_dir），避免"文档写一个、代码写另一个"。
from app.config import settings  # noqa: E402

EXPORT_DIR = Path(settings.export_dir)
EXPORT_UID = 1002
EXPORT_GID = 1002
CONVERT_TIMEOUT = 240
ALLOWED_FORMATS = ("pdf", "docx")


def _esc(v) -> str:
    return (str("" if v is None else v)
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


_TABLE_RE = re.compile(r"<table\b([^>]*)>", re.I)
_PAPER_RE = re.compile(r'''<div\b[^>]*\bclass=["']paper["'][^>]*>''', re.I)
_INFO_RE = re.compile(
    r'''(<table\b[^>]*\bclass=["']info["'][^>]*>)(.*?)(</table>)''', re.I | re.S)


def _document_layout(body_html: str) -> str:
    """把网页CSS之外的文档结构显式传给Writer HTML导入器。"""
    first = True

    def section(match):
        nonlocal first
        if first:
            first = False
            return match.group(0)
        # Writer忽略div上的page-break-before，但识别段落上的该属性。
        return '<p style="page-break-before: always; margin: 0"></p>' + match.group(0)

    def columns(match):
        if re.match(r'\s*<colgroup\b', match.group(2), re.I):
            return match.group(0)
        # info表为标签/值/标签/值四列，跨三列的整行字段保持原有colspan。
        grid = '<colgroup><col width="15%"><col width="35%"><col width="15%"><col width="35%"></colgroup>'
        return match.group(1) + grid + match.group(2) + match.group(3)

    return _INFO_RE.sub(columns, _PAPER_RE.sub(section, body_html or ""))


def _borderize(html_str: str) -> str:
    """给正文里所有 <table> 注入 border 属性。

    ★ 实测结论：LibreOffice 的 HTML 导入**完全不认 CSS 的表格边框** ★
      方式A  CSS 简写  td{border:1px solid #999}          -> 无边框
      方式B  CSS 长写  td{border-width/style/color:...}   -> 无边框
      方式C  HTML 属性 <table border="1">                 -> 有边框 ✓
    报告正文的表格直接取自页面已渲染的 HTML（没有这个属性），
    不补的话导出后就是无框的散排文字，作为评估报告不可用。
    """
    def repl(m):
        attrs = m.group(1)
        if "border" in attrs.lower():
            return m.group(0)
        return '<table border="1" cellspacing="0" cellpadding="4" width="100%%"%s>' % attrs
    return _TABLE_RE.sub(repl, html_str or "")


def _safe_stem(stem: str) -> str:
    """去掉文件名里的路径分隔符与控制字符，避免目录穿越。"""
    stem = (stem or "报告").strip()
    for ch in '\\/:*?"<>|\r\n\t':
        stem = stem.replace(ch, "_")
    stem = stem.strip(". ") or "报告"
    return stem[:80]


def ensure_export_dir() -> None:
    try:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        # 目录建不出来，后续必然失败（转换完无处落盘）。
        # 必须立刻抛出：静默继续只会把错误推迟到更难定位的位置。
        # 只取 e.strerror（如「拒绝访问」），不带 [WinError N] 之类的平台噪音。
        raise RuntimeError(
            "导出目录不可用（%s）：%s。请检查该路径是否存在、磁盘是否可写。"
            % (EXPORT_DIR, (e.strerror or str(e)).rstrip("。."))
        ) from e
    # 属主与权限是给桌面用户取文件用的；改不动不影响导出本身，可以容忍。
    try:
        if hasattr(os, "chown"):
            os.chown(EXPORT_DIR, EXPORT_UID, EXPORT_GID)
        os.chmod(EXPORT_DIR, 0o755)
    except OSError:
        pass


def build_html(title: str, meta_rows, body_html: str,
               subtitle: str = "", footer: str = "") -> str:
    """把结构化数据拼成一份自包含、适合打印的 HTML。"""
    rows = "".join(
        '<tr><th>%s</th><td>%s</td></tr>' % (_esc(k), _esc(v))
        for k, v in (meta_rows or []) if v not in (None, "")
    )
    # 同样必须用 border 属性而不是 CSS，理由见 _borderize()
    meta_table = ('<table border="1" cellspacing="0" cellpadding="4" '
                  'width="100%%" class="meta">%s</table>' % rows) if rows else ""
    sub_html = '<div class="sub">%s</div>' % _esc(subtitle) if subtitle else ""
    # 正文已经是前端渲染好的整份文档（自带标题和自己那张抬头表）时，这里绝不能再补
    # 标题和 meta 表：否则导出的 PDF/Word 开头会多出一张「委托单位/使用单位/设备类别/
    # 产品编号」的表，同一份抬头在文件里出现两次（现场反馈）。
    head_html = "" if (body_html or "").strip() else (
        "<h1>%s</h1>%s%s" % (_esc(title), sub_html, meta_table)
    )
    return """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>%(title)s</title>
<style>
/* Writer HTML导入不识别A4简写，会静默退回Letter，必须使用明确尺寸。 */
@page { size: 210mm 297mm; margin: 20mm 18mm 18mm 18mm; }
body  { font-family: "Noto Sans CJK SC","Noto Sans CJK JP","WenQuanYi Zen Hei",sans-serif;
        font-size: 10.5pt; line-height: 1.35; color: #1a1a1a; }
h1    { font-size: 17pt; text-align: center; margin: 0 0 4pt 0; }
.sub  { text-align: center; font-size: 10pt; color: #5a6b75; margin: 0 0 16pt 0; }
h2    { font-size: 12.5pt; color: #1b5e7a; margin: 16pt 0 8pt 0;
        border-bottom: 1px solid #cfd8dd; padding-bottom: 3pt; }
h3    { font-size: 11pt;  color: #22475c; margin: 12pt 0 6pt 0; }
h4    { font-size: 10.5pt;color: #22475c; margin: 10pt 0 5pt 0; }
p     { margin: 0 0 6pt 0; }
ul,ol { margin: 0 0 6pt 0; padding-left: 20pt; }
li    { margin-bottom: 3pt; }
table.meta { border-collapse: collapse; width: 100%%; margin-bottom: 14pt; }
table.meta th { width: 26%%; text-align: left; font-weight: bold; }
table.meta th, table.meta td { border: 1px solid #000; padding: 4pt 7pt; font-size: 10pt; }
/* 报告正文里的表格没有类名（直接取自页面已渲染的 HTML），
   所以这里对裸 table/th/td 也要给边框，否则导出后是无框的散排文字 */
/* 纸张里的表格按 JTE 文档：只留黑色框线，任何地方都不加底色。
   实测模板 JTE-09-R02-3.00 的 w:shd 填充全是 FFFFFF（白），没有一处彩色底；
   之前给表头加淡蓝底、后来又改成浅灰底，都是凭空加的（现场反馈「抬头标题有背景色」）。 */
table { border-collapse: collapse; width: 100%%; margin: 6pt 0 12pt 0; }
th, td { border: 1px solid #000; padding: 1.5mm 2mm; font-size: 9pt; vertical-align: top; }
th { font-weight: bold; }
table.meta th, table.meta td { padding: 4pt 7pt; font-size: 10pt; }
.card { margin: 0 0 8pt 0; }
.raw-text { font-size: 10.5pt; }
.section-title, .card-header { font-weight: bold; }
.empty { color: #6b7b85; }
.notes { font-size: 9pt; }
.foot { margin-top: 22pt; font-size: 9pt; color: #6b7b85; text-align: center; }
</style></head>
<body>
%(head)s
%(body)s
%(foot)s
</body></html>
""" % {
        "title": _esc(title),
        "sub": sub_html,
        "meta": meta_table,
        "head": head_html,
        "body": _borderize(_document_layout(body_html)),
        "foot": ('<div class="foot">%s</div>' % _esc(footer)) if footer else "",
    }


def export(html_str: str, fmt: str, stem: str) -> dict:
    """把 html_str 转成 fmt(pdf|docx) 并落到 EXPORT_DIR，返回文件信息。"""
    started = perf_counter()
    timings = {}
    fmt = (fmt or "").lower().strip()
    if fmt not in ALLOWED_FORMATS:
        raise ValueError("不支持的导出格式：%s（只支持 pdf / docx）" % fmt)

    ensure_export_dir()
    clean_stem = _safe_stem(stem)
    work = Path(tempfile.mkdtemp(prefix="elevator_export_"))
    profile = work / "loprofile"
    try:
        src = work / (clean_stem + ".html")
        src.write_text(html_str, encoding="utf-8")

        cmd = [
            SOFFICE, "--headless", "--norestore", "--nolockcheck", "--nodefault",
            "-env:UserInstallation=file://%s" % profile,
            '--infilter=HTML (StarWriter)',
            "--convert-to", fmt,
            "--outdir", str(work),
            str(src),
        ]
        convert_started = perf_counter()
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=CONVERT_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise RuntimeError("转换超时（%d 秒），请重试" % CONVERT_TIMEOUT)
        except OSError as e:
            # 常见于板端未安装 LibreOffice 或路径不可执行。
            # 必须转成可执行提示：原始 OSError 只会显示 "系统找不到指定的文件"，
            # 用户无法据此判断问题所在。
            raise RuntimeError(
                "导出失败：无法启动 LibreOffice（%s）。"
                "请确认板端已安装 LibreOffice，且该路径存在且可执行。" % SOFFICE
            ) from e

        timings['convert_ms'] = (perf_counter()-convert_started)*1000

        out = work / (clean_stem + "." + fmt)
        if not out.exists():
            msg = ((proc.stdout or b"") + (proc.stderr or b"")).decode("utf-8", "replace")
            raise RuntimeError("LibreOffice 未产出文件：%s" % msg.strip()[-500:])

        publish_started = perf_counter()
        final = EXPORT_DIR / out.name
        if final.exists():      # 同一秒重复导出时不覆盖
            final = EXPORT_DIR / ("%s_%s.%s" % (clean_stem, datetime.now().strftime("%H%M%S"), fmt))
        shutil.move(str(out), str(final))
        try:
            if hasattr(os, "chown"):
                os.chown(final, EXPORT_UID, EXPORT_GID)
            os.chmod(final, 0o644)
        except OSError:
            pass

        result = {
            "filename": final.name,
            "path": str(final),
            "dir": str(EXPORT_DIR),
            "size": final.stat().st_size,
            "fmt": fmt,
        }
        timings['publish_ms'] = (perf_counter()-publish_started)*1000
    finally:
        cleanup_started = perf_counter()
        shutil.rmtree(work, ignore_errors=True)
        timings['cleanup_ms'] = (perf_counter()-cleanup_started)*1000
    timings['export_total_ms'] = (perf_counter()-started)*1000
    result['performance'] = {key:round(value, 3) for key,value in timings.items()}
    return result

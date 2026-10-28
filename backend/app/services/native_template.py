"""Fill the verified JTE OOXML package; never rebuild it from browser HTML.

Only document.xml, report-number headers and updateFields are editable.
The remaining ZIP parts (including equations' dependencies/styles) stay byte-identical.
"""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re
from xml.dom import minidom
from zipfile import ZipFile

TEMPLATE = Path(__file__).resolve().parent.parent / "data" / "jte_template.docx"
TEMPLATE_SHA256 = "d5be8cdbe1dbf9ac5dde6cfc57ff9bdaa31ccf9db7a5acbb8e9e012df47f9fff"


def children(node, tag):
    return [n for n in node.childNodes if n.nodeType == n.ELEMENT_NODE and n.tagName == tag]


def text(node):
    return "".join(n.firstChild.data if n.firstChild else "" for n in node.getElementsByTagName("w:t"))


def replace_text(node, value):
    """Preserve cell/paragraph/run properties, replace only the slot content."""
    document = node.ownerDocument
    paragraphs = children(node, "w:p")
    paragraph = paragraphs[0] if paragraphs else node
    properties = children(paragraph, "w:pPr")
    runs = paragraph.getElementsByTagName("w:r")
    run_properties = children(runs[0], "w:rPr") if runs else []
    for child in list(paragraph.childNodes):
        if child not in properties:
            paragraph.removeChild(child)
    for extra in paragraphs[1:]:
        node.removeChild(extra)
    run = document.createElement("w:r")
    if run_properties:
        run.appendChild(run_properties[0].cloneNode(True))
    for i, line in enumerate(str(value).split("\n")):
        if i:
            run.appendChild(document.createElement("w:br"))
        t = document.createElement("w:t")
        t.setAttribute("xml:space", "preserve")
        t.appendChild(document.createTextNode(line))
        run.appendChild(t)
    paragraph.appendChild(run)


def page_break(paragraph):
    props = children(paragraph, "w:pPr")
    props = props[0] if props else paragraph.insertBefore(
        paragraph.ownerDocument.createElement("w:pPr"), paragraph.firstChild)
    if not children(props, "w:pageBreakBefore"):
        props.appendChild(paragraph.ownerDocument.createElement("w:pageBreakBefore"))


def _append_paragraph(document, body, text_value="", *, bold=False, size=24, page_break=False):
    paragraph = document.createElement("w:p")
    if page_break:
        run = document.createElement("w:r")
        br = document.createElement("w:br")
        br.setAttribute("w:type", "page")
        run.appendChild(br)
        paragraph.appendChild(run)
    run = document.createElement("w:r")
    props = document.createElement("w:rPr")
    if bold:
        props.appendChild(document.createElement("w:b"))
    sz = document.createElement("w:sz")
    sz.setAttribute("w:val", str(size))
    props.appendChild(sz)
    run.appendChild(props)
    node = document.createElement("w:t")
    node.setAttribute("xml:space", "preserve")
    node.appendChild(document.createTextNode(str(text_value)))
    run.appendChild(node)
    paragraph.appendChild(run)
    sections = children(body, "w:sectPr")
    if sections:
        body.insertBefore(paragraph, sections[0])
    else:
        body.appendChild(paragraph)


def _append_analysis(document, body, analysis_text):
    """在 Word 模板末尾追加「文本分析报告」，不改模板原有页面。"""
    _append_paragraph(document, body, "文本分析报告", bold=True, size=30, page_break=True)
    _append_paragraph(document, body, "以下内容由大模型基于本次评估事实与人工勾选的候选路径生成，未签核，供复核。",
                      size=18)
    for line in str(analysis_text).split("\n"):
        _append_paragraph(document, body, line, size=22)


def build_docx(report):
    try:
        original = TEMPLATE.read_bytes()
    except OSError as exc:
        raise RuntimeError("原始Word模板缺失，请恢复模板文件后重试") from exc
    if sha256(original).hexdigest() != TEMPLATE_SHA256:
        raise RuntimeError("原始Word模板校验失败，请勿使用未经核对的模板")
    with ZipFile(BytesIO(original)) as source:
        doc = minidom.parseString(source.read("word/document.xml"))
        body = doc.getElementsByTagName("w:body")[0]
        tables = children(body, "w:tbl")
        if len(tables) != 12:
            raise RuntimeError("模板表格结构不匹配")
        # Compose display values without modifying the immutable report snapshot.
        form = dict(report["form"])
        if any(key in form for key in ('floors', 'stops', 'doors')):
            form['floorsStopsDoors'] = '　'.join(
                f"{str(form.get(key) or '/').strip() or '/'} {unit}"
                for key, unit in (('floors', '层'), ('stops', '站'), ('doors', '门')))
        for key, unit in (('ratedLoad', 'kg'), ('ratedSpeed', 'm/s')):
            raw = str(form.get(key) or '/').strip() or '/'
            if raw == '/' or re.fullmatch(r'\d+(?:\.\d+)?', raw):
                form[key] = f'{raw} {unit}'
        value = lambda key: str(form.get(key) or "/").strip() or "/"
        for row, key in zip(children(tables[0], 'w:tr'),
                            ('clientName', 'userName', 'deviceVariety', 'productNo', 'assessDate')):
            cell = children(row, 'w:tc')[1]
            # The colon and the underlined value are separate source runs.
            underline = next(run.cloneNode(True) for run in cell.getElementsByTagName('w:r')
                             if run.getElementsByTagName('w:u'))
            replace_text(cell, '：')
            for child in list(underline.childNodes):
                if child.nodeType == child.ELEMENT_NODE and child.tagName != 'w:rPr':
                    underline.removeChild(child)
            filled = value(key)
            visual_length = sum(2 if ord(char) > 127 else 1 for char in filled)
            label = doc.createElement('w:t')
            label.setAttribute('xml:space', 'preserve')
            label.appendChild(doc.createTextNode(filled + ' ' * max(0, 32 - visual_length)))
            underline.appendChild(label)
            children(cell, 'w:p')[0].appendChild(underline)
        header = children(tables[1], "w:tr")
        slots = {
            0: [(1, "clientName")], 1: [(1, "userName")], 2: [(1, "installSite")],
            3: [(1, "deviceCategory"), (3, "deviceVariety")],
            4: [(1, "model"), (3, "productNo")],
            5: [(1, "registerNo"), (3, "manufactureDate")],
            6: [(1, "manufacturer")], 7: [(1, "retrofitUnit"), (3, "retrofitDate")],
            8: [(1, "maintainUnit")], 9: [(2, "ratedLoad"), (4, "ratedSpeed")],
            10: [(2, "floorsStopsDoors"), (4, "controlMode")],
            11: [(1, "instruments")], 12: [(1, "basis")],
            15: [(1, "suggestion")], 16: [(1, "remark")], 17: [(1, "assessDate")],
        }
        for row, fields in slots.items():
            for col, key in fields:
                replace_text(children(header[row], "w:tc")[col], value(key))
        risks = report["risks"]
        counts = {c: sum(r.get("category") == c for r in risks.values()) for c in ("Ⅰ类", "Ⅱ类")}
        overview = (f"1、存在Ⅰ类风险 {counts['Ⅰ类']} 项，Ⅱ类风险 {counts['Ⅱ类']} 项。\n"
                    f"2、综合安全状况得分 {report['score']}。\n{report['narrative']}")
        replace_text(children(header[13], "w:tc")[1], overview)
        replace_text(children(header[14], "w:tc")[1], f"综合安全状况等级：{report['grade']}")

        answers = {i["no"]: i for i in report["items"]}
        order = []
        for table in tables[2:8]:
            rows = children(table, "w:tr")
            for row in rows[:2]:
                props = children(row, "w:trPr")
                props = props[0] if props else row.insertBefore(doc.createElement("w:trPr"), row.firstChild)
                if not children(props, "w:tblHeader"):
                    props.appendChild(doc.createElement("w:tblHeader"))
            for row in rows:
                cells = children(row, "w:tc")
                no = text(cells[0]).strip()
                if not re.fullmatch(r"\d{1,2}\.\d{1,2}", no):
                    continue
                if no not in answers or no in order:
                    raise ValueError("报告项目与原始模板不一致，不能导出")
                order.append(no)
                item = answers[no]
                risk = risks.get(no)
                result = {"fit": "符合", "unfit": "不符合", "na": "无此项"}[item["result"]]
                if item["result"] == "unfit":
                    descriptions = [r["text"] for r in risk["selected_risks"]]
                    if item.get("other_text"):
                        descriptions.append("现场描述：" + item["other_text"])
                    result += "\n" + "\n".join(dict.fromkeys(descriptions))
                vals = [result] + [
                    str(risk.get(key)) if risk and risk.get(key) is not None else "/"
                    for key in ("severity", "probability", "category")
                ]
                for cell, val in zip(cells[-4:], vals):
                    replace_text(cell, val)
        if len(order) != 66 or set(order) != set(answers):
            raise ValueError("报告必须包含完整66项，不能导出")

        appendix = tables[8]
        rows = children(appendix, "w:tr")
        pattern = rows[1].cloneNode(True)
        for row in rows[1:]:
            appendix.removeChild(row)
        unfit = [no for no in order if answers[no]["result"] == "unfit"]
        for i, no in enumerate(unfit or [None], 1):
            row = pattern.cloneNode(True)
            if no:
                risk = risks[no]
                details = risk["selected_risks"]
                vals = [str(i), no, "\n".join(f"{j}、{r['text']}" for j, r in enumerate(details, 1)),
                        risk["category"], "\n".join(f"{j}、{r['measure']}" for j, r in enumerate(details, 1))]
            else:
                vals = ["/", "/", "无", "/", "/"]
            for cell, val in zip(children(row, "w:tc"), vals):
                replace_text(cell, val)
            appendix.appendChild(row)

        # Keep the original cover and notice, including their logo and section geometry.
        elements = [n for n in body.childNodes if n.nodeType == n.ELEMENT_NODE]
        start = elements.index(tables[1]) - 1
        front_matter = set(elements[:start])
        # LibreOffice may spill the source's empty section-end paragraph to a blank
        # page even with exact 1pt spacing. Move the same sectPr to the preceding
        # content paragraph, dropping only its empty tail. Keep all section geometry.
        for index, node in enumerate(elements[:start]):
            if node.tagName != 'w:p' or not node.getElementsByTagName('w:sectPr'):
                continue
            cursor = index - 1
            while cursor >= 0:
                blank = elements[cursor]
                if blank.tagName != 'w:p' or text(blank).strip() or blank.getElementsByTagName('w:drawing'):
                    break
                cursor -= 1
            anchor = elements[cursor]
            if cursor < 0 or anchor.tagName != 'w:p':
                raise RuntimeError('模板分节锚点结构不匹配')
            properties = children(anchor, 'w:pPr')
            props = properties[0] if properties else anchor.insertBefore(doc.createElement('w:pPr'), anchor.firstChild)
            props.appendChild(node.getElementsByTagName('w:sectPr')[0])
            for blank in elements[cursor+1:index+1]:
                if blank.parentNode == body:
                    body.removeChild(blank)
        # Empty photo appendix has no input source. Keep section geometry at end.
        photo_title = next(n for n in elements if n.tagName == "w:p" and text(n).strip() == "附图：")
        for node in elements[elements.index(photo_title):]:
            if node.tagName != "w:sectPr" and node.parentNode == body:
                body.removeChild(node)
        # Source contains paragraphs used to pad a fixed sample to full pages.
        # Content is variable now: explicit section starts, no manufactured blank pages.
        for node in list(children(body, "w:p")):
            if node in front_matter:
                continue
            t = text(node).strip()
            if t.startswith("（本页为可选页") or (
                not t and not node.getElementsByTagName("m:oMath")
                and not node.getElementsByTagName("m:oMathPara")
            ):
                body.removeChild(node)
            elif t in ("附页：", "附录A"):
                page_break(node)
        # Preserve equations and table geometry; no fixed heights may clip long input.
        for height in doc.getElementsByTagName("w:trHeight"):
            if height.getAttribute("w:hRule") == "exact":
                height.setAttribute("w:hRule", "atLeast")
        evaluation_start = doc.createElement("w:p")
        page_break(evaluation_start)
        body.insertBefore(evaluation_start, tables[2])
        for index, sect in enumerate(doc.getElementsByTagName("w:sectPr")):
            for ref in sect.getElementsByTagName("w:headerReference"):
                if ref.getAttribute("w:type") == "default":
                    ref.setAttribute("r:id", "rId5")
            for ref in sect.getElementsByTagName("w:footerReference"):
                if ref.getAttribute("w:type") == "default":
                    ref.setAttribute("r:id", "rId11")
            for page in sect.getElementsByTagName("w:pgNumType"):
                if index == 0:
                    page.setAttribute("w:start", "1")
                elif page.hasAttribute('w:start'):
                    page.removeAttribute('w:start')

        changed = {"word/document.xml": doc.toxml(encoding="UTF-8")}
        for name in source.namelist():
            if name.startswith("word/header") and name.endswith(".xml"):
                h = minidom.parseString(source.read(name))
                for paragraph in h.getElementsByTagName("w:p"):
                    if "报告编号：" in text(paragraph):
                        replace_text(paragraph, "报告编号：" + report["report_no"])
                        props = children(paragraph, "w:pPr")[0]
                        for indent in children(props, "w:ind"):
                            props.removeChild(indent)
                        align = children(props, "w:jc")
                        align = align[0] if align else props.appendChild(h.createElement("w:jc"))
                        align.setAttribute("w:val", "right")
                        changed[name] = h.toxml(encoding="UTF-8")
            if name.startswith("word/footer") and name.endswith(".xml"):
                footer = minidom.parseString(source.read(name))
                for paragraph in footer.getElementsByTagName("w:p"):
                    if not re.search(r"第\s*\d+\s*页\s*共\s*\d+\s*页", text(paragraph)):
                        continue
                    replace_text(paragraph, "第 ")
                    run = children(paragraph, "w:r")[0]
                    for label, instruction in (("1", "PAGE"), (" 页 共 ", ""),
                                               ("1", "NUMPAGES"), (" 页", "")):
                        piece = run.cloneNode(True)
                        piece.getElementsByTagName("w:t")[0].firstChild.data = label
                        if instruction:
                            field = footer.createElement("w:fldSimple")
                            field.setAttribute("w:instr", instruction)
                            field.appendChild(piece)
                            paragraph.appendChild(field)
                        else:
                            paragraph.appendChild(piece)
                    changed[name] = footer.toxml(encoding="UTF-8")
        analysis_text = str((report.get("provenance") or {}).get("analysis_text") or "").strip()
        if analysis_text:
            _append_analysis(doc, body, analysis_text)
            # document.xml 在第 275 行已序列化一次；追加段落后必须重新写回 changed
            changed["word/document.xml"] = doc.toxml(encoding="UTF-8")
        settings = minidom.parseString(source.read("word/settings.xml"))
        fields = settings.getElementsByTagName("w:updateFields")
        field = fields[0] if fields else settings.documentElement.appendChild(settings.createElement("w:updateFields"))
        field.setAttribute("w:val", "true")
        changed["word/settings.xml"] = settings.toxml(encoding="UTF-8")
        output = BytesIO()
        with ZipFile(output, "w") as target:
            for entry in source.infolist():
                target.writestr(entry, changed.get(entry.filename, source.read(entry.filename)))
        return output.getvalue()

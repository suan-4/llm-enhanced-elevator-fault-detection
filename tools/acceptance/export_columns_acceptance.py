"""Real board Writer regression. Only synthetic data; never opens a business DB.

PYTHONPATH=<candidate backend> python3 export_columns_acceptance.py --output-dir <new dir>
Requires the board's real soffice, pdfinfo and pdftotext. Retains artifacts for visual QA.
"""
import argparse
import json
import re
import xml.etree.ElementTree as ET
from html import escape
from pathlib import Path
from zipfile import ZipFile

from app.services import export_service, expert_risk

NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
EXPECTED = [544, 1328, 4478, 995, 624, 624, 629]


def body(result):
    return ('<div class="paper"><h1>列宽回归测试</h1><table class="evaluation">'
            '<thead><tr><th rowspan="2" style="width:16mm">项目编号</th>'
            '<th rowspan="2" style="width:22mm">项目</th><th rowspan="2">评价内容与要求</th>'
            '<th rowspan="2" style="width:30mm">评价结果</th>'
            '<th colspan="3" style="width:38mm">风险评定值</th></tr>'
            '<tr><th style="width:12mm">严重程度</th><th style="width:12mm">概率等级</th>'
            '<th style="width:12mm">风险类别</th></tr></thead><tbody>'
            '<tr><td>1.7</td><td>机房工作安全空间</td><td>机房应有足够的工作空间，'
            '以允许人员安全和容易地对有关设备进行作业，尤其是对电气设备的作业。</td>'
            '<td>符合</td><td>2</td><td>F</td><td>Ⅲ类</td></tr>'
            '<tr><td>16.1</td><td>控制柜</td><td>控制柜散热通道应畅通，电气元件温升应正常。</td>'
            f'<td>{escape(result)}</td><td>2</td><td>B</td><td>Ⅰ类</td></tr>'
            '</tbody></table><p>END_OF_TABLE</p></div>')


def inspect_docx(path):
    with ZipFile(path) as z:
        root = ET.fromstring(z.read('word/document.xml'))
    table = root.find('.//w:tbl', NS)
    widths = [int(col.get('{'+NS['w']+'}w')) for col in table.findall('w:tblGrid/w:gridCol', NS)]
    ratios = [value/sum(widths) for value in widths]
    return root, widths, ratios


def full_body(result):
    """Exercise all item names, numeric identifiers and requirements, not just two rows."""
    catalog = json.loads((Path(export_service.__file__).resolve().parents[1] / 'data/jte_items.json').read_text())['items']
    rows = []
    for item in catalog:
        no = item['no']
        value = result if no == '16.1' else '符合'
        risk = expert_risk.assess(no, 'unfit' if no == '16.1' else 'fit',
                                 expert_risk.options(no) if no == '16.1' else [])
        req = ''.join('<div>'+escape(re.sub(r'^[a-zA-Z][)）]\s*', '', line))+'</div>' for line in item['req'])
        rows.append('<tr><td>'+escape(no)+'</td><td>'+escape(item['name']+' '+item.get('sub',''))+
                    '</td><td>'+req+'</td><td>'+escape(value)+'</td><td>'+str(risk['severity'])+
                    '</td><td>'+str(risk['probability'])+'</td><td>'+risk['category']+'</td></tr>')
    return re.sub(r'(<tbody>).*?(</tbody>)', lambda m:m[1]+''.join(rows)+m[2], body(result), flags=re.S)


def main():
    import subprocess
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--full-report', action='store_true', help='Also exercise the complete 66-item table; same strict ratio gate')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    original = export_service.EXPORT_DIR
    records = []
    failures = []
    risks = expert_risk.options('16.1')
    cases = {'short': '不符合（'+risks[-1]['text']+'）',
             'long32': '不符合（'+'；'.join(r['text'] for r in risks)+'）'}
    try:
        export_service.EXPORT_DIR = args.output_dir
        for name, result in cases.items():
            html = export_service.build_html('Columns regression', [], full_body(result) if args.full_report else body(result))
            (args.output_dir/(name+'.html')).write_text(html, encoding='utf8')
            pdf = Path(export_service.export(html, 'pdf', name)['path'])
            docx = Path(export_service.export(html, 'docx', name)['path'])
            root, widths, ratios = inspect_docx(docx)
            expected = [value/sum(EXPECTED) for value in EXPECTED]
            normalized = lambda value: re.sub(r'\s+', '', value)
            # Content-stream order keeps wrapped cell text together, unlike global XY sorting.
            pdf_text = subprocess.check_output(['pdftotext', '-raw', str(pdf), '-'], text=True)
            xml_text = ''.join(root.itertext())
            # Writer repeats the header and the row's 2/B/I cells at a page seam.
            # Remove only this fixture's known non-description tokens before joining it.
            pdf_content = normalized(pdf_text).replace(
                '项目编号项目评价内容与要求评价结果风险评定值严重程度概率等级风险类别', ''
            ).replace('2BⅠ类', '')
            selected = risks if name == 'long32' else [risks[-1]]
            for text in [r['text'] for r in selected] + ['END_OF_TABLE']:
                assert normalized(text) in pdf_content, 'Missing PDF content: '+text
                assert normalized(text) in normalized(xml_text), 'Missing DOCX content'
            within = len(ratios) == 7 and all(abs(a-b) < .006 for a,b in zip(ratios,expected))
            records.append({'case':name,'docx_widths_twips':widths,
                            'ratios':ratios,'expected_ratios':expected,'widths_ok':within,
                            'selected_risks':len(selected),'all_text_preserved':True})
            if not within: failures.append(name+' columns diverged from JTE template')
        if not all(abs(a-b)<.002 for a,b in zip(records[0]['ratios'],records[1]['ratios'])):
            failures.append('Text length moved columns beyond strict tolerance')
        payload={'converter':subprocess.check_output([export_service.SOFFICE,'--version'],text=True).strip(),
                 'full_report':args.full_report,'cases':records,'failures':failures}
        (args.output_dir/'results.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps(payload,ensure_ascii=False),flush=True)
        assert not failures, '; '.join(failures)
    finally:
        export_service.EXPORT_DIR = original


if __name__ == '__main__': main()

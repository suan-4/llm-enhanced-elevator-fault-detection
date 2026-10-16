"""板端真实 LibreOffice 导出版式回归；仅使用临时目录，不读写业务库。

在板端 backend 目录运行：
    python3 /path/to/export_layout_acceptance.py
需要 PYTHONPATH 指向 backend，及真实 soffice/pdfinfo/pdftotext。
"""
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

from app.services import export_service


def main():
    body = (
        '<div class="paper"><h1>FIRST_SECTION</h1>'
        '<table class="info"><tr><th>Client</th><td colspan="3">Example</td></tr>'
        '<tr><th>Type</th><td>Elevator</td><th>Product</th><td>123</td></tr>'
        '</table></div>'
        '<div class="paper"><h1>SECOND_SECTION</h1><p>Evaluation</p></div>'
        '<div class="paper"><h1>THIRD_SECTION</h1><p>Appendix</p></div>'
    )
    html = export_service.build_html('Layout regression', [], body)
    original_dir = export_service.EXPORT_DIR
    with tempfile.TemporaryDirectory(prefix='elevator_layout_acceptance_') as work:
        export_service.EXPORT_DIR = Path(work) / 'exports'
        try:
            pdf = Path(export_service.export(html, 'pdf', 'layout')['path'])
            docx = Path(export_service.export(html, 'docx', 'layout')['path'])
            info = subprocess.check_output(['pdfinfo', str(pdf)], text=True)
            size = re.search(r'Page size:\s*([\d.]+) x ([\d.]+)', info)
            assert size, info
            width, height = map(float, size.groups())
            assert abs(width - 595.28) < 1 and abs(height - 841.89) < 1, (
                f'PDF must be A4, got {width} x {height} pt')
            text = subprocess.check_output(['pdftotext', str(pdf), '-'], text=True)
            pages = [p for p in text.split('\f') if p.strip()]
            assert len(pages) == 3, f'Three document sections must start separately, got {len(pages)} pages'
            for index, marker in enumerate(('FIRST_SECTION', 'SECOND_SECTION', 'THIRD_SECTION')):
                assert marker in pages[index], f'{marker} not on its own section page'
            with ZipFile(docx) as archive:
                root = ET.fromstring(archive.read('word/document.xml'))
            ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            sizes = root.findall('.//w:sectPr/w:pgSz', ns)
            assert sizes, 'DOCX has no page geometry'
            for item in sizes:
                w = int(item.get('{' + ns['w'] + '}w'))
                h = int(item.get('{' + ns['w'] + '}h'))
                assert abs(w - 11906) <= 2 and abs(h - 16838) <= 2, (
                    f'DOCX must be A4, got {w} x {h} twips')
            print('PASS: real PDF and DOCX use A4; all three PDF sections start on separate pages')
        finally:
            export_service.EXPORT_DIR = original_dir


if __name__ == '__main__':
    main()

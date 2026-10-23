"""Writer needs explicit column attributes, not the browser's header CSS."""
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import export_service


class Columns(HTMLParser):
    def __init__(self):
        super().__init__()
        self.widths = []

    def handle_starttag(self, tag, attrs):
        if tag == 'col':
            self.widths.append(dict(attrs).get('width'))


class ExportColumnsTests(unittest.TestCase):
    def test_evaluation_has_template_column_proportions(self):
        for result in ('符合', '不符合（' + '控制柜散热通道堵塞；' * 150 + '）'):
            with self.subTest(long=len(result) > 10):
                body = '<table class="evaluation"><thead><tr><th>项目编号</th></tr></thead>' \
                       '<tbody><tr><td>' + result + '</td></tr></tbody></table>'
                html = export_service.build_html('Report', [], body)
                parsed = Columns()
                parsed.feed(html)
                # Retained JTE template tblGrid: 544/1328/4478/995/624/624/629.
                expected = ['544*', '1328*', '4478*', '995*', '624*', '624*', '629*']
                self.assertEqual(parsed.widths, expected)
                self.assertIn(result, html)

    def test_existing_grid_is_preserved_and_other_tables_are_untouched(self):
        body = '<table class="evaluation"><colgroup><col width="100%"></colgroup><tr><td>x</td></tr></table>'
        html = export_service.build_html('Report', [], body)
        self.assertEqual(html.count('<colgroup>'), 1)
        self.assertIn('<col width="100%">', html)
        plain = export_service.build_html('Report', [], '<table><tr><td>附页</td></tr></table>')
        self.assertNotIn('<colgroup>', plain)


if __name__ == '__main__':
    unittest.main()

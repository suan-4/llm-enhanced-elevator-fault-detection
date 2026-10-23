"""Native template + report-bound export regression, isolated SQLite/files only."""
import asyncio
import hashlib
import json
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
from xml.dom import minidom

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from tests._tempdb import TempDB
from tests.test_report_workflow import FORM, _items
from app import db
from app.main import app
from app.services import auth_service, export_service, report_workflow as wf


class NativeExportTests(unittest.TestCase):
    def setUp(self):
        self.tempdb = TempDB()
        self.tempdb.__enter__()
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.dirpatch = patch.object(export_service, "EXPORT_DIR", self.directory)
        self.dirpatch.start()
        self.actor, session = auth_service.init_system(
            display_name="验收", username="nativeexport", password="Testing2026")
        self.headers = {"Authorization": "Bearer " + session["token"]}
        self.client = TestClient(app)
        draft = wf.create_draft(actor=self.actor)
        wf.save_content(draft["id"], form=FORM, items=_items(unfit=1), actor=self.actor)
        self.report = asyncio.run(wf.generate(draft["id"], actor=self.actor))

    def tearDown(self):
        self.client.close()
        self.dirpatch.stop()
        self.tmp.cleanup()
        self.tempdb.__exit__()

    def payload(self, **overrides):
        return {"fmt": "docx", "report_id": self.report["id"],
                "version": self.report["version"],
                "result_digest": self.report["provenance"].get("result_digest", ""),
                **overrides}

    def post(self, **overrides):
        return self.client.post("/api/report/export", headers=self.headers,
                                json=self.payload(**overrides))

    def test_missing_binding_and_client_html_rejected(self):
        r = self.client.post("/api/report/export", headers=self.headers,
                             json={"fmt": "docx", "body_html": "<p>forged</p>"})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.post(body_html="<p>forged</p>").status_code, 422)

    def test_split_numeric_fields_keep_units_and_missing_positions(self):
        from copy import deepcopy
        from app.services import native_template as native
        report = deepcopy(self.report)
        report['form'].update(floors='10', stops='', doors='12', ratedLoad='1000', ratedSpeed='1.75')
        report['form'].pop('floorsStopsDoors', None)
        original = deepcopy(report['form'])
        with ZipFile(BytesIO(native.build_docx(report))) as archive:
            body = minidom.parseString(archive.read('word/document.xml')).getElementsByTagName('w:body')[0]
        rows = native.children(native.children(body, 'w:tbl')[1], 'w:tr')
        self.assertEqual(native.text(native.children(rows[10], 'w:tc')[2]), '10 层　/ 站　12 门')
        self.assertEqual(native.text(native.children(rows[9], 'w:tc')[2]), '1000 kg')
        self.assertEqual(native.text(native.children(rows[9], 'w:tc')[4]), '1.75 m/s')
        self.assertEqual(report['form'], original)

    def test_native_docx_archives_and_records_hash_without_converter(self):
        r = self.post()
        self.assertEqual(r.status_code, 200, r.text)
        info = r.json()
        p = Path(info["path"])
        self.assertEqual(info["sha256"], hashlib.sha256(p.read_bytes()).hexdigest())
        self.assertEqual(info["result_digest"], self.report["provenance"]["result_digest"])
        after = wf.get_report(self.report["id"])
        self.assertEqual(after["status"], "filed")
        self.assertEqual(after["files"][0]["sha256"], info["sha256"])
        self.assertTrue(after["exported_at"])
        with db.get_conn() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM audit_log WHERE event='report_export'").fetchone()[0], 1)
        with ZipFile(p) as z:
            xml = z.read("word/document.xml").decode()
        self.assertIn("佛山某公司", xml)
        self.assertIn("44786091", xml)
        self.assertIn("限速器运行中有异响", xml)
        self.assertNotIn("XXX", xml)
        self.assertNotIn("温湿度计、万用表", xml)
        self.assertNotIn("技术服务合同/协议", xml)
        self.assertNotIn("forged", xml)
        doc = minidom.parseString(xml)
        text = lambda n: "".join(t.firstChild.data if t.firstChild else "" for t in n.getElementsByTagName("w:t"))
        body = doc.getElementsByTagName("w:body")[0]
        first = next(n for n in body.childNodes if n.nodeType == n.ELEMENT_NODE)
        self.assertIn("质量体系文件编号", text(first))
        first_table = doc.getElementsByTagName("w:tbl")[0]
        self.assertIn("委托单位名称", text(first_table))
        self.assertIn("曳引驱动乘客电梯", text(first_table))
        body_table = doc.getElementsByTagName("w:tbl")[1]
        self.assertIn("综合安全状况等级：四级", text(body_table))
        self.assertIn("综合安全状况得分 0", text(body_table))

    def test_cover_notice_logo_and_continuous_page_numbers_are_restored(self):
        from app.services import native_template
        with ZipFile(BytesIO(native_template.build_docx(self.report))) as out:
            doc = minidom.parseString(out.read('word/document.xml'))
        body = doc.getElementsByTagName('w:body')[0]
        elements = [n for n in body.childNodes if n.nodeType == n.ELEMENT_NODE]
        tables = native_template.children(body, 'w:tbl')
        cover_text = native_template.text(tables[0])
        for expected in ('佛山某公司', '曳引驱动乘客电梯', '44786091', '2026-10-13'):
            self.assertIn(expected, cover_text)
        notice = next(n for n in elements if native_template.text(n).strip() == '注意事项')
        self.assertLess(elements.index(tables[0]), elements.index(notice))
        self.assertLess(elements.index(notice), elements.index(tables[1]))
        self.assertIn('本报告由计算机生成，涂改无效', native_template.text(body))
        self.assertTrue(doc.getElementsByTagName('a:blip'), 'original cover logo must remain referenced')
        for row in native_template.children(tables[0], 'w:tr'):
            slot = native_template.children(row, 'w:tc')[1]
            self.assertTrue(slot.getElementsByTagName('w:u'), 'cover fill-in underline must remain')
        for section in doc.getElementsByTagName('w:sectPr')[1:]:
            for num in section.getElementsByTagName('w:pgNumType'):
                self.assertFalse(num.hasAttribute('w:start'), 'page numbers must not restart in each section')

    def test_empty_frontmatter_section_end_cannot_create_a_libreoffice_blank_page(self):
        from app.services import native_template
        with ZipFile(BytesIO(native_template.build_docx(self.report))) as out:
            doc = minidom.parseString(out.read('word/document.xml'))
        paragraphs = doc.getElementsByTagName('w:p')
        endings = [p for p in paragraphs if native_template.children(p, 'w:pPr')
                   and native_template.children(native_template.children(p, 'w:pPr')[0], 'w:sectPr')]
        self.assertEqual(len(endings), 2)
        self.assertEqual([native_template.text(p).strip() for p in endings],
                         ['广东省特种设备检测研究院', '联系电话：'])
        for paragraph in endings:
            self.assertTrue(native_template.text(paragraph).strip(),
                            'section break must end on real content, not a spillable empty paragraph')

    def test_repeat_export_keeps_both_files(self):
        first, second = self.post(), self.post()
        self.assertEqual((first.status_code, second.status_code), (200, 200))
        self.assertNotEqual(first.json()["path"], second.json()["path"])
        self.assertEqual(len(wf.get_report(self.report["id"])["files"]), 2)
        self.assertEqual(Path(first.json()["path"]).read_bytes(), Path(second.json()["path"]).read_bytes())

    def test_unknown_stale_void_and_untrusted_digest_rejected(self):
        self.assertEqual(self.post(report_id="123456789").status_code, 404)
        self.assertEqual(self.post(version=999).status_code, 409)
        self.assertEqual(self.post(result_digest="f"*64).status_code, 409)
        wf.void_report(self.report["id"], reason="验收", actor=self.actor)
        self.assertEqual(self.post().status_code, 409)
        self.assertFalse(list(self.directory.glob("*.docx")))

    def test_changed_input_rejected(self):
        wf.save_content(self.report["id"], form={**FORM, "productNo": "changed"},
                        items=_items(unfit=1), actor=self.actor)
        self.assertEqual(self.post().status_code, 409)

    def test_regeneration_invalidates_same_input_snapshot(self):
        before = self.report["provenance"].get("result_digest")
        self.assertTrue(before, "generated report must identify its actual result snapshot")
        regenerated = asyncio.run(wf.generate(self.report["id"], actor=self.actor))
        self.assertNotEqual(before, regenerated["provenance"]["result_digest"])
        self.assertEqual(self.post().status_code, 409)

    def test_audit_failure_rolls_back_archive_and_removes_owned_file(self):
        from app.services import audit_service
        with patch.object(audit_service, "record", side_effect=RuntimeError("injected audit failure")):
            r = self.post()
        self.assertEqual(r.status_code, 500)
        self.assertEqual(wf.get_report(self.report["id"])["status"], "generated")
        self.assertFalse(list(self.directory.glob("*.docx")))

    def test_pdf_failure_does_not_archive_or_publish(self):
        with patch.object(export_service, "SOFFICE", str(self.directory/"not-installed")):
            r = self.post(fmt="pdf")
        self.assertEqual(r.status_code, 500)
        self.assertEqual(wf.get_report(self.report["id"])["files"], [])
        self.assertFalse(list(self.directory.glob("*.pdf")))

    def test_no_login_cannot_export(self):
        r = self.client.post("/api/report/export", json=self.payload())
        self.assertEqual(r.status_code, 401)

    def test_concurrent_void_after_render_cannot_be_archived(self):
        from app.services import native_template
        build = native_template.build_docx
        def interrupted(report):
            content = build(report)
            wf.void_report(report["id"], reason="转换期间作废", actor=self.actor)
            return content
        with patch.object(native_template, "build_docx", interrupted):
            r = self.post()
        self.assertEqual(r.status_code, 409)
        self.assertEqual(wf.get_report(self.report["id"])["status"], "void")
        self.assertFalse(list(self.directory.glob("*.docx")))

    def test_template_geometry_equations_and_opaque_parts_preserved(self):
        from app.services import native_template
        response = self.post()
        self.assertEqual(response.status_code, 200, response.text)
        with ZipFile(native_template.TEMPLATE) as source, ZipFile(response.json()["path"]) as out:
            editable = {"word/document.xml", "word/settings.xml", "word/header1.xml", "word/header3.xml",
                        "word/footer2.xml", "word/footer5.xml"}
            self.assertEqual(source.namelist(), out.namelist())
            for name in source.namelist():
                if name not in editable:
                    self.assertEqual(source.read(name), out.read(name), name)
            before = minidom.parseString(source.read("word/document.xml"))
            after = minidom.parseString(out.read("word/document.xml"))
        source_tables = native_template.children(before.getElementsByTagName("w:body")[0], "w:tbl")
        out_tables = native_template.children(after.getElementsByTagName("w:body")[0], "w:tbl")
        self.assertEqual(len(out_tables), 11)
        for a, b in zip(source_tables[:11], out_tables):
            self.assertEqual(a.getElementsByTagName("w:tblGrid")[0].toxml(),
                             b.getElementsByTagName("w:tblGrid")[0].toxml())
        self.assertEqual([n.toxml() for n in before.getElementsByTagName("m:oMath")],
                         [n.toxml() for n in after.getElementsByTagName("m:oMath")])

    def test_total_pages_are_dynamic_not_sample_page_count(self):
        r = self.post()
        self.assertEqual(r.status_code, 200, r.text)
        with ZipFile(r.json()["path"]) as z:
            for name in ("word/footer2.xml", "word/footer5.xml"):
                footer = z.read(name).decode()
                self.assertIn("NUMPAGES", footer, "样例的共13/14页不能进入可变长度报告")
            doc = minidom.parseString(z.read("word/document.xml"))
            section = doc.getElementsByTagName("w:sectPr")[-1]
            refs = {n.getAttribute("w:type"): n.getAttribute("r:id")
                    for n in section.getElementsByTagName("w:footerReference")}
            self.assertEqual(refs["default"], "rId11", "正文须引用有动态页码的页脚")

    def test_recovery_removes_uncommitted_owned_file_but_keeps_registered_file(self):
        from app.services.report_export import recover_pending
        res = self.post().json()
        pending = self.directory / ".pending"
        orphan = self.directory / "orphan.docx"
        orphan.write_bytes(b"orphan")
        for name, path, digest in (
            ("registered", Path(res["path"]), res["sha256"]),
            ("orphan", orphan, hashlib.sha256(b"orphan").hexdigest()),
        ):
            (pending / (name + ".json")).write_text(json.dumps({
                "db": str(db.DB_PATH.resolve()), "path": str(path.resolve()),
                "sha256": digest, "report_id": self.report["id"],
                "device": path.stat().st_dev, "inode": path.stat().st_ino,
            }), encoding="utf-8")
        recover_pending()
        self.assertTrue(Path(res["path"]).exists())
        self.assertFalse(orphan.exists())
        self.assertFalse(list(pending.glob("*.json")))

    def test_recovery_cleans_inactive_staging_but_not_another_database(self):
        from app.services.report_export import recover_pending
        pending = self.directory / ".pending"
        pending.mkdir()
        for key, database in (("a", str(db.DB_PATH.resolve())), ("b", "/another/database")):
            work = pending / (key*32 + "-staging")
            work.mkdir()
            (work/"owner.json").write_text(json.dumps({"db": database}), encoding="utf-8")
            (work/"report.docx").write_bytes(b"interrupted-conversion")
        recover_pending()
        self.assertFalse((pending/("a"*32+"-staging")).exists())
        self.assertTrue((pending/("b"*32+"-staging")/"report.docx").exists())

    def test_recovery_leaves_an_active_conversion_alone(self):
        from app.services.report_export import recover_pending, work_lock
        work = self.directory / ".pending" / ("c"*32+"-staging")
        work.mkdir(parents=True)
        (work/"owner.json").write_text(json.dumps({"db": str(db.DB_PATH.resolve())}))
        with work_lock(work) as acquired:
            self.assertTrue(acquired)
            recover_pending()
            self.assertTrue(work.exists())
        recover_pending()
        self.assertFalse(work.exists())

    def test_missing_or_modified_template_never_falls_back_to_html(self):
        from app.services import native_template
        with patch.object(native_template, "TEMPLATE", self.directory / "missing.docx"):
            self.assertEqual(self.post().status_code, 500)
        bad = self.directory / "bad-template.docx"
        bad.write_bytes(b"not the verified template")
        with patch.object(native_template, "TEMPLATE", bad):
            self.assertEqual(self.post().status_code, 500)
        self.assertEqual(wf.get_report(self.report["id"])["files"], [])


if __name__ == "__main__":
    unittest.main()

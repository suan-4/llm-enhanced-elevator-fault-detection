"""Native template + report-bound export regression, isolated SQLite/files only."""
import asyncio
import hashlib
import json
import sys
import tempfile
import unittest
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
        self.assertEqual(text(first), "在用曳引驱动电梯安全评估报告")
        first_table = doc.getElementsByTagName("w:tbl")[0]
        self.assertIn("委托单位名称", text(first_table))
        self.assertIn("综合安全状况等级：四级", text(first_table))
        self.assertIn("综合安全状况得分 0", text(first_table))

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
        self.assertEqual(len(out_tables), 10)
        for a, b in zip(source_tables[1:11], out_tables):
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

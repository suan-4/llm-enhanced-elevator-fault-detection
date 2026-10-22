"""Report-bound HTTP gate with disposable SQLite and real native DOCX output."""
import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient
from tests._tempdb import TempDB
from app import db
from app.main import app
from app.services import auth_service, export_service, report_workflow as wf


def probe():
    with TempDB(), tempfile.TemporaryDirectory() as tmp, \
            patch.object(export_service, "EXPORT_DIR", Path(tmp)), TestClient(app) as client:
        actor, session = auth_service.init_system(
            display_name="导出契约验收", username="exportprobe", password="Probe2026")
        headers = {"Authorization": "Bearer " + session["token"]}
        form = dict(clientName="验收委托", userName="验收使用",
                    deviceCategory="曳引驱动电梯", productNo="PROBE-ONLY")
        items = [
            {"no": i["no"], "result": "fit", "reasons": [], "other_text": ""}
            for i in json.loads(wf.ITEMS_PATH.read_text(encoding="utf-8"))["items"]
        ]
        report = wf.create_draft(actor=actor)
        wf.save_content(report["id"], form=form, items=items, actor=actor)
        report = asyncio.run(wf.generate(report["id"], actor=actor))
        cases = []

        def request(name, extra, should_reject):
            count = len(list(Path(tmp).glob("*.docx")))
            response = client.post("/api/report/export", headers=headers, json={
                "fmt": "docx", "version": report["version"],
                "result_digest": report["provenance"]["result_digest"], **extra,
            })
            reached = len(list(Path(tmp).glob("*.docx"))) > count
            cases.append({
                "case": name, "expected": "reject_before_conversion" if should_reject else "conversion_success",
                "http_status": response.status_code, "converter_called": reached,
                "file_published": reached,
                "passed": response.status_code >= 400 and not reached if should_reject else response.status_code == 200,
            })

        request("missing_report_id", {}, True)
        request("unknown_report_id", {"report_id": "999999999"}, True)
        request("generated_report", {"report_id": report["id"], "version": report["version"]}, False)
        request("caller_html_rejected", {"report_id": report["id"], "body_html": "<p>forged</p>"}, True)
        after = wf.get_report(report["id"])
        with db.get_conn() as conn:
            audits = conn.execute("SELECT COUNT(*) FROM audit_log WHERE event='report_export'").fetchone()[0]
        registration = {
            "status": after["status"], "exported_at": after["exported_at"],
            "files": len(after["files"]), "export_audits": audits,
        }
        registration["passed"] = (
            registration["status"] == "filed" and bool(registration["exported_at"])
            and registration["files"] > 0 and audits > 0
        )
        # Independent drafts keep these cases valid after a future exporter archives its input.
        stale = wf.create_draft(actor=actor)
        wf.save_content(stale["id"], form=form, items=items, actor=actor)
        stale = asyncio.run(wf.generate(stale["id"], actor=actor))
        wf.save_content(stale["id"], form={**form, "productNo": "CHANGED"},
                        items=items, version=stale["version"], actor=actor)
        request("modified_after_generation", {"report_id": stale["id"], "version": stale["version"],
                "result_digest": stale["provenance"]["result_digest"]}, True)
        voided = wf.void_report(report["id"], reason="契约验收作废", actor=actor)
        request("void_report", {"report_id": voided["id"], "version": voided["version"]}, True)
        return {
            "scope": "isolated SQLite + real HTTP routing + native DOCX output; PDF/layout tested separately",
            "cases": cases, "registration": registration,
            "contract_passed": all(c["passed"] for c in cases) and registration["passed"],
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = probe()
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)
    raise SystemExit(0 if result["contract_passed"] else 1)

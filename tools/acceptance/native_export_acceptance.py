"""Run only in an isolated release: real full-report Word + PDF conversion."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app import db
from app.services import auth_service, expert_risk, report_workflow as wf, report_export, export_service
from app.repo import ids
from tests.test_report_workflow import FORM, _items


def run():
    if not str(ROOT).startswith("/userdata/releases/20261020-native-export-"):
        raise RuntimeError("This runner is restricted to the isolated board candidate")
    run_id = os.environ.get("EXPORT_ACCEPTANCE_RUN", "initial")
    if not run_id.isalnum():
        raise ValueError("Run label must be alphanumeric")
    qa = ROOT / "qa" / run_id
    qa.mkdir(exist_ok=True)
    db.DB_PATH = qa / "native-export.db"
    export_service.EXPORT_DIR = qa / "exports"
    if db.DB_PATH.exists():
        raise RuntimeError("Use a new database for each acceptance run")
    db.init_db()
    ids.configure(31, db.max_business_id())
    actor, _ = auth_service.init_system(display_name="导出验收", username="acceptance", password="Acceptance2026!")
    results = []
    for label, n in (("all-fit", 0), ("multiple-risks", 3), ("long-32-risks", 32)):
        items = _items(unfit=n)
        if n == 3:
            for item in items:
                if item["result"] == "unfit":
                    item["reasons"] = [o["text"] for o in expert_risk.options(item["no"])[:3]]
        form = {**FORM, "clientName": "模板导出验收（非正式检验）",
                "productNo": label, "instruments": "/", "basis": "/"}
        draft = wf.create_draft(actor=actor)
        wf.save_content(draft["id"], form=form, items=items, actor=actor)
        report = asyncio.run(wf.generate(draft["id"], actor=actor))
        data = {"scenario": label, "report_id": report["id"], "outputs": []}
        for fmt in ("docx", "pdf"):
            info = report_export.export_report(
                report_id=report["id"], version=report["version"],
                result_digest=report["provenance"]["result_digest"],
                fmt=fmt, filename=label, actor=actor)
            if fmt == "pdf":
                # -layout interleaves neighbouring table columns line-by-line,
                # so a complete sentence is no longer contiguous. Raw reading
                # order preserves cell text; independent page QA checks layout.
                content = subprocess.check_output(["pdftotext", "-raw", info["path"], "-"]).decode("utf-8")
                for item in items:
                    assert item["no"] in content, item["no"]
                assert label in content
                assert "XXX" not in content
                for risk in report["risks"].values():
                    for detail in risk.get("selected_risks", []):
                        # Ignore wrapping/whitespace only; never drop risk/measure text.
                        normalized = "".join(content.split())
                        assert "".join(detail["text"].split()) in normalized, detail["text"]
                        assert "".join(detail["measure"].split()) in normalized, detail["measure"]
            data["outputs"].append(info)
        assert len(wf.get_report(report["id"])["files"]) == 2
        results.append(data)
        print(json.dumps(data, ensure_ascii=False), flush=True)
    (qa / "native-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return results


if __name__ == "__main__":
    run()

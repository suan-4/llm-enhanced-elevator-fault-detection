"""Run against an isolated candidate, never the formal DB.

Launch with PYTHONPATH pointing at the verified offline tokenizers runtime.
Conversion of the short fixture proves publication only, not JTE template fidelity.
"""
import asyncio
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


def formal_snapshot():
    path = Path("/userdata/elevator/elevator.db")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT * FROM report ORDER BY id").fetchall()
        return {
            "report_count": len(rows),
            "reports_sha256": hashlib.sha256(
                json.dumps(rows, ensure_ascii=False, default=str).encode()).hexdigest(),
            "db_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    finally:
        conn.close()


async def main():
    root = Path(sys.argv[1]).resolve()
    if root.parent != Path("/userdata/releases") or not root.name.startswith("20261020-regression-"):
        raise SystemExit("Only the dedicated regression candidate is allowed")
    work = root / "acceptance"
    work.mkdir(exist_ok=False)
    os.chdir(root / "backend")
    sys.path.insert(0, str(root / "backend"))
    assets = Path("/userdata/releases/20261018-prompt-guard-01/backend/data/tokenizers/qwen3.5-4b")
    os.environ.update(
        SQLITE_PATH=str(work / "test.db"), EXPORT_DIR=str(work / "exports"),
        BACKUP_DIR=str(work / "backups"), RECOVERY_KEY_PATH=str(work / "missing.key"),
        RKLLM_TOKENIZER_PATH=str(assets / "tokenizer.json"),
        RKLLM_CALIBRATION_PATH=str(assets / "calibration.json"),
        RKLLM_SERVER_URL="http://127.0.0.1:8080/v1/chat/completions",
    )
    result = {"before": formal_snapshot(), "candidate": root.name}
    from app import db
    from app.services import auth_service, expert_risk, export_service, report_workflow as wf
    from app.services.llm_service import llm_service
    try:
        assert db.DB_PATH == work / "test.db"
        result["regressions"] = {}
        for name in ("test_save_consistency.py", "test_export_collision.py"):
            run = subprocess.run([sys.executable, "tests/" + name], capture_output=True, text=True)
            result["regressions"][name] = {"exit_code": run.returncode, "log": run.stdout + run.stderr}
            assert run.returncode == 0, name
        db.init_db()
        actor, _ = auth_service.init_system(
            display_name="隔离验收", username="regression", password="Regression2026")
        report = wf.create_draft(actor=actor)
        items = [{"no": no, "result": "fit", "reasons": [], "other_text": ""}
                 for no in expert_risk.knowledge()["items"]]
        next(i for i in items if i["no"] == "16.1").update(
            result="unfit", other_text="控制柜的散热风道被灰尘堵住，电气元件温度升高。")
        form = dict(clientName="隔离验收委托单位", userName="隔离验收使用单位",
                    deviceCategory="曳引驱动电梯", productNo="REGRESSION-ONLY")
        saved = wf.save_content(report["id"], form=form, items=items,
                                version=report["version"], actor=actor)
        try:
            wf.save_content(report["id"], form={"clientName": "过期页面"},
                            items=[], version=report["version"], actor=actor)
            raise AssertionError("stale save accepted")
        except wf.VersionConflict:
            result["stale_save_rejected"] = True
        try:
            generated = await wf.generate(report["id"], use_llm=True, actor=actor)
            result["generation"] = {
                "status": generated["status"], "score": generated["score"], "grade": generated["grade"],
                "risk_16_1": generated["risks"].get("16.1"),
                "llm_status": generated["provenance"]["llm_status"],
                "llm_error_code": generated["provenance"]["llm_error_code"],
                "performance": generated["performance"],
            }
        except Exception as exc:
            result["generation"] = {"error_type": type(exc).__name__, "message": str(exc)}
        # Real LibreOffice conversion; freeze only the naming clock to exercise
        # repeated exports deterministically. This is NOT a template fidelity test.
        exports = []
        with patch.object(export_service, "datetime") as clock:
            clock.now.return_value = datetime(2026, 10, 20, 12, 0, 0)
            for n, fmt in enumerate(("pdf", "pdf", "pdf", "docx"), 1):
                html = export_service.build_html(
                    "Regression", [], f"<h1>隔离导出验收 {n}</h1><p>REGRESSION-{n}</p>")
                info = export_service.export(html, fmt, "regression")
                exports.append({**info, "sha256": hashlib.sha256(Path(info["path"]).read_bytes()).hexdigest()})
        assert len({e["path"] for e in exports}) == 4
        assert len({e["sha256"] for e in exports[:3]}) == 3
        result["exports"] = exports
        result["saved_version"] = saved["version"]
    finally:
        await llm_service.close()
        result["after"] = formal_snapshot()
        result["formal_unchanged"] = result["before"] == result["after"]
        (work / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    assert result["formal_unchanged"]
    assert result.get("generation", {}).get("llm_status") == "success", "model acceptance failed"
    assert result["generation"]["risk_16_1"]["category"] == "Ⅰ类"
    assert result["generation"]["score"] == 0


if __name__ == "__main__":
    asyncio.run(main())

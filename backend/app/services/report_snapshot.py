"""Stable content fingerprint; export timestamps/files/status do not change it."""
import hashlib
import json


def result_digest(report):
    keys = ("id", "report_no", "version", "form", "items", "risks", "score",
            "grade", "narrative", "generated_at", "catalog_version", "template_version")
    value = {k: report.get(k) for k in keys}
    value["id"] = str(value["id"])
    provenance = report.get("provenance") or {}
    value["provenance"] = {k: provenance.get(k) for k in (
        "generation_id", "input_digest", "risk_catalog_version", "score_basis",
        "assessment_complete", "assessment_issues", "overview_policy")}
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

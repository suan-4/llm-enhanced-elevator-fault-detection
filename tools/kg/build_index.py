#!/usr/bin/env python3
"""Build the runtime read model for the v2 knowledge graph (SQLite + FTS5).

Input : v2_1000paths/data/{fault_paths,path_steps,states,components,...}.csv
Output: backend/data/kg_v2.sqlite

No third-party dependency. Run from repo root:
    python tools/kg/build_index.py
"""
from __future__ import annotations
import argparse, csv, json, sqlite3, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA = ROOT / "v2_1000paths" / "data"
DEFAULT_OUT = ROOT / "backend" / "data" / "kg_v2.sqlite"


def rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def as_json_list(value: str) -> list[str]:
    try:
        data = json.loads(value or "[]")
        return [str(x) for x in data] if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()
    data_dir, out = Path(args.data_dir), Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    started = time.time()
    conn = sqlite3.connect(out)
    cur = conn.cursor()
    cur.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE path(
            path_id TEXT PRIMARY KEY, system_id TEXT, system_name TEXT,
            component_id TEXT, component_name TEXT,
            item_id TEXT, item_name TEXT, action_id TEXT, corrective_action TEXT,
            inspection_method TEXT, acceptance_basis TEXT, verification_after_action TEXT,
            risk_name TEXT, clause_id TEXT, phenomenon_name TEXT, source_refs TEXT,
            path_summary TEXT, mechanism_steps TEXT, trigger_condition TEXT,
            barrier_condition TEXT, confidence REAL, verified TEXT, evidence_class TEXT,
            state_ids TEXT, state_names TEXT);
        CREATE TABLE path_state(path_id TEXT, state_id TEXT, ordinal INTEGER, state_name TEXT);
        CREATE TABLE state(state_id TEXT PRIMARY KEY, name TEXT, description TEXT);
        CREATE TABLE component(component_id TEXT PRIMARY KEY, name TEXT, system_id TEXT, description TEXT);
        CREATE TABLE inspection_item(item_id TEXT PRIMARY KEY, name TEXT, method TEXT, acceptance_basis TEXT);
        CREATE TABLE action(action_id TEXT PRIMARY KEY, name TEXT, action_type TEXT, verification TEXT);
        CREATE TABLE risk(risk_id TEXT PRIMARY KEY, name TEXT, severity TEXT, risk_level TEXT);
        CREATE TABLE clause(clause_id TEXT PRIMARY KEY, standard_code TEXT, clause_no TEXT, title TEXT, legal_status TEXT);
        CREATE VIRTUAL TABLE path_fts USING fts5(
            path_id UNINDEXED, text, tokenize='unicode61');
    """)

    for csv_name in ("states", "components", "inspection_items", "actions", "risks", "clauses"):
        if not (data_dir / f"{csv_name}.csv").exists():
            continue
        for r in rows(data_dir / f"{csv_name}.csv"):
            if csv_name == "states":
                cur.execute("INSERT OR REPLACE INTO state VALUES(?,?,?)",
                            (r.get("state_id"), r.get("state_name") or r.get("name"), r.get("description")))
            elif csv_name == "components":
                cur.execute("INSERT OR REPLACE INTO component VALUES(?,?,?,?)",
                            (r.get("component_id"), r.get("component_name") or r.get("name"),
                             r.get("system_id"), r.get("description")))
            elif csv_name == "inspection_items":
                cur.execute("INSERT OR REPLACE INTO inspection_item VALUES(?,?,?,?)",
                            (r.get("item_id"), r.get("item_name") or r.get("name"),
                             r.get("method"), r.get("acceptance_basis")))
            elif csv_name == "actions":
                cur.execute("INSERT OR REPLACE INTO action VALUES(?,?,?,?)",
                            (r.get("action_id"), r.get("action_name") or r.get("name"),
                             r.get("action_type"), r.get("verification_after_action")))
            elif csv_name == "risks":
                cur.execute("INSERT OR REPLACE INTO risk VALUES(?,?,?,?)",
                            (r.get("risk_id"), r.get("risk_name") or r.get("name"),
                             r.get("severity"), r.get("risk_level")))
            elif csv_name == "clauses":
                cur.execute("INSERT OR REPLACE INTO clause VALUES(?,?,?,?,?)",
                            (r.get("clause_id"), r.get("standard_code"), r.get("clause_no"),
                             r.get("title") or r.get("name"), r.get("legal_status")))

    paths = rows(data_dir / "fault_paths.csv")
    for r in paths:
        state_ids = as_json_list(r.get("state_ids", ""))
        state_names = as_json_list(r.get("state_names", ""))
        cur.execute("INSERT OR REPLACE INTO path VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            r.get("path_id"), r.get("system_id"), r.get("system_name"),
            r.get("component_id"), r.get("component_name"),
            r.get("item_id"), r.get("item_name"), r.get("action_id"), r.get("corrective_action"),
            r.get("inspection_method"), r.get("acceptance_basis"), r.get("verification_after_action"),
            r.get("risk_name"), r.get("clause_id"), r.get("phenomenon_name"), r.get("source_refs"),
            r.get("path_summary"), r.get("mechanism_steps"), r.get("trigger_condition"),
            r.get("barrier_condition"), float(r.get("confidence") or 0), r.get("verified"),
            r.get("evidence_class"), json.dumps(state_ids, ensure_ascii=False),
            json.dumps(state_names, ensure_ascii=False)))
        for i, sid in enumerate(state_ids):
            name = state_names[i] if i < len(state_names) else ""
            cur.execute("INSERT INTO path_state VALUES(?,?,?,?)", (r.get("path_id"), sid, i, name))
        fts = " ".join(filter(None, [r.get("path_summary"), " ".join(state_names),
                                     r.get("mechanism_steps", ""), r.get("item_name"),
                                     r.get("component_name"), r.get("risk_name"),
                                     r.get("corrective_action"), r.get("inspection_method")]))
        cur.execute("INSERT INTO path_fts(path_id, text) VALUES(?,?)", (r.get("path_id"), fts))

    cur.executescript("""
        CREATE INDEX idx_path_component ON path(component_id);
        CREATE INDEX idx_path_system ON path(system_id);
        CREATE INDEX idx_path_state ON path_state(state_id);
        CREATE INDEX idx_path_item ON path(item_id);
    """)
    meta = {
        "kg_version": "v2_1000paths",
        "source_dir": str(data_dir),
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "paths": len(paths),
    }
    for k, v in meta.items():
        cur.execute("INSERT INTO meta VALUES(?,?)", (k, str(v)))
    conn.commit()
    conn.close()
    print(json.dumps({**meta, "db": str(out), "elapsed_s": round(time.time() - started, 2)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

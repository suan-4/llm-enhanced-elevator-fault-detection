"""v0（旧 4 张表）→ v1（基础版 5 张表）。

要点（每条都有对应测试）：
1. 账号搬进 `account`，角色统一成 `inspector`（单角色），主键换成雪花 ID，
   并记住旧 id → 新 id 的映射，供后面挂接。
2. `report_history` 变成 `report`，**并且按创建日期补上报告编号** ——
   不补的话老报告在列表里没有编号，现场对不上纸面件。
3. `form_draft` 变成 `status='draft'` 的报告（没有编号）。
4. 旧表**改名保留**（`*_legacy_日期`）而不是删除，方便回查。
5. 最后把 `user_version` 置 1；重复执行直接跳过（幂等）。
"""
from __future__ import annotations

from typing import Any

from app.config import settings
from app.repo import ids as id_gen
from app.repo.base import day_key, dumps, loads

LEGACY_TABLES = ("users", "sessions", "report_history", "form_draft")
LEGACY_SUFFIX = "legacy_20261013"
TEMPLATE_VERSION = "JTE-09-R02-3.00"

_FIT = {"符合", "合格", "fit", "ok", "true", "1"}
_UNFIT = {"不符合", "不合格", "unfit", "fail", "false", "0"}
_NA = {"无此项", "na", "none", "-"}


def _result_code(value: Any) -> str:
    """把旧版五花八门的取值统一成 fit / unfit / na / ''。"""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "fit" if value else "unfit"
    text = str(value).strip()
    if text in _FIT:
        return "fit"
    if text in _UNFIT:
        return "unfit"
    if text in _NA:
        return "na"
    return ""


def _normalize_item(raw: dict) -> dict:
    reasons = raw.get("reasons") or raw.get("causes") or raw.get("states") or []
    if isinstance(reasons, str):
        reasons = [r for r in reasons.replace(",", "；").split("；") if r]
    return {
        "no": str(raw.get("no") or raw.get("item_no") or raw.get("itemNo") or "").strip(),
        "result": _result_code(raw.get("result")),
        "reasons": [str(r) for r in reasons],
        "other_text": str(raw.get("other_text") or raw.get("other") or raw.get("otherText") or ""),
    }


def _convert_items(raw: Any) -> list[dict]:
    """旧 items_data 有两种形态：dict{编号: 取值} 或 list[字典]，都要认。"""
    data = loads(raw, None)
    if isinstance(data, list):
        return [_normalize_item(x) for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        out = []
        for no, value in data.items():
            if isinstance(value, dict):
                item = _normalize_item(value)
                item["no"] = item["no"] or str(no)
            else:
                item = {"no": str(no), "result": _result_code(value),
                        "reasons": [], "other_text": ""}
            out.append(item)
        return [i for i in out if i["no"]]
    return []


def _counters(items: list[dict], legacy_total: int | None = None) -> dict:
    total = max(len(items), int(legacy_total or 0))
    done = sum(1 for i in items if i["result"])
    return {
        "total": total,
        "done": done,
        "unfit": sum(1 for i in items if i["result"] == "unfit"),
        "missing": max(0, total - done),
    }


def _promote(form: dict) -> dict:
    """抬头里提升为真实列的 6 个字段（与 repo 的 _PROMOTED 一致）。"""
    def pick(*keys: str) -> str:
        for k in keys:
            v = form.get(k)
            if v:
                return str(v)
        return ""

    return {
        "client_name": pick("clientName", "client_name"),
        "user_name": pick("userName", "user_name"),
        "device_category": pick("deviceCategory", "device_category"),
        "product_no": pick("productNo", "product_no"),
        "location": pick("installSite", "location"),
        "assessed_on": pick("assessDate", "assessed_on"),
    }


def _tables(conn: Any) -> set[str]:
    return {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }


def run(conn: Any, *, prefix: str | None = None, suffix: str = LEGACY_SUFFIX) -> dict:
    """执行迁移。调用方负责事务与备份（见 tools/migrate_v1.py）。"""
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version >= 1:
        return {"skipped": True, "version": version}

    prefix = prefix or settings.report_no_prefix
    present = _tables(conn)
    if "users" not in present:
        # 全新库：结构已由 init_db 建好，直接标版本。
        conn.execute("PRAGMA user_version = 1")
        return {"skipped": False, "accounts": 0, "sessions": 0,
                "reports": 0, "drafts": 0, "note": "无旧数据"}

    # ── 1. 账号 ──────────────────────────────────────────
    id_map: dict[int, int] = {}
    for u in conn.execute("SELECT * FROM users ORDER BY id").fetchall():
        new_id = id_gen.next_id()
        id_map[u["id"]] = new_id
        conn.execute(
            "INSERT INTO account (id, username, display_name, employee_no, password_salt,"
            " password_hash, password_algo, role, is_active, must_change_password,"
            " created_at, last_login_at) VALUES (?,?,?,'',?,?,?, 'inspector', ?, 0, ?, ?)",
            (new_id, u["username"], u["display_name"], u["password_salt"], u["password_hash"],
             "pbkdf2_sha256$120000", u["is_active"], u["created_at"], u["last_login_at"]),
        )

    def account_of(user_id: int | None) -> int | None:
        return id_map.get(user_id) if user_id is not None else None

    # ── 2. 会话（顺带把过期的丢掉）────────────────────────
    sessions = 0
    for s in conn.execute("SELECT * FROM sessions").fetchall():
        aid = account_of(s["user_id"])
        if aid is None:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO session (token, account_id, created_at, expires_at,"
            " last_seen_at, origin) VALUES (?,?,?,?,?, 'migrated')",
            (s["token"], aid, s["created_at"], s["expires_at"], s["created_at"]),
        )
        sessions += 1

    # ── 3. 历史记录 → 已生成报告（补编号）──────────────────
    reports = 0
    for h in conn.execute("SELECT * FROM report_history ORDER BY created_at, id").fetchall():
        aid = account_of(h["user_id"])
        if aid is None:
            continue
        day = day_key(h["created_at"])
        seq = _next_seq(conn, day)
        report_no = f"{prefix}-{day}-{seq:03d}"
        items = _convert_items(h["items_data"])
        form = loads(h["form_data"], {}) or {}
        if h["reg"]:
            form.setdefault("registerNo", h["reg"])
        if h["location"]:
            form.setdefault("installSite", h["location"])
        promoted = _promote(form)
        if h["location"] and not promoted["location"]:
            promoted["location"] = h["location"]
        provenance = {
            "legacy_id": h["id"],
            "kg": loads(h["fault_chain"], None),
            "migrated_from": "report_history",
        }
        conn.execute(
            "INSERT INTO report (id, report_no, status, version, created_by, created_at,"
            " updated_at, generated_at, client_name, user_name, device_category, product_no,"
            " location, assessed_on, form_json, items_json, counters_json, risks_json,"
            " files_json, narrative, provenance_json, catalog_version, template_version)"
            " VALUES (?,?, 'generated', 1, ?, ?, ?, ?, ?,?,?,?,?,?, ?,?,?, '{}', '[]', ?, ?, ?, ?)",
            (
                id_gen.next_id(), report_no, aid, h["created_at"], h["created_at"],
                h["created_at"],
                promoted["client_name"], promoted["user_name"], promoted["device_category"],
                promoted["product_no"], promoted["location"], promoted["assessed_on"],
                dumps(form),
                dumps(items),
                dumps(_counters(items, h["items_count"])),
                h["report_text"] or "",
                dumps(provenance),
                TEMPLATE_VERSION, TEMPLATE_VERSION,
            ),
        )
        reports += 1

    # ── 4. 旧草稿 → 草稿报告 ──────────────────────────────
    drafts = 0
    for d in conn.execute("SELECT * FROM form_draft").fetchall():
        aid = account_of(d["user_id"])
        if aid is None:
            continue
        form = loads(d["form_data"], {}) or {}
        items = _convert_items(d["items_data"])
        promoted = _promote(form)
        conn.execute(
            "INSERT INTO report (id, status, version, created_by, created_at, updated_at,"
            " client_name, user_name, device_category, product_no, location, assessed_on,"
            " form_json, items_json, counters_json, provenance_json, template_version)"
            " VALUES (?, 'draft', 1, ?, ?, ?, ?,?,?,?,?,?, ?,?,?, ?, ?)",
            (
                id_gen.next_id(), aid, d["updated_at"], d["updated_at"],
                promoted["client_name"], promoted["user_name"], promoted["device_category"],
                promoted["product_no"], promoted["location"], promoted["assessed_on"],
                dumps(form),
                dumps(items),
                dumps(_counters(items)),
                dumps({"migrated_from": "form_draft"}),
                TEMPLATE_VERSION,
            ),
        )
        drafts += 1

    # ── 5. 旧表改名保留 ───────────────────────────────────
    renamed = []
    for table in LEGACY_TABLES:
        if table in _tables(conn):
            new_name = f"{table}_{suffix}"
            conn.execute(f"ALTER TABLE {table} RENAME TO {new_name}")
            renamed.append(new_name)

    conn.execute("PRAGMA user_version = 1")
    return {"skipped": False, "accounts": len(id_map), "sessions": sessions,
            "reports": reports, "drafts": drafts, "renamed": renamed}


def _next_seq(conn: Any, day: str) -> int:
    """迁移内部用的取号（与 repo.next_seq 同语义，避免跨层依赖）。"""
    conn.execute(
        "INSERT INTO report_no_seq (day, last_seq) VALUES (?, 1)"
        " ON CONFLICT(day) DO UPDATE SET last_seq = last_seq + 1",
        (day,),
    )
    return int(
        conn.execute("SELECT last_seq FROM report_no_seq WHERE day = ?", (day,)).fetchone()[0]
    )

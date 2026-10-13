"""报告作业：草稿 → 生成 → （导出归档）/ 作废 / 复制 / 删除。

一条报告记录贯穿全生命周期（设计 §4.3），所以这里不再有"草稿另存一份"的概念。

分工：
  - 定级与得分：risk_rules（纯公式，大模型不参与）；
  - 叙述文字：模型可用时用模型，不可用时用图谱/规则摘要兜底（PRD 4.3 降级）；
  - 数据存取：repo。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from time import monotonic

from app import db
from app.config import settings
from app.repo import report_repo
from app.repo.base import day_key, now_iso
from app.repo.ids import next_id
from app.services import audit_service, risk_rules
from app.services.llm_service import llm_service

TEMPLATE_VERSION = "JTE-09-R02-3.00"
ITEMS_PATH = Path(__file__).resolve().parent.parent / "data" / "jte_items.json"

# 让模型"写话"，不让它"定数"：编号、风险类别、得分、等级都不许它碰。
NARRATIVE_SYSTEM = (
    "你是电梯安全评估报告的编写助手。请根据给定的评估数据，用简体中文、正式书面语，"
    "写一段「评估概况」说明，3~5 句，概括本次评估的主要发现与结论。"
    "要求：只陈述数据中已有的事实，不得新增、推测或夸大；"
    "不得改动项目编号、风险类别、得分与等级；不要使用 Markdown 标记；"
    "不要逐条罗列，用概括性语言；直接给正文，不要任何前后缀说明。"
)


class VersionConflict(Exception):
    """乐观锁：客户端拿的是旧版本，先刷新再改。"""


def _catalog_version() -> str:
    """条目库版本 = 模板号 + 条目文件哈希前 8 位（启动时现算，不建表）。"""
    try:
        digest = hashlib.sha256(ITEMS_PATH.read_bytes()).hexdigest()[:8]
    except OSError:
        digest = "unknown"
    return f"{TEMPLATE_VERSION}+{digest}"


def public_report(row: dict | None) -> dict | None:
    """对外结构：id 一律字符串（雪花 ID 超出 JS 安全整数）。"""
    if row is None:
        return None
    out = dict(row)
    for key in ("id", "created_by"):
        if out.get(key) is not None:
            out[key] = str(out[key])
    return out


def _promote(form: dict) -> dict:
    """抬头里提升为真实列的 6 个字段（与 repo 的白名单一致）。"""
    def pick(*keys: str) -> str:
        for key in keys:
            value = form.get(key)
            if value:
                return str(value)
        return ""

    return {
        "client_name": pick("clientName", "client_name"),
        "user_name": pick("userName", "user_name"),
        "device_category": pick("deviceCategory", "device_category"),
        "product_no": pick("productNo", "product_no"),
        "location": pick("installSite", "location"),
        "assessed_on": pick("assessDate", "assessed_on"),
    }


def counters_of(items: list[dict]) -> dict:
    total = len(items)
    done = sum(1 for i in items if i.get("result"))
    return {
        "total": total,
        "done": done,
        "unfit": sum(1 for i in items if i.get("result") == "unfit"),
        "missing": max(0, total - done),
    }


# ── 草稿 ────────────────────────────────────────────────
def create_draft(*, actor: dict | None = None, form: dict | None = None) -> dict:
    """新建一份空白评估。form 只在"复制为新建"时才带。"""
    stamp = now_iso()
    report_id = next_id()
    with db.get_conn() as conn:
        report = report_repo.insert_draft(
            conn,
            report_id=report_id,
            created_by=int(actor["id"]) if actor else _first_account_id(conn),
            created_at=stamp,
            updated_at=stamp,
            catalog_version=_catalog_version(),
            template_version=TEMPLATE_VERSION,
        )
        if form:
            report_repo.update_content(
                conn, report_id, form=form, items=[], counters=counters_of([]),
                updated_at=stamp, promote=_promote(form),
            )
            report = report_repo.find_by_id(conn, report_id)
        audit_service.record(conn, "report_create", actor=actor, target=str(report_id))
    return public_report(report)


def _first_account_id(conn) -> int:
    row = conn.execute("SELECT id FROM account ORDER BY created_at LIMIT 1").fetchone()
    if row is None:
        raise ValueError("还没有任何账号，无法创建报告")
    return int(row["id"])


def get_report(report_id: int | str) -> dict | None:
    with db.get_conn() as conn:
        return public_report(report_repo.find_by_id(conn, int(report_id)))


def get_draft(report_id: int | str) -> dict:
    """续录用：直接把 form / items / counters 给前端，不用它自己拼。"""
    report = get_report(report_id)
    if report is None:
        raise LookupError("报告不存在")
    return {
        "id": report["id"],
        "status": report["status"],
        "version": report["version"],
        "form": report["form"],
        "items": report["items"],
        "counters": report["counters"],
    }


def save_content(report_id: int | str, *, form: dict, items: list,
                 version: int | None = None, actor: dict | None = None) -> dict:
    """保存填写内容（防抖自动保存与手动保存都走这里）。"""
    rid = int(report_id)
    stamp = now_iso()
    with db.get_conn() as conn:
        report = report_repo.find_by_id(conn, rid)
        if report is None:
            raise LookupError("报告不存在")
        if report["status"] in ("void", "filed"):
            raise ValueError("已作废或已归档的报告不能修改，请复制为新建")
        if version is not None and int(version) != int(report["version"]):
            raise VersionConflict("这份报告已被修改过，请刷新后再编辑")

        counters = counters_of(items)
        report_repo.update_content(conn, rid, form=form, items=items, counters=counters,
                                   updated_at=stamp, promote=_promote(form))

        # 已生成的报告被改过 → 回落草稿、版本 +1（旧的风险值保留，便于对比改了什么）
        if report["status"] == "generated":
            conn.execute("UPDATE report SET status = 'draft', version = version + 1 WHERE id = ?",
                         (rid,))
    return {"counters": counters, "saved_at": stamp}


# ── 生成 ────────────────────────────────────────────────
def _narrative(unfit: list[dict], risks: dict, score: float, grade: str,
               *, llm_used: bool) -> str:
    """叙述文字。模型可用时用模型，不可用时用规则摘要兜底。"""
    if not unfit:
        return f"本次评估未发现不符合项。综合安全状况得分 {score}，等级 {grade}。"
    lines = [f"本次评估共发现 {len(unfit)} 项不符合，综合安全状况得分 {score}，等级 {grade}。"]
    for index, item in enumerate(unfit, start=1):
        risk = risks.get(item["no"], {})
        reasons = "；".join(item.get("reasons") or []) or item.get("other_text") or "见现场记录"
        lines.append(
            f"{index}、项目 {item['no']}　{risks.get(item['no'], {}).get('name', '')}"
            f"　存在风险：{reasons}；风险类别：{risk.get('category', '')}。"
        )
    if not llm_used:
        lines.append("（本报告未使用大模型生成，叙述文字由规则与图谱摘要自动汇总。）")
    return "\n".join(lines)


def _narrative_prompt(report: dict, unfit: list[dict], risks: dict,
                      score: float, grade: str) -> str:
    """把报告里的事实整理成提示词。

    刻意**不带知识图谱链路**：模板条目与图谱条目还没建立映射（PRD Q5），
    现在硬接只会给出对不上的证据。模型只根据"用户自己填的内容+规则算出的风险值"来写。
    """
    form = report.get("form") or {}
    counters = report.get("counters") or {}
    categories = {"Ⅰ类": 0, "Ⅱ类": 0, "Ⅲ类": 0}
    for risk in risks.values():
        if risk["category"] in categories:
            categories[risk["category"]] += 1
    data = {
        "委托单位名称": form.get("clientName", ""),
        "使用单位名称": form.get("userName", ""),
        "设备类别": form.get("deviceCategory", ""),
        "产品编号": form.get("productNo", ""),
        "评估日期": form.get("assessDate", ""),
        "评价条目总数": counters.get("total"),
        "不符合项": [
            {
                "项目编号": item["no"],
                "存在风险": "；".join(item.get("reasons") or []) or item.get("other_text") or "",
                "风险类别": risks.get(item["no"], {}).get("category", ""),
            }
            for item in unfit
        ],
        "风险类别统计": categories,
        "综合安全状况得分": score,
        "综合安全状况等级": grade,
    }
    return json.dumps({"system": NARRATIVE_SYSTEM, "data": data}, ensure_ascii=False)


async def generate(report_id: int | str, *, use_llm: bool = False,
                   actor: dict | None = None) -> dict:
    """生成报告：分配编号 + 算风险评定值 + 算得分等级 + 组装叙述文字。

    异步是为了能直接 await 模型调用（模型用同一个事件循环里的 httpx 客户端）。
    模型不可用时**不抛错**，退回规则摘要并在溯源里写明 —— 报告必须出得来。
    """
    rid = int(report_id)
    started = monotonic()
    stamp = now_iso()

    with db.get_conn() as conn:
        report = report_repo.find_by_id(conn, rid)
        if report is None:
            raise LookupError("报告不存在")
        if report["status"] in ("void", "filed"):
            raise ValueError("已作废或已归档的报告不能重新生成")

        counters = report["counters"] or counters_of(report["items"])
        if int(counters.get("missing", 0)) > 0:
            raise ValueError(f"还有 {counters['missing']} 项未填写，无法生成报告")

        unfit = [i for i in report["items"] if i.get("result") == "unfit"]
        risks: dict[str, dict] = {}
        for index, item in enumerate(unfit):
            risks[item["no"]] = risk_rules.assign(index)
        categories = [r["category"] for r in risks.values()]
        score = risk_rules.score_of(categories)
        grade = risk_rules.grade_of(score)

        # 编号只在第一次生成时分配；重新生成沿用原编号（报告身份不变）
        report_no = report["report_no"]
        if not report_no:
            day = day_key(stamp)
            seq = report_repo.next_seq(conn, day)
            report_no = f"{settings.report_no_prefix}-{day}-{seq:03d}"

        fallback = _narrative(unfit, risks, score, grade, llm_used=False)
        narrative, llm_used, llm_error = fallback, False, ""
        if use_llm:
            try:
                text = (await llm_service.generate(
                    _narrative_prompt(report, unfit, risks, score, grade)) or "").strip()
                if text:
                    narrative, llm_used = text, True
                else:
                    llm_error = "模型返回空内容"
            except Exception as e:  # noqa: BLE001
                # 模型挂了不是"报告出不来"的理由，降级并记明原因
                llm_error = f"{type(e).__name__}: {e}"

        provenance = {
            "llm_used": llm_used,
            "llm_model": "Qwen3.5-4B" if llm_used else "",
            "llm_error": llm_error,
            "llm_note": "" if llm_used else "未使用大模型，叙述文字由规则摘要自动汇总",
            "kg_available": False,
            "kg_note": "模板条目与图谱条目的映射未定（PRD Q5），暂不引用图谱链路",
            "risk_rule": "placeholder（PRD Q6 未定）",
            "unfit_count": len(unfit),
            "catalog_version": report["catalog_version"],
            "elapsed_ms": int((monotonic() - started) * 1000),
        }
        report_repo.update_generated(
            conn, rid, report_no=report_no, status="generated", generated_at=stamp,
            risks=risks, score=int(score) if float(score).is_integer() else score,
            grade=grade, narrative=narrative, provenance=provenance,
        )
        audit_service.record(conn, "report_generate", actor=actor, target=report_no,
                             note=f"不符合 {len(unfit)} 项，得分 {score}")
        updated = report_repo.find_by_id(conn, rid)
    return public_report(updated)


# ── 管理 ────────────────────────────────────────────────
def list_reports(*, status: str | None = None, q: str | None = None,
                 from_: str | None = None, to: str | None = None,
                 mine: int | str | None = None, page: int = 1, size: int = 20) -> dict:
    with db.get_conn() as conn:
        rows, total = report_repo.list_(
            conn, status=status, q=q, from_=from_, to=to,
            mine=int(mine) if mine else None, page=page, size=size,
        )
    return {"total": total, "page": page, "size": size,
            "items": [public_report(r) for r in rows]}


def void_report(report_id: int | str, *, reason: str, actor: dict | None = None) -> dict:
    rid = int(report_id)
    if not reason.strip():
        raise ValueError("作废必须填写原因")
    with db.get_conn() as conn:
        report = report_repo.find_by_id(conn, rid)
        if report is None:
            raise LookupError("报告不存在")
        if not report_repo.void(conn, rid, voided_at=now_iso(), reason=reason.strip()):
            raise ValueError("只有已生成或已归档的报告才能作废")
        audit_service.record(conn, "report_void", actor=actor,
                             target=report["report_no"] or str(rid), note=reason.strip())
        return public_report(report_repo.find_by_id(conn, rid))


def clone_report(report_id: int | str, *, actor: dict | None = None) -> dict:
    """复制为新建：只带抬头，不带评价结果。"""
    source = get_report(report_id)
    if source is None:
        raise LookupError("报告不存在")
    cloned = create_draft(actor=actor, form=source["form"])
    return get_report(cloned["id"])


def delete_report(report_id: int | str, *, actor: dict | None = None) -> None:
    rid = int(report_id)
    with db.get_conn() as conn:
        report = report_repo.find_by_id(conn, rid)
        if report is None:
            raise LookupError("报告不存在")
        if report["status"] not in ("draft", "void"):
            raise ValueError("已生成或已归档的报告只能作废，不能删除")
        report_repo.delete(conn, rid)
        audit_service.record(conn, "report_delete", actor=actor,
                             target=report["report_no"] or str(rid))

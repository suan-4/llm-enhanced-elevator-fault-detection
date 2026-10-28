"""kg-prompt-v1 输出校验器（纯程序，不调用模型）。

只做三件事：
1. 解析模型 JSON；
2. 按证据白名单检查 T2/T3/T4；
3. 返回可直接入库的 errors（code/item_no/detail）。
"""
from __future__ import annotations

import difflib
import json
import re
from typing import Any

FORBIDDEN_CLAIMS = ("已确认", "已签核", "违反", "必然", "已证明")
CLAUSE_RE = re.compile(r"(?:GB/T|GB|TSG)\s*\d+(?:\.\d+)*(?:[—\-]?\d+)?")
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?%?")
PATH_RE = re.compile(r"PATH_V2_[A-Za-z0-9_]+")


class ValidationError(ValueError):
    def __init__(self, code: str, detail: str, item_no: str = "") -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.item_no = item_no


def _norm(value: Any) -> str:
    return re.sub(r"[\s，,。；;、:：/（）()【】\[\]]+", "",
                  str(value or ""))


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for x in value:
            out.extend(_strings(x))
        return out
    if isinstance(value, dict):
        out = []
        for x in value.values():
            out.extend(_strings(x))
        return out
    return []


def parse_json_output(raw: str | dict) -> dict:
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    text = re.sub(r"^\s*\x60{3}(?:json)?\s*|\s*\x60{3}\s*$", "", text, flags=re.I)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValidationError("SCHEMA_INVALID", "输出不是 JSON 对象")
    try:
        data = json.loads(text[start:end + 1])
    except ValueError as exc:
        raise ValidationError("SCHEMA_INVALID", f"JSON 解析失败：{exc}") from exc
    if not isinstance(data, dict):
        raise ValidationError("SCHEMA_INVALID", "输出必须是 JSON 对象")
    return data


def _allowed_numbers(*values: Any) -> set[str]:
    return set(NUMBER_RE.findall(json.dumps(values, ensure_ascii=False)))


def _allowed_clauses(*values: Any) -> set[str]:
    return {m.group(0) for m in CLAUSE_RE.finditer(json.dumps(values, ensure_ascii=False))}


def _check_common(output: dict, item_no: str, allowed_numbers: set[str],
                  allowed_clauses: set[str]) -> list[dict]:
    errors: list[dict] = []
    texts = [t for t in _strings(output) if t]

    for text in texts:
        for claim in FORBIDDEN_CLAIMS:
            if claim in text:
                errors.append({"code": "CLAIM_UNSUPPORTED", "item_no": item_no,
                               "detail": f"出现禁止表述：{claim}"})
                break
        for clause in CLAUSE_RE.findall(text):
            if clause not in allowed_clauses:
                errors.append({"code": "CLAUSE_NOT_ALLOWED", "item_no": item_no,
                               "detail": f"条款不在证据中：{clause}"})
        for number in NUMBER_RE.findall(text):
            if number not in allowed_numbers and number != str(item_no):
                errors.append({"code": "NUMBER_NOT_ALLOWED", "item_no": item_no,
                               "detail": f"数值不在证据中：{number}"})
    return errors


def validate_t3(output: dict, *, item_no: str, allowed_path_ids: set[str],
                evidence_paths: list[dict], rule_facts: dict | None = None) -> dict:
    """校验 T3 逐项证据归纳结果。"""
    try:
        data = parse_json_output(output)
    except ValidationError as exc:
        return {"valid": False, "errors": [{"code": exc.code, "item_no": item_no,
                                            "detail": exc.detail}]}

    errors: list[dict] = []
    required = ["item_no", "path_ids", "fault_chain", "trigger", "barrier",
                "risk", "inspection", "action", "verification", "evidence_note"]
    missing = [k for k in required if k not in data]
    if missing:
        errors.append({"code": "SCHEMA_INVALID", "item_no": item_no,
                       "detail": f"缺少字段：{','.join(missing)}"})
    if str(data.get("item_no", "")) != str(item_no):
        errors.append({"code": "SCHEMA_INVALID", "item_no": item_no,
                       "detail": "item_no 与请求不一致"})

    path_ids = data.get("path_ids")
    if not isinstance(path_ids, list) or any(not isinstance(x, str) for x in path_ids):
        errors.append({"code": "SCHEMA_INVALID", "item_no": item_no,
                       "detail": "path_ids 必须是字符串数组"})
        path_ids = []
    if not set(path_ids).issubset(allowed_path_ids):
        errors.append({"code": "PATH_NOT_ALLOWED", "item_no": item_no,
                       "detail": f"path_ids 不在勾选集合内：{sorted(set(path_ids) - allowed_path_ids)}"})

    chain = data.get("fault_chain")
    if not isinstance(chain, list) or any(not isinstance(x, str) for x in chain):
        errors.append({"code": "SCHEMA_INVALID", "item_no": item_no,
                       "detail": "fault_chain 必须是字符串数组"})
        chain = []
    # 状态必须是证据状态的有序子序列
    evidence_states: list[str] = []
    for p in evidence_paths:
        evidence_states.extend(str(s) for s in (p.get("states") or []))
    cursor = 0
    for state in chain:
        try:
            cursor = evidence_states.index(state, cursor) + 1
        except ValueError:
            errors.append({"code": "SCHEMA_INVALID", "item_no": item_no,
                           "detail": f"fault_chain 不在证据状态链中：{state}"})
            break

    actions = [str(p.get("action") or "") for p in evidence_paths if p.get("action")]
    action = str(data.get("action") or "")
    if action:
        action_n = _norm(action)
        grounded = any(action_n and (_norm(a) and (action_n in _norm(a) or _norm(a) in action_n))
                       for a in actions)
        if not grounded:
            best = max((difflib.SequenceMatcher(None, action_n, _norm(a)).ratio()
                        for a in actions), default=0.0)
            if best < 0.60:
                errors.append({"code": "ACTION_NOT_GROUNDED", "item_no": item_no,
                               "detail": f"整改措施与证据不一致（相似度 {best:.2f}）"})

    for key in ("trigger", "barrier", "risk", "inspection", "verification"):
        if not isinstance(data.get(key, ""), str):
            errors.append({"code": "SCHEMA_INVALID", "item_no": item_no,
                           "detail": f"{key} 必须是字符串"})
    for key in ("trigger", "barrier", "risk", "inspection", "action", "verification"):
        if len(str(data.get(key) or "")) > 220:
            errors.append({"code": "SCHEMA_INVALID", "item_no": item_no,
                           "detail": f"{key} 超过长度限制"})

    evidence_values = evidence_paths + ([rule_facts] if rule_facts else [])
    allowed_numbers = _allowed_numbers(evidence_values, item_no)
    allowed_clauses = _allowed_clauses(evidence_values)
    errors.extend(_check_common(data, item_no, allowed_numbers, allowed_clauses))

    # 去重，保持顺序
    seen = set()
    unique = []
    for err in errors:
        key = (err["code"], err["detail"])
        if key not in seen:
            seen.add(key)
            unique.append(err)
    return {"valid": not unique, "errors": unique}


def normalize_t4(output: dict) -> dict:
    """模型常见超长；在不新增事实的前提下截断到模板上限。"""
    data = dict(output)
    if isinstance(data.get("overview"), str):
        data["overview"] = data["overview"].strip()[:800]
    findings = data.get("key_findings")
    if isinstance(findings, list):
        data["key_findings"] = [str(x).strip()[:80] for x in findings if isinstance(x, str)][:5]
    return data


def validate_t4(output: dict, *, overview_facts: dict, required_keys: list[str],
                items: list[dict]) -> dict:
    """校验 T4 报告叙事结果（正文不出现候选路径）。"""
    try:
        data = parse_json_output(output)
    except ValidationError as exc:
        return {"valid": False, "errors": [{"code": exc.code, "item_no": "",
                                            "detail": exc.detail}]}
    errors: list[dict] = []
    for key in ("overview", "key_findings", "risk_statement", "limitations"):
        if key not in data:
            errors.append({"code": "SCHEMA_INVALID", "item_no": "",
                           "detail": f"缺少字段：{key}"})
    overview = str(data.get("overview") or "")
    findings = data.get("key_findings")
    if len(overview) > 800:
        errors.append({"code": "SCHEMA_INVALID", "item_no": "", "detail": "overview 超过 800 字"})
    if not isinstance(findings, list) or len(findings) > 5:
        errors.append({"code": "SCHEMA_INVALID", "item_no": "",
                       "detail": "key_findings 必须是最多 5 条的数组"})
        findings = []
    for i, finding in enumerate(findings):
        if not isinstance(finding, str) or len(finding) > 80:
            errors.append({"code": "SCHEMA_INVALID", "item_no": "",
                           "detail": f"key_findings[{i}] 超过 80 字或非字符串"})
        elif items and not any(str(it.get("item_no")) in finding for it in items):
            errors.append({"code": "CLAIM_UNSUPPORTED", "item_no": "",
                           "detail": f"key_findings[{i}] 未引用 item_no"})

    text_all = " ".join([overview, " ".join(str(x) for x in findings),
                         str(data.get("risk_statement") or ""),
                         str(data.get("limitations") or "")])
    if PATH_RE.search(text_all) or "候选路径" in text_all:
        errors.append({"code": "PATH_NOT_ALLOWED", "item_no": "",
                       "detail": "正文不得出现候选路径/path_id（只进附页）"})
    if "不符合" not in overview and "未发现" not in overview:
        errors.append({"code": "CLAIM_UNSUPPORTED", "item_no": "", "detail": "overview 未说明不符合结论"})
    limitations = str(data.get("limitations") or "")
    if "候选" not in limitations and "复核" not in limitations:
        errors.append({"code": "SCHEMA_INVALID", "item_no": "", "detail": "limitations 未标注候选/复核"})
    for key in required_keys:
        if key == "finding":
            continue
        if str(key) not in text_all and not any(str(key) in str(f) for f in findings):
            if key.startswith(("1", "2", "3", "4", "5", "6", "7", "8", "9")):
                errors.append({"code": "CLAIM_UNSUPPORTED", "item_no": "",
                               "detail": f"未覆盖必含事实 key：{key}"})
    allowed_numbers = _allowed_numbers(overview_facts, items)
    allowed_clauses = _allowed_clauses(overview_facts, items)
    errors.extend(_check_common(data, "", allowed_numbers, allowed_clauses))
    seen = set(); unique = []
    for err in errors:
        key = (err["code"], err["detail"])
        if key not in seen:
            seen.add(key); unique.append(err)
    return {"valid": not unique, "errors": unique}

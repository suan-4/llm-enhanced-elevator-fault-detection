"""kg-prompt-v1 模板与校验器测试（不调用模型、不依赖图谱数据库）。"""
import json

from app.services.kg_prompt import (
    PROMPT_VERSION,
    build_t1_query_prompt,
    build_t2_rerank_prompt,
    build_t3_item_prompt,
    build_t4_overview_prompt,
)
from app.services.kg_validation import validate_t3, validate_t4

PATH = {
    "path_id": "PATH_V2_BRAKE_test",
    "system": "制动系统",
    "component": "手动松闸及双组机械独立性",
    "states": ["释放手柄锁扣误留开启", "释放力持续施加于制动器", "制动衬不能闭合"],
    "mechanism_steps": ["松闸锁扣未复位使释放力持续施加。"],
    "trigger_condition": "松闸手柄锁扣未复位。",
    "barrier_condition": "复位检查与分组验证。",
    "risk": "轿厢非正常移动",
    "inspection": "检查松闸拉索、杠杆复位与联动间隙。",
    "action": "按救援结束复位程序恢复并验证。",
    "verification": "复测复位及各组独立能力。",
    "clause": {"standard_code": "TSG T5002—2017", "clause_no": "附件A 表A-1 序号1"},
    "confidence": 0.4,
    "verified": "false",
}


def _envelope(prompt: str) -> dict:
    data = json.loads(prompt)
    assert isinstance(data.get("system"), str) and data["system"]
    assert isinstance(data.get("data"), dict)
    return data


def test_prompt_version():
    assert PROMPT_VERSION == "kg-prompt-v1"


def test_t1_is_json_envelope():
    data = _envelope(build_t1_query_prompt(
        item_no="5.1", item_name="制动器型式", original_text="柱塞发涩", known_terms=["制动器"]))
    assert data["data"]["task"] == "kg_query_expand"
    assert data["data"]["item_no"] == "5.1"


def test_t2_only_candidates_payload():
    data = _envelope(build_t2_rerank_prompt(
        item_no="5.1", query="柱塞发涩", candidates=[PATH]))
    assert data["data"]["task"] == "kg_rerank"
    assert data["data"]["candidates"][0]["path_id"] == PATH["path_id"]
    assert "states" not in data["data"]["candidates"][0]


def test_t3_contains_evidence_and_requires_json():
    data = _envelope(build_t3_item_prompt(
        item_no="5.1", item_name="制动器型式", query="双组要求",
        rule_facts={"category": "Ⅱ类", "measure": "应整改。"}, paths=[PATH]))
    assert data["data"]["task"] == "kg_item_summary"
    assert data["data"]["paths"][0]["path_id"] == PATH["path_id"]
    assert data["data"]["paths"][0]["states"][0] == "释放手柄锁扣误留开启"


def test_t4_body_has_no_candidate_paths():
    data = _envelope(build_t4_overview_prompt(
        overview_facts={"finding": "本次评估共发现 1 项不符合。", "score": "得分 97.73，等级 一级。"},
        required_keys=["finding", "score"],
        items=[{"item_no": "5.1", "category": "Ⅱ类", "measure": "应整改。", "has_candidate_evidence": True}],
    ))
    assert data["data"]["task"] == "report_analysis"
    assert "path_id" not in json.dumps(data["data"], ensure_ascii=False)
    assert "候选路径" not in json.dumps(data["data"], ensure_ascii=False)


GOOD_T3 = {
    "item_no": "5.1",
    "path_ids": ["PATH_V2_BRAKE_test"],
    "fault_chain": ["释放手柄锁扣误留开启", "释放力持续施加于制动器", "制动衬不能闭合"],
    "trigger": "松闸手柄锁扣未复位。",
    "barrier": "复位检查与分组验证。",
    "risk": "轿厢非正常移动",
    "inspection": "检查松闸拉索、杠杆复位与联动间隙。",
    "action": "按救援结束复位程序恢复并验证。",
    "verification": "复测复位及各组独立能力。",
    "evidence_note": "候选证据，未签核",
}


def test_t3_good_passes():
    result = validate_t3(GOOD_T3, item_no="5.1", allowed_path_ids={PATH["path_id"]},
                         evidence_paths=[PATH], rule_facts={"category": "Ⅱ类"})
    assert result["valid"] is True, result["errors"]


def test_t3_rejects_unknown_path():
    bad = json.loads(json.dumps(GOOD_T3))
    bad["path_ids"] = ["PATH_V2_FAKE"]
    result = validate_t3(bad, item_no="5.1", allowed_path_ids={PATH["path_id"]},
                         evidence_paths=[PATH])
    assert not result["valid"]
    assert any(e["code"] == "PATH_NOT_ALLOWED" for e in result["errors"])


def test_t3_rejects_ungrounded_action_and_chain():
    bad_action = json.loads(json.dumps(GOOD_T3))
    bad_action["action"] = "随便换个部件"
    r = validate_t3(bad_action, item_no="5.1", allowed_path_ids={PATH["path_id"]},
                    evidence_paths=[PATH])
    assert any(e["code"] == "ACTION_NOT_GROUNDED" for e in r["errors"])

    bad_chain = json.loads(json.dumps(GOOD_T3))
    bad_chain["fault_chain"] = ["不存在状态"]
    r = validate_t3(bad_chain, item_no="5.1", allowed_path_ids={PATH["path_id"]},
                    evidence_paths=[PATH])
    assert any(e["code"] == "SCHEMA_INVALID" for e in r["errors"])


def test_t4_good_and_rejects_path_or_new_number():
    facts = {"finding": "本次评估共发现 1 项不符合。", "score": "得分 97.73，等级 一级。"}
    items = [{"item_no": "5.1", "category": "Ⅱ类", "measure": "应整改。"}]
    good = {
        "overview": "本次评估共发现 1 项不符合。综合安全状况得分 97.73，等级 一级。",
        "key_findings": ["5.1：制动器型式不符合，已给出候选演化路径。"],
        "risk_statement": "按规则评定为Ⅱ类风险。",
        "limitations": "图谱路径为工程候选，需人工复核。",
    }
    result = validate_t4(good, overview_facts=facts, required_keys=["finding", "score"], items=items)
    assert result["valid"] is True, result["errors"]

    bad = json.loads(json.dumps(good))
    bad["overview"] += " 详见 PATH_V2_FAKE。"
    r = validate_t4(bad, overview_facts=facts, required_keys=["finding", "score"], items=items)
    assert any(e["code"] == "PATH_NOT_ALLOWED" for e in r["errors"])

    bad2 = json.loads(json.dumps(good))
    bad2["key_findings"].append("5.1：新增了一个 999 的限值要求。")
    r2 = validate_t4(bad2, overview_facts=facts, required_keys=["finding", "score"], items=items)
    assert any(e["code"] == "NUMBER_NOT_ALLOWED" for e in r2["errors"])

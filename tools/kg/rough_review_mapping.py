#!/usr/bin/env python3
"""Rough first-pass review (v2): TF-IDF over all 1,052 paths.

For each of the 445 JTE options, retrieve top 3 candidate paths by Chinese token
TF-IDF (jieba), then annotate a conservative suggested decision:

  批准      : top candidate clearly matches component + fault mechanism
  待定      : plausible but weak / needs human check
  驳回      : candidate exists but does not match this option
  无合适候选: structural/test/administrative requirement not represented as a fault path

Output is a pre-filled review CSV for the human reviewer.
"""
from __future__ import annotations
import csv, json, re, unicodedata
from collections import defaultdict
from pathlib import Path

import jieba
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "docs" / "kg-review"
GRAPH = ROOT / "v2_1000paths" / "data" / "fault_paths.csv"
EXPERT = ROOT / "backend" / "app" / "data" / "expert_risks.json"
JTE = ROOT / "backend" / "app" / "data" / "jte_items.json"
OUT = SRC / "JTE-图谱映射审核表-粗审.csv"

COMP_TERMS = [
    "制动器", "制动轮", "制动盘", "制动衬", "制动臂", "制动弹簧", "闸瓦", "抱闸",
    "限速器", "棘爪", "棘轮", "离心重块", "绳轮", "夹绳", "张紧轮",
    "安全钳", "钳体", "楔块", "提拉杆", "联动轴",
    "层门", "轿门", "门扇", "门套", "地坎", "门锁", "门机", "门刀", "门轮", "门滑块",
    "钢丝绳", "悬挂绳", "包覆绳", "绳头", "端接", "锥套", "曳引轮", "绳槽",
    "减速箱", "减速器", "蜗轮", "斜齿轮", "行星齿轮", "轴承", "联轴器", "电动机", "电机",
    "曳引机", "编码器", "控制柜", "接触器", "继电器", "变频器", "接线", "接地",
    "随行电缆", "补偿链", "补偿缆", "对重", "对重架", "导靴", "导轨", "轨线",
    "缓冲器", "液压缓冲器", "弹簧缓冲器", "轿架", "轿厢", "轿壁", "轿顶", "轿底",
    "安全开关", "电气安全装置", "平层", "层楼位置", "盘车", "手动", "夹绳器",
    "机房", "滑轮间", "井道", "底坑", "通风", "照明", "护栏", "防护",
    "扳手", "松闸", "释放手柄", "杠杆", "拉索", "销轴", "焊缝", "支架", "底座", "安装孔",
    "紧固", "隔振垫", "主轴", "键", "油封", "密封", "锁钩", "锁座",
    "触点", "线圈", "电阻", "电容", "电线", "端子", "接地线", "等电位",
    "平层感应", "旋编", "光栅", "磁开关", "按钮", "急停", "检修", "报警", "对讲",
    "应急电源", "蓄电池", "制动电阻", "散热", "风扇", "油缸", "柱塞", "阀", "液压", "弹簧",
    "旁路", "开门限制", "意外移动", "上行超速", "安全回路", "门锁监控", "平层", "楼层显示",
    "限速绳", "张紧", "安全触点", "缓冲", "底坑", "轿架", "对重块", "导轨压板",
]

STOP = set("的 了 和 与 或 在 是 为 应 不应 不 未 有 无 及 等 中 上 下 时 后 前 可能 导致 影响 "
           "存在 进行 检查 要求 符合 不符合 情况 工作 正常 装置 设备 电梯 安全 人员 单位 "
           "使用 维护 保养 应该 需要 是否 以及 一个 两个 至少 设置 采用 安装 部件 功能".split())

STRUCT = ["未分成至少两组", "未采用至少两个", "未设置", "未装设", "未配备", "未安装", "缺少",
          "应设置", "应装设", "应配备", "应安装", "应满足", "应能", "应当", "不应", "不得",
          "型式", "结构", "证书", "铭牌", "标识", "标志", "制度", "记录", "档案", "预案",
          "演练", "培训", "资质", "许可", "检验报告", "自检", "合同", "平衡系数", "应急救援",
          "空载", "制停", "加速度", "减速度", "监测功能", "试验", "校验"]
MECH_GROUPS = [
    {"锈蚀", "腐蚀", "锈损", "氧化", "起皮", "剥落"},
    {"裂纹", "开裂", "裂损", "龟裂"},
    {"断裂", "折断", "裂断"},
    {"磨损", "磨耗", "磨伤", "拉伤"},
    {"变形", "翘曲", "弯曲", "扭曲", "鼓包"},
    {"松动", "松脱", "脱落", "脱开", "位移", "脱焊", "开焊"},
    {"卡阻", "卡涩", "卡滞", "卡死", "咬死", "不灵活", "转动不灵活", "动作不灵活"},
    {"渗漏", "泄漏", "滴漏", "渗油"},
    {"异响", "噪声", "杂音", "撞击声"},
    {"过热", "发热", "温升", "烧蚀"},
    {"破损", "穿孔", "破裂", "缺损", "开裂", "洞穿", "缺口", "锋利"},
    {"润滑", "缺油", "乳化", "干摩擦"},
    {"污染", "油污", "积尘", "堵塞"},
    {"潮湿", "积水", "结露", "冻结"},
    {"短路", "断路", "接触不良", "虚接"},
    {"绝缘", "老化", "击穿", "漏电"},
    {"打滑", "滑移", "溜车"},
    {"张力", "制动力", "保持力", "夹持力", "压力"},
    {"信号", "编码", "反馈", "漂移", "抖动", "失真", "丢步", "失步"},
    {"触点", "线圈", "电压", "电流", "通断", "烧蚀"},
]

MECH = ["裂纹", "断裂", "折断", "变形", "磨损", "锈蚀", "腐蚀", "松动", "脱落", "卡阻", "卡涩",
        "卡滞", "咬合", "脱扣", "误动作", "不动作", "动作迟滞", "间隙", "行程", "位移", "偏斜",
        "弯曲", "拉长", "伸长", "渗漏", "泄漏", "油污", "污染", "过热", "发热", "异响", "噪声",
        "振动", "短路", "断路", "接触不良", "绝缘", "老化", "失效", "失灵", "破损", "开裂",
        "点蚀", "胶合", "剥落", "起皮", "润滑", "缺油", "乳化", "堵塞", "积水", "潮湿", "打滑",
        "滑移", "制动力", "保持力", "夹持力", "张力", "通断", "信号", "编码", "反馈", "触点",
        "线圈", "电压", "电流", "双组", "两组", "独立", "破裂", "缺损", "短缺", "脱焊", "烧蚀",
        "击穿", "漏电", "失步", "漂移", "迟滞", "抖动"]


def norm(s: str) -> str:
    return re.sub(r"[\s，,。；;、:：/（）()【】\[\]]+", "", unicodedata.normalize("NFKC", s or ""))


def tok(s: str) -> list[str]:
    s = unicodedata.normalize("NFKC", s or "")
    return [w for w in jieba.lcut(s) if len(w.strip()) > 1 and w not in STOP]


def ptext(p: dict) -> str:
    return " ".join(filter(None, [
        p.get("path_summary"), p.get("mechanism_steps"), p.get("inspection_method"),
        p.get("corrective_action"), p.get("risk_name"), p.get("component_name"),
        p.get("item_name"),
    ]))


def classify(option: str, path: dict, sim: float, item_comp: str, item_name: str) -> tuple[str, str, str]:
    o = norm(option)
    t = norm(ptext(path))
    mech = [w for w in MECH if w in o and w in t]
    shared_groups = []
    for group in MECH_GROUPS:
        if any(w in o for w in group) and any(w in t for w in group):
            shared_groups.append("/".join(sorted(group & set(MECH)) or sorted(group)[:1]))
    if len(shared_groups) > len(mech):
        mech = shared_groups
    comp = norm(path.get("component_name") or "")
    item = norm(item_comp or "")
    # 部件同族：条目级主部件匹配，或「情形中的具体部件词」在候选部件/路径文本中出现
    item_terms = [w for w in COMP_TERMS if w in item]
    specific = [w for w in COMP_TERMS if w in o and w not in item_terms]
    cand_text = comp + " " + t
    shared_specific = [w for w in specific if w in cand_text]
    comp_match = bool(item and (item in comp or comp in item)) or bool(shared_specific)
    if not comp_match and item_terms and not specific:
        comp_match = any(w in comp for w in item_terms)
    # 情形里点名了具体部件（如「扳手」「拉索」），候选部件不含它 → 不算同族
    if specific and not shared_specific:
        comp_match = False
    # 候选必须与「评估项本身的部件」同族，避免把缓冲器弹簧映射到制动弹簧等
    head_terms = sorted({w for w in COMP_TERMS if w in norm(item_name)}, key=len, reverse=True)
    if head_terms:
        longest = [w for w in head_terms if len(w) == len(head_terms[0])]
        if not any(w in cand_text for w in longest):
            comp_match = False
    structural = any(p in o for p in STRUCT)
    if structural and not (len(mech) >= 2 or "双组" in t or "两组" in t):
        return "无合适候选", "低", "结构/试验/管理类要求，图谱无对应故障演化路径"
    if structural and ("双组" in t or "两组" in t) and sim >= 0.20:
        return "待定", "中", "图谱有双组/独立性相关路径，但属故障情景，需确认能否对应此结构要求"
    # 批准要求「部件同族」且至少共享一个机理（或明确结构对应）；避免泛词相似误批
    if comp_match and sim >= 0.36 and len(mech) >= 1:
        return "批准", "高", f"同部件且机理吻合(sim={sim:.2f})，机理={','.join(mech[:3])}"
    if comp_match and sim >= 0.28 and len(mech) >= 2:
        return "批准", "中", f"同部件且机理吻合(sim={sim:.2f}，机理={','.join(mech[:3])})"
    if comp_match and sim >= 0.36:
        return "批准", "中", f"同部件且文本相似(sim={sim:.2f})，建议确认故障机理"
    if sim >= 0.45 and len(mech) >= 2:
        return "批准", "中", f"文本高度相似且机理一致(sim={sim:.2f})"
    if sim >= 0.28 or len(mech) >= 2:
        return "待定", "中" if sim >= 0.30 else "低", f"候选可能相关但部件/机理证据不足(sim={sim:.2f}，机理={','.join(mech[:3]) or '无'})"
    return "驳回", "低", f"与情形无明显关系(sim={sim:.2f})"


def main() -> int:
    with GRAPH.open(encoding="utf-8-sig", newline="") as fh:
        paths = list(csv.DictReader(fh))
    jte = json.loads(JTE.read_text(encoding="utf-8"))["items"]
    expert = json.loads(EXPERT.read_text(encoding="utf-8"))["items"]
    with (SRC / "JTE-条目候选表.csv").open(encoding="utf-8-sig", newline="") as fh:
        item_rows = {r["jte_no"]: r for r in csv.DictReader(fh)}

    ids = [p["path_id"] for p in paths]
    vec = TfidfVectorizer(tokenizer=tok, lowercase=False, token_pattern=None)
    matrix = vec.fit_transform([ptext(p) for p in paths])

    out, counts = [], defaultdict(int)
    for item in jte:
        no, name = str(item["no"]), item["name"]
        item_comp = item_rows.get(no, {}).get("graph_component", "")
        for opt in expert.get(no, {}).get("options", []):
            option = opt.get("text") or opt.get("raw_text") or ""
            sims = cosine_similarity(vec.transform([option]), matrix)[0]
            order = sims.argsort()[::-1][:3]
            candidates = []
            for idx in order:
                p, sim = paths[int(idx)], float(sims[int(idx)])
                # 部件同族加权：候选部件含当前条目的主部件关键词
                bonus = 0.08 if item_comp and (norm(item_comp) in norm(p["component_name"]) or
                                               norm(p["component_name"]) in norm(item_comp)) else 0.0
                candidates.append((sim + bonus, sim, p))
            for rank, (score, sim, p) in enumerate(candidates, 1):
                decision, conf, reason = classify(option, p, sim, item_comp, name)
                out.append({
                    "jte_no": no, "jte_name": name,
                    "option_key": opt.get("key"), "option_text": option,
                    "option_category": opt.get("category", ""),
                    "rule_measure": opt.get("measure", ""),
                    "rank": rank, "score": round(sim, 3),
                    "path_id": p["path_id"], "system": p["system_name"],
                    "component": p["component_name"], "path_summary": p["path_summary"],
                    "inspection": p["inspection_method"], "action": p["corrective_action"],
                    "verification": p["verification_after_action"], "risk": p["risk_name"],
                    "match_reason": "tfidf-top3; candidate only",
                    "suggested_decision": "待定" if rank > 1 and decision == "批准" else decision,
                    "suggestion_confidence": conf,
                    "suggestion_reason": reason,
                    "self_decision": "", "self_note": "", "expert_decision": "", "expert_note": "",
                })
            # 若第一名不是批准，其余候选统一待定/驳回（避免同一情形出现多个批准）
            top_decision = out[-len(candidates)]["suggested_decision"]
            for row in out[-len(candidates):]:
                if row["rank"] > 1 and row["suggested_decision"] == "批准" and top_decision != "批准":
                    row["suggested_decision"] = "待定"
                counts[row["suggested_decision"]] += 1

    fields = ["jte_no", "jte_name", "option_key", "option_text", "option_category",
              "rule_measure", "rank", "score", "path_id", "system", "component",
              "path_summary", "inspection", "action", "verification", "risk",
              "match_reason", "suggested_decision", "suggestion_confidence",
              "suggestion_reason", "self_decision", "self_note", "expert_decision", "expert_note"]
    with OUT.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(out)
    summary = {"options": sum(len(v.get("options", [])) for v in expert.values()),
               "rows": len(out), "counts": dict(counts), "out": str(OUT.relative_to(ROOT))}
    (SRC / "rough_review_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

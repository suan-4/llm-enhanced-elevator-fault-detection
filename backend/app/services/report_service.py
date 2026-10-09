import json

from app.services.kg_service import kg_service
from app.services.llm_service import llm_service
from app.models.schemas import (
    ReportRequest,
    ReportResponse,
    ReportContent,
    FaultChainResponse,
    InspectionItemResult,
    FaultState,
    KGNode,
    ElevatorInfo,
)
from datetime import datetime


def _build_structured_chain(raw_chain: list[dict]) -> FaultChainResponse:
    """将图谱原始查询结果转换为 Pydantic 模型。"""
    inspection_results = []
    all_risks: dict[str, KGNode] = {}
    all_actions: dict[str, KGNode] = {}

    for item_data in raw_chain:
        ins = item_data["inspection_item"]
        ins_node = KGNode(
            id=ins["id"],
            name=ins["name"],
            description=ins.get("description"),
        )

        detected_states = []
        for s in item_data["detected_states"]:
            state = s["state"]
            risks = [
                KGNode(id=r["id"], name=r["name"], description=r.get("description"),
                       extra={"risk_level": r.get("risk_level")})
                for r in s.get("risks", [])
            ]
            actions = [
                KGNode(id=a["id"], name=a["name"], description=a.get("description"),
                       extra={"action_type": a.get("action_type")})
                for a in s.get("actions", [])
            ]
            detected_states.append(FaultState(
                state=KGNode(id=state["id"], name=state["name"], description=state.get("description")),
                component=KGNode(id=s["component"]["id"], name=s["component"]["name"],
                                 description=s["component"].get("description")),
                severity=state.get("severity", 0),
                state_level=state.get("state_level"),
                phenomena=[KGNode(id=p["id"], name=p["name"], description=p.get("description"))
                           for p in s.get("phenomena", [])],
                risks=risks,
                actions=actions,
                evolved_states=_build_evolved_states(s.get("evolved_states", [])),
                coupled_states=[KGNode(id=cs["state"]["id"], name=cs["state"]["name"])
                                for cs in s.get("coupled_states", [])],
            ))

            for r in risks:
                if r.id not in all_risks:
                    all_risks[r.id] = r
            for a in actions:
                if a.id not in all_actions:
                    all_actions[a.id] = a

        inspection_results.append(
            InspectionItemResult(inspection_item=ins_node, detected_states=detected_states)
        )

    return FaultChainResponse(
        inspection_results=inspection_results,
        all_risks=list(all_risks.values()),
        all_actions=list(all_actions.values()),
    )


def _build_evolved_states(evolved_list: list[dict]) -> list[FaultState]:
    result = []
    for ev in evolved_list:
        ev_state = ev["state"]
        result.append(FaultState(
            state=KGNode(id=ev_state["id"], name=ev_state["name"],
                         description=ev_state.get("description")),
            component=KGNode(id="", name=""),
            severity=ev_state.get("severity", 0),
            state_level=ev_state.get("state_level"),
            phenomena=[KGNode(id=p["id"], name=p["name"], description=p.get("description"))
                       for p in ev.get("phenomena", [])],
            risks=[KGNode(id=r["id"], name=r["name"], description=r.get("description"),
                          extra={"risk_level": r.get("risk_level")})
                   for r in ev.get("risks", [])],
            actions=[KGNode(id=a["id"], name=a["name"], description=a.get("description"),
                            extra={"action_type": a.get("action_type")})
                     for a in ev.get("actions", [])],
            evolved_states=_build_evolved_states(ev.get("evolved_states", [])),
        ))
    return result


def _build_prompt(chain: FaultChainResponse, elevator_info: ElevatorInfo | None) -> str:
    """将图谱查询结果整理为紧凑文本，缩短 LLM 推理时间。"""
    lines = []

    if elevator_info:
        info = []
        if elevator_info.registration_id: info.append(elevator_info.registration_id)
        if elevator_info.location: info.append(elevator_info.location)
        if elevator_info.elevator_type: info.append(elevator_info.elevator_type)
        if info: lines.append("电梯：" + "/".join(info))

    for ir in chain.inspection_results:
        for s in ir.detected_states:
            parts = [f"{s.component.name}：{s.state.name}({s.state_level})"]
            if s.phenomena: parts.append("现象：" + "、".join(p.name for p in s.phenomena))
            if s.risks: parts.append("风险：" + "、".join(r.name for r in s.risks))
            lines.append("；".join(parts))

    risks = list({r.name for r in chain.all_risks})
    actions = list({a.name for a in chain.all_actions})
    if risks: lines.append("风险汇总：" + "、".join(risks))
    if actions: lines.append("建议汇总：" + "、".join(actions))

    system_prompt = (
        "[严格指令] 你是一个报告生成器，直接输出报告正文。禁止任何对话、问候、确认语句。\n\n"
        "报告模板：\n"
        "综合安全状况等级：X级\n\n"
        "## 故障原因分析\n"
        "逐项分析不合格项的根本原因和故障演化路径。\n\n"
        "## 风险评估\n"
        "按严重程度列出风险项及可能后果。\n\n"
        "## 整改建议\n"
        "按紧急程度列出整改措施。\n\n"
        "## 综合结论\n"
        "给出综合安全评价。"
    )
    data_text = "\n".join(lines)

    return json.dumps(
        {"system": system_prompt, "data": data_text},
        ensure_ascii=False,
    )


def generate_prompt_only(raw_chain: list[dict], elevator_info: ElevatorInfo | None) -> str:
    """只生成 prompt，用于流式接口。"""
    chain = _build_structured_chain(raw_chain)
    return _build_prompt(chain, elevator_info)


async def generate_report(request: ReportRequest) -> ReportResponse:
    raw_chain = kg_service.query_fault_chain(
        request.inspection_item_ids,
        request.abnormal_states,
    )

    if not raw_chain:
        return ReportResponse(
            success=False,
            message="未查询到关联的故障链路信息，请确认检测项目ID和状态ID是否正确。",
        )

    fault_chain = _build_structured_chain(raw_chain)
    prompt = _build_prompt(fault_chain, request.elevator_info)

    # 生成图谱 markdown 摘要（紧凑格式）
    md_lines = []
    for ir in fault_chain.inspection_results:
        md_lines.append(f"### {ir.inspection_item.name}")
        for s in ir.detected_states:
            parts = [f"**{s.component.name}**：{s.state.name}（{s.state_level}）"]
            if s.phenomena:
                parts.append(f"现象：{'、'.join(p.name for p in s.phenomena)}")
            if s.risks:
                parts.append(f"风险：{'、'.join(r.name for r in s.risks)}")
            if s.actions:
                parts.append(f"建议：{'、'.join(a.name for a in s.actions)}")
            md_lines.append("；".join(parts))
    if fault_chain.all_risks:
        md_lines.append("### 风险清单")
        md_lines.append("| 风险 | 等级 | 说明 |")
        md_lines.append("|------|------|------|")
        for r in fault_chain.all_risks:
            lv = r.extra.get("risk_level", "") if r.extra else ""
            md_lines.append(f"| {r.name} | {lv} | {r.description or ''} |")
    if fault_chain.all_actions:
        md_lines.append("### 建议措施")
        md_lines.append("| 措施 | 类型 | 说明 |")
        md_lines.append("|------|------|------|")
        for a in fault_chain.all_actions:
            tp = a.extra.get("action_type", "") if a.extra else ""
            md_lines.append(f"| {a.name} | {tp} | {a.description or ''} |")
    kg_markdown = "\n".join(md_lines)
    kg_markdown = kg_markdown.replace('Ⅰ','I').replace('Ⅱ','II').replace('Ⅲ','III').replace('Ⅳ','IV')

    success = True
    message = "报告生成成功"

    if request.generate_with_llm:
        try:
            raw_output = await llm_service.generate_or_fallback(prompt)
        except Exception:
            raw_output = "[AI模型调用失败，以下为图谱查询结果]\n\n" + kg_markdown
            success = False
            message = "AI模型调用失败，已展示图谱查询结果"
        report = ReportContent(raw_text=raw_output)
    else:
        report = ReportContent(raw_text=kg_markdown)

    return ReportResponse(
        success=success,
        message=message,
        report=report,
        fault_chain=fault_chain,
        generated_at=datetime.now(),
    )

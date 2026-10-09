from neo4j import GraphDatabase, Driver
from neo4j.exceptions import Neo4jError, ServiceUnavailable

from app.config import settings

# 查询流程:
#   1. 根据检测项ID找关联状态 (State -[:DETECTED_BY]-> InspectionItem)
#   2. 合并前端传入的异常状态ID
#   3. 追溯每个状态的: 演化链、现象、风险、建议措施、耦合关系

_QUERY = """
// 从检测项关联的状态
MATCH (c:Component)-[:HAS_STATE]->(s:State)-[:DETECTED_BY]->(ins:InspectionItem)
WHERE ins.item_id IN $item_ids

WITH c, s, ins

OPTIONAL MATCH (s)-[:EVOLVES_TO]->(evolved:State)
OPTIONAL MATCH (evolved)-[:EVOLVES_TO]->(evolved2:State)

OPTIONAL MATCH (s)-[:MANIFESTS_AS]->(p:FaultPhenomenon)
OPTIONAL MATCH (evolved)-[:MANIFESTS_AS]->(ep:FaultPhenomenon)
OPTIONAL MATCH (evolved2)-[:MANIFESTS_AS]->(ep2:FaultPhenomenon)

OPTIONAL MATCH (p)-[:LEADS_TO]->(r:RiskEvent)
OPTIONAL MATCH (ep)-[:LEADS_TO]->(er:RiskEvent)
OPTIONAL MATCH (ep2)-[:LEADS_TO]->(er2:RiskEvent)

OPTIONAL MATCH (s)-[:MITIGATED_BY]->(a:CorrectiveAction)
OPTIONAL MATCH (evolved)-[:MITIGATED_BY]->(ea:CorrectiveAction)
OPTIONAL MATCH (evolved2)-[:MITIGATED_BY]->(ea2:CorrectiveAction)

OPTIONAL MATCH (s)-[:COUPLES_WITH]->(coupled:State)
OPTIONAL MATCH (coupled)<-[:HAS_STATE]-(cc:Component)

RETURN
    ins.item_id AS ins_item_id,
    ins.name AS ins_name,
    ins.description AS ins_desc,
    ins.method AS ins_method,
    s.state_id AS s_id,
    s.name AS s_name,
    s.description AS s_desc,
    s.severity AS s_severity,
    s.state_level AS s_level,
    c.component_id AS c_id,
    c.name AS c_name,
    c.description AS c_desc,
    evolved.state_id AS ev_id,
    evolved.name AS ev_name,
    evolved.description AS ev_desc,
    evolved.severity AS ev_severity,
    evolved.state_level AS ev_level,
    evolved2.state_id AS ev2_id,
    evolved2.name AS ev2_name,
    evolved2.description AS ev2_desc,
    evolved2.severity AS ev2_severity,
    evolved2.state_level AS ev2_level,
    p.phenomenon_id AS p_id,
    p.name AS p_name,
    p.description AS p_desc,
    ep.phenomenon_id AS ep_id,
    ep.name AS ep_name,
    ep.description AS ep_desc,
    ep2.phenomenon_id AS ep2_id,
    ep2.name AS ep2_name,
    ep2.description AS ep2_desc,
    r.risk_id AS r_id,
    r.name AS r_name,
    r.risk_level AS r_level,
    r.description AS r_desc,
    er.risk_id AS er_id,
    er.name AS er_name,
    er.risk_level AS er_level,
    er.description AS er_desc,
    er2.risk_id AS er2_id,
    er2.name AS er2_name,
    er2.risk_level AS er2_level,
    er2.description AS er2_desc,
    a.action_id AS a_id,
    a.name AS a_name,
    a.action_type AS a_type,
    a.description AS a_desc,
    ea.action_id AS ea_id,
    ea.name AS ea_name,
    ea.action_type AS ea_type,
    ea.description AS ea_desc,
    ea2.action_id AS ea2_id,
    ea2.name AS ea2_name,
    ea2.action_type AS ea2_type,
    ea2.description AS ea2_desc,
    coupled.state_id AS cu_id,
    coupled.name AS cu_name,
    coupled.description AS cu_desc,
    cc.component_id AS cc_id,
    cc.name AS cc_name
"""


class KnowledgeGraphService:
    def __init__(self) -> None:
        self._driver: Driver | None = None

    @property
    def driver(self) -> Driver:
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password),
            )
        return self._driver

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def query_fault_chain(self, item_ids: list[str], state_ids: list[str] | None = None) -> list[dict]:
        """根据检测项目ID和前端确认的异常状态ID查询故障链路。

        Returns:
            [
              {
                "inspection_item": {id, name, description, method},
                "detected_states": [
                  {
                    "state": {id, name, description, severity, state_level},
                    "component": {id, name, description},
                    "phenomena": [...], "risks": [...], "actions": [...],
                    "coupled_states": [...], "evolved_states": [...]
                  }
                ]
              }
            ]
        """
        if state_ids is None:
            state_ids = []

        try:
            session = self.driver.session()
        except (ServiceUnavailable, OSError) as e:
            raise RuntimeError(
                f"无法连接Neo4j数据库({settings.neo4j_uri})，请确认数据库已启动。错误: {e}"
            ) from e

        result_per_item: dict[str, dict] = {}

        with session:
            # 检测项关联的状态
            for item_id in item_ids:
                try:
                    records = list(session.run(_QUERY, item_ids=[item_id]))
                except Neo4jError as e:
                    raise RuntimeError(f"图谱查询异常 [{item_id}]: {e}") from e

                self._collect_records(result_per_item, item_id, records, from_item=True)

            # 前端传入的异常状态（跳过已在检测项查询中找到的）
            if state_ids:
                # 收集已查到的状态ID
                seen_states = set()
                for key in result_per_item:
                    for sid in result_per_item[key].get("states", {}):
                        seen_states.add(sid)

                for state_id in state_ids:
                    if state_id in seen_states:
                        continue  # 已通过检测项查到，跳过
                    try:
                        records = list(session.run(
                            """
                            MATCH (c:Component)-[:HAS_STATE]->(s:State {state_id: $state_id})
                            OPTIONAL MATCH (s)-[:EVOLVES_TO]->(evolved:State)
                            OPTIONAL MATCH (evolved)-[:EVOLVES_TO]->(evolved2:State)
                            OPTIONAL MATCH (s)-[:MANIFESTS_AS]->(p:FaultPhenomenon)
                            OPTIONAL MATCH (evolved)-[:MANIFESTS_AS]->(ep:FaultPhenomenon)
                            OPTIONAL MATCH (evolved2)-[:MANIFESTS_AS]->(ep2:FaultPhenomenon)
                            OPTIONAL MATCH (p)-[:LEADS_TO]->(r:RiskEvent)
                            OPTIONAL MATCH (ep)-[:LEADS_TO]->(er:RiskEvent)
                            OPTIONAL MATCH (ep2)-[:LEADS_TO]->(er2:RiskEvent)
                            OPTIONAL MATCH (s)-[:MITIGATED_BY]->(a:CorrectiveAction)
                            OPTIONAL MATCH (evolved)-[:MITIGATED_BY]->(ea:CorrectiveAction)
                            OPTIONAL MATCH (evolved2)-[:MITIGATED_BY]->(ea2:CorrectiveAction)
                            OPTIONAL MATCH (s)-[:COUPLES_WITH]->(coupled:State)
                            OPTIONAL MATCH (coupled)<-[:HAS_STATE]-(cc:Component)
                            RETURN
                                s.state_id AS s_id, s.name AS s_name, s.description AS s_desc,
                                s.severity AS s_severity, s.state_level AS s_level,
                                c.component_id AS c_id, c.name AS c_name, c.description AS c_desc,
                                evolved.state_id AS ev_id, evolved.name AS ev_name, evolved.description AS ev_desc,
                                evolved.severity AS ev_severity, evolved.state_level AS ev_level,
                                evolved2.state_id AS ev2_id, evolved2.name AS ev2_name, evolved2.description AS ev2_desc,
                                evolved2.severity AS ev2_severity, evolved2.state_level AS ev2_level,
                                p.phenomenon_id AS p_id, p.name AS p_name, p.description AS p_desc,
                                ep.phenomenon_id AS ep_id, ep.name AS ep_name, ep.description AS ep_desc,
                                ep2.phenomenon_id AS ep2_id, ep2.name AS ep2_name, ep2.description AS ep2_desc,
                                r.risk_id AS r_id, r.name AS r_name, r.risk_level AS r_level, r.description AS r_desc,
                                er.risk_id AS er_id, er.name AS er_name, er.risk_level AS er_level, er.description AS er_desc,
                                er2.risk_id AS er2_id, er2.name AS er2_name, er2.risk_level AS er2_level, er2.description AS er2_desc,
                                a.action_id AS a_id, a.name AS a_name, a.action_type AS a_type, a.description AS a_desc,
                                ea.action_id AS ea_id, ea.name AS ea_name, ea.action_type AS ea_type, ea.description AS ea_desc,
                                ea2.action_id AS ea2_id, ea2.name AS ea2_name, ea2.action_type AS ea2_type, ea2.description AS ea2_desc,
                                coupled.state_id AS cu_id, coupled.name AS cu_name, coupled.description AS cu_desc,
                                cc.component_id AS cc_id, cc.name AS cc_name
                            """,
                            state_id=state_id,
                        ))
                    except Neo4jError as e:
                        raise RuntimeError(f"图谱查询异常 [{state_id}]: {e}") from e

                    self._collect_records(result_per_item, f"__state__{state_id}", records, from_item=False)

        return self._format_results(result_per_item)

    def _collect_records(self, result: dict, key: str, records: list,
                         from_item: bool = True) -> None:
        """将查询记录汇总到 result_per_item 结构中。"""
        if key not in result:
            result[key] = {"inspection_item": None, "states": {}}

        for rec in records:
            rec_data = dict(rec)

            if from_item and result[key]["inspection_item"] is None:
                result[key]["inspection_item"] = {
                    "id": rec_data["ins_item_id"],
                    "name": rec_data["ins_name"],
                    "description": rec_data.get("ins_desc"),
                    "method": rec_data.get("ins_method"),
                }

            s_id = rec_data["s_id"]
            if s_id not in result[key]["states"]:
                result[key]["states"][s_id] = {
                    "state": {
                        "id": s_id,
                        "name": rec_data["s_name"],
                        "description": rec_data.get("s_desc"),
                        "severity": rec_data.get("s_severity", 0),
                        "state_level": rec_data.get("s_level"),
                    },
                    "component": {
                        "id": rec_data["c_id"],
                        "name": rec_data["c_name"],
                        "description": rec_data.get("c_desc"),
                    },
                    "evolved": {}, "evolved2": {},
                    "phenomena": {}, "risks": {}, "actions": {}, "coupled": {},
                }

            entry = result[key]["states"][s_id]
            self._add_if(entry["phenomena"], rec_data, "p")
            self._add_if(entry["risks"], rec_data, "r", extra_key="r_level", extra_label="risk_level")
            self._add_if(entry["actions"], rec_data, "a", extra_key="a_type", extra_label="action_type")
            self._add_coupled(entry["coupled"], rec_data)
            self._add_evolved(entry["evolved"], entry["evolved2"], rec_data)

    def _add_if(self, container: dict, rec: dict, prefix: str,
                extra_key: str = None, extra_label: str = None) -> None:
        node_id = rec.get(f"{prefix}_id")
        if node_id is None:
            return
        if node_id in container:
            return
        node = {"id": node_id, "name": rec.get(f"{prefix}_name", ""),
                "description": rec.get(f"{prefix}_desc")}
        if extra_key and rec.get(extra_key):
            node[extra_label] = rec[extra_key]
        container[node_id] = node

    def _add_coupled(self, container: dict, rec: dict) -> None:
        cu_id = rec.get("cu_id")
        if cu_id is None or cu_id in container:
            return
        container[cu_id] = {
            "state": {"id": cu_id, "name": rec.get("cu_name")},
            "component": {"id": rec.get("cc_id"), "name": rec.get("cc_name")},
        }

    def _add_evolved(self, ev1: dict, ev2: dict, rec: dict) -> None:
        ev_id = rec.get("ev_id")
        if ev_id is None:
            return
        if ev_id not in ev1:
            ev1[ev_id] = {
                "state": {"id": ev_id, "name": rec["ev_name"], "description": rec.get("ev_desc"),
                          "severity": rec.get("ev_severity", 0), "state_level": rec.get("ev_level")},
                "phenomena": {}, "risks": {}, "actions": {},
            }
        entry = ev1[ev_id]
        self._add_if(entry["phenomena"], rec, "ep")
        self._add_if(entry["risks"], rec, "er", "er_level", "risk_level")
        self._add_if(entry["actions"], rec, "ea", "ea_type", "action_type")

        ev2_id = rec.get("ev2_id")
        if ev2_id is None:
            return
        if ev2_id not in ev2:
            ev2[ev2_id] = {
                "state": {"id": ev2_id, "name": rec["ev2_name"], "description": rec.get("ev2_desc"),
                          "severity": rec.get("ev2_severity", 0), "state_level": rec.get("ev2_level")},
                "phenomena": {}, "risks": {}, "actions": {},
            }
        e2 = ev2[ev2_id]
        self._add_if(e2["phenomena"], rec, "ep2")
        self._add_if(e2["risks"], rec, "er2", "er2_level", "risk_level")
        self._add_if(e2["actions"], rec, "ea2", "ea2_type", "action_type")

    def _format_results(self, raw: dict) -> list[dict]:
        output = []
        for key, item_data in raw.items():
            if item_data["inspection_item"] is None and key.startswith("__state__"):
                # 纯状态输入，构造虚拟检测项条目
                item_data["inspection_item"] = {"id": key, "name": "前端异常状态", "description": ""}

            if item_data["inspection_item"] is None:
                output.append({
                    "inspection_item": {"id": key, "name": "", "description": "未在知识库中找到"},
                    "detected_states": [],
                })
                continue

            detected_states = []
            for state_id, entry in item_data["states"].items():
                se = {
                    "state": entry["state"],
                    "component": entry["component"],
                    "phenomena": list(entry["phenomena"].values()),
                    "risks": list(entry["risks"].values()),
                    "actions": list(entry["actions"].values()),
                    "coupled_states": list(entry["coupled"].values()),
                    "evolved_states": self._flat_evolved(entry["evolved"], entry["evolved2"]),
                }
                detected_states.append(se)

            output.append({
                "inspection_item": item_data["inspection_item"],
                "detected_states": detected_states,
            })
        return output

    def _flat_evolved(self, ev1: dict, ev2: dict) -> list[dict]:
        result = []
        for ev_id, entry in ev1.items():
            ev_state = {
                "state": entry["state"],
                "phenomena": list(entry["phenomena"].values()),
                "risks": list(entry["risks"].values()),
                "actions": list(entry["actions"].values()),
                "evolved_states": [],
            }
            for ev2_id, e2 in ev2.items():
                ev_state["evolved_states"].append({
                    "state": e2["state"],
                    "phenomena": list(e2["phenomena"].values()),
                    "risks": list(e2["risks"].values()),
                    "actions": list(e2["actions"].values()),
                })
            result.append(ev_state)
        return result


    def get_inspection_items(self) -> list[dict]:
        """获取所有检测项目，按系统分组。"""
        query = """
        MATCH (c:Component)-[:HAS_STATE]->(s:State)-[:DETECTED_BY]->(ins:InspectionItem)
        OPTIONAL MATCH (c)<-[:HAS_COMPONENT]-(sys:System)
        RETURN
            ins.item_id AS id,
            ins.name AS name,
            ins.description AS description,
            ins.method AS method,
            s.state_id AS state_id,
            s.name AS state_name,
            sys.system_id AS system_id,
            sys.name AS system_name
        ORDER BY system_id, id
        """
        try:
            session = self.driver.session()
        except (ServiceUnavailable, OSError) as e:
            raise RuntimeError(f"无法连接Neo4j数据库: {e}") from e

        with session:
            records = list(session.run(query))

        items_by_system: dict[str, dict] = {}
        for rec in records:
            r = dict(rec)
            sys_id = r.get("system_id", "UNKNOWN")
            if sys_id not in items_by_system:
                items_by_system[sys_id] = {
                    "system_id": sys_id,
                    "system_name": r.get("system_name", ""),
                    "items": {},
                }
            ins_id = r["id"]
            if ins_id not in items_by_system[sys_id]["items"]:
                items_by_system[sys_id]["items"][ins_id] = {
                    "id": ins_id,
                    "name": r["name"],
                    "description": r.get("description"),
                    "method": r.get("method"),
                    "states": [],
                }
            items_by_system[sys_id]["items"][ins_id]["states"].append({
                "state_id": r.get("state_id"),
                "state_name": r.get("state_name"),
            })

        result = []
        for sys_id, sys_data in items_by_system.items():
            sys_data["items"] = list(sys_data["items"].values())
            result.append(sys_data)
        result.sort(key=lambda x: x["system_id"])
        return result


    def get_assessment_basis(self) -> str:
        """从 Neo4j 获取评估依据（标准条款列表）。"""
        query = """
        MATCH (sc:StandardClause)
        RETURN sc.standard_code AS code, sc.title AS title
        ORDER BY sc.standard_code, sc.clause_no
        """
        try:
            session = self.driver.session()
        except (ServiceUnavailable, OSError) as e:
            raise RuntimeError(f"无法连接Neo4j数据库: {e}") from e
        with session:
            records = list(session.run(query))
        seen = set()
        lines = []
        for r in records:
            d = dict(r)
            key = d["code"]
            if key not in seen:
                seen.add(key)
                lines.append(f"{d['code']} {d['title']}")
        return "\n".join(lines) if lines else "GB/T 42615-2023 在用电梯安全评估规范"


kg_service = KnowledgeGraphService()

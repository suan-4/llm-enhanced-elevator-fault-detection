"""电梯故障知识图谱 — CSV 导入 Neo4j 脚本"""
import csv
from neo4j import GraphDatabase

URI = "bolt://127.0.0.1:7687"
AUTH = ("neo4j", "12345678")
CSV_DIR = "../elevator_kg_csv"

driver = GraphDatabase.driver(URI, auth=AUTH)


def load_csv(filename):
    with open(f"{CSV_DIR}/{filename}", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def run(session):
    # === 节点 ===
    print("Creating nodes...")
    for row in load_csv("systems.csv"):
        session.run("CREATE (:System {system_id: $id, name: $name, description: $desc})",
                     id=row["system_id"], name=row["system_name"], desc=row.get("description"))

    for row in load_csv("components.csv"):
        session.run("CREATE (:Component {component_id: $id, name: $name, system_id: $sys, alias: $alias, importance: toInteger($imp), description: $desc})",
                     id=row["component_id"], name=row["component_name"], sys=row.get("system_id"), alias=row.get("alias"), imp=row.get("importance", 0), desc=row.get("description"))

    for row in load_csv("states.csv"):
        session.run("CREATE (:State {state_id: $id, name: $name, component_id: $cid, state_level: $lv, severity: toInteger($sev), description: $desc})",
                     id=row["state_id"], name=row["state_name"], cid=row.get("component_id"), lv=row.get("state_level"), sev=row.get("severity", 0), desc=row.get("description"))

    for row in load_csv("inspection_items.csv"):
        session.run("CREATE (:InspectionItem {item_id: $id, name: $name, description: $desc, method: $method})",
                     id=row["item_id"], name=row["item_name"], desc=row.get("description"), method=row.get("method"))

    for row in load_csv("phenomena.csv"):
        session.run("CREATE (:FaultPhenomenon {phenomenon_id: $id, name: $name, description: $desc, observation_method: $method})",
                     id=row["phenomenon_id"], name=row["phenomenon_name"], desc=row.get("description"), method=row.get("observation_method"))

    for row in load_csv("risks.csv"):
        session.run("CREATE (:RiskEvent {risk_id: $id, name: $name, risk_level: $lv, severity: toInteger($sev), description: $desc})",
                     id=row["risk_id"], name=row["risk_name"], lv=row.get("risk_level"), sev=row.get("severity", 0), desc=row.get("description"))

    for row in load_csv("actions.csv"):
        session.run("CREATE (:CorrectiveAction {action_id: $id, name: $name, action_type: $type, description: $desc})",
                     id=row["action_id"], name=row["action_name"], type=row.get("action_type"), desc=row.get("description"))

    for row in load_csv("clauses.csv"):
        session.run("CREATE (:StandardClause {clause_id: $id, standard_code: $code, clause_no: $no, title: $title, content_summary: $summary, verified: $v})",
                     id=row["clause_id"], code=row.get("standard_code"), no=row.get("clause_no"), title=row.get("title"), summary=row.get("content_summary"), v=row.get("verified", "false").lower() == "true")

    for row in load_csv("evidence.csv"):
        session.run("CREATE (:Evidence {evidence_id: $id, name: $name, source_type: $type, source_ref: $ref, reliability: toFloat($rel)})",
                     id=row["evidence_id"], name=row["evidence_name"], type=row.get("source_type"), ref=row.get("source_ref"), rel=row.get("reliability", "0"))

    # === 索引 ===
    print("Creating indexes...")
    for label in ["System", "Component", "State", "InspectionItem", "FaultPhenomenon", "RiskEvent", "CorrectiveAction"]:
        prop = {"System": "system_id", "Component": "component_id", "State": "state_id",
                 "InspectionItem": "item_id", "FaultPhenomenon": "phenomenon_id",
                 "RiskEvent": "risk_id", "CorrectiveAction": "action_id"}[label]
        session.run(f"CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})")

    # === 关系 ===
    print("Creating relationships...")
    id_to_label = {}
    for label, prop, csv_file in [
        ("System", "system_id", "systems.csv"),
        ("Component", "component_id", "components.csv"),
        ("State", "state_id", "states.csv"),
        ("InspectionItem", "item_id", "inspection_items.csv"),
        ("FaultPhenomenon", "phenomenon_id", "phenomena.csv"),
        ("RiskEvent", "risk_id", "risks.csv"),
        ("CorrectiveAction", "action_id", "actions.csv"),
        ("StandardClause", "clause_id", "clauses.csv"),
        ("Evidence", "evidence_id", "evidence.csv"),
    ]:
        for row in load_csv(csv_file):
            id_to_label[row[prop]] = label

    rels = load_csv("relationships.csv")
    total = len(rels)
    for i, row in enumerate(rels):
        from_id, rel_type, to_id = row["from_id"], row["relation_type"], row["to_id"]
        from_label = id_to_label.get(from_id)
        to_label = id_to_label.get(to_id)
        if not from_label or not to_label:
            continue
        from_prop = {"System": "system_id", "Component": "component_id", "State": "state_id",
                      "InspectionItem": "item_id", "FaultPhenomenon": "phenomenon_id",
                      "RiskEvent": "risk_id", "CorrectiveAction": "action_id",
                      "StandardClause": "clause_id", "Evidence": "evidence_id"}[from_label]
        to_prop = {"System": "system_id", "Component": "component_id", "State": "state_id",
                    "InspectionItem": "item_id", "FaultPhenomenon": "phenomenon_id",
                    "RiskEvent": "risk_id", "CorrectiveAction": "action_id",
                    "StandardClause": "clause_id", "Evidence": "evidence_id"}[to_label]
        session.run(
            f"MATCH (a:{from_label} {{{from_prop}: $from_id}}) "
            f"MATCH (b:{to_label} {{{to_prop}: $to_id}}) "
            f"CREATE (a)-[:{rel_type} {{confidence: toFloat($conf), description: $desc}}]->(b)",
            from_id=from_id, to_id=to_id, conf=row.get("confidence", "1.0"), desc=row.get("description", ""))
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{total} relationships...")

    print("Done!")


if __name__ == "__main__":
    with driver.session() as session:
        # Clear existing data
        session.run("MATCH (n) DETACH DELETE n")
        run(session)
    driver.close()

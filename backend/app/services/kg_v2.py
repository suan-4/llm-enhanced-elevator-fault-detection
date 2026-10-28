"""v2 知识图谱检索（GraphRAG 风格）与证据装配。

只依赖标准库：读取 tools/kg/build_index.py 生成的 backend/data/kg_v2.sqlite。
本版本只提供检索/摘要/选择日志，不改变现有报告生成链路。
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
import threading
import time
import unicodedata
from pathlib import Path

from app.config import settings

BACKEND_DIR = Path(__file__).resolve().parents[2]
JTE_ITEMS = BACKEND_DIR / "app" / "data" / "jte_items.json"

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
]
SYSTEM_KEYWORDS = [
    (["制动器", "制动", "闸瓦", "抱闸"], "制动系统"),
    (["限速器", "安全钳", "缓冲器", "超速", "安全开关", "安全触点"], "安全保护系统"),
    (["门", "门锁", "地坎", "门机", "门扇"], "门系统"),
    (["钢丝绳", "悬挂", "曳引", "减速箱", "减速器", "联轴器", "电动机", "电机", "驱动主机"], "曳引与悬挂系统"),
    (["导轨", "导靴", "轨线"], "导向系统"),
    (["轿厢", "轿架", "轿壁", "轿顶", "轿底", "对重"], "轿厢与对重系统"),
    (["控制柜", "电气", "接地", "接线", "电缆", "开关", "编码器", "变频器"], "电气控制系统"),
    (["机房", "井道", "底坑", "滑轮间", "通风", "照明"], "机房井道与底坑环境"),
    (["应急", "盘车", "救援", "对讲", "报警"], "应急救援与通信系统"),
]

MECH_TERMS = [
    "裂纹", "断裂", "折断", "变形", "磨损", "锈蚀", "腐蚀", "松动", "脱落", "卡阻", "卡涩",
    "卡滞", "咬合", "脱扣", "误动作", "不动作", "动作迟滞", "间隙", "行程", "位移", "弯曲",
    "拉长", "伸长", "渗漏", "泄漏", "油污", "污染", "过热", "发热", "异响", "噪声", "振动",
    "短路", "断路", "接触不良", "绝缘", "老化", "失效", "失灵", "破损", "开裂", "点蚀",
    "胶合", "剥落", "起皮", "润滑", "缺油", "乳化", "堵塞", "积水", "潮湿", "打滑", "滑移",
    "制动力", "保持力", "夹持力", "张力", "通断", "信号", "编码", "反馈", "触点", "线圈",
    "电压", "电流", "破裂", "缺损", "脱焊", "烧蚀", "击穿", "漏电", "失步", "漂移", "抖动",
]
SYNONYMS = {
    "卡涩": ["卡滞", "卡阻", "发涩", "不灵活"],
    "卡滞": ["卡涩", "卡阻", "发涩", "不灵活"],
    "卡阻": ["卡涩", "卡滞", "卡住", "不灵活"],
    "锈蚀": ["腐蚀", "生锈", "锈损"],
    "腐蚀": ["锈蚀", "生锈", "锈损"],
    "磨损": ["磨耗", "磨伤", "拉伤"],
    "松动": ["松脱", "松了", "不紧", "晃动"],
    "脱落": ["脱开", "掉", "掉落"],
    "断裂": ["折断", "裂断", "断了"],
    "裂纹": ["开裂", "裂缝", "龟裂"],
    "变形": ["翘曲", "弯曲", "扭曲", "鼓包"],
    "漏油": ["渗油", "渗漏", "泄漏"],
    "异响": ["噪声", "杂音", "响声"],
    "不动作": ["不动作", "没动作", "拒动"],
    "回位慢": ["不能复位", "复位慢", "返回慢"],
}
GENERIC = ["电梯", "安全", "要求", "规定", "符合", "不符合", "情况", "工作", "正常", "存在",
           "影响", "导致", "可能", "发生", "进行", "检查", "检验", "装置", "设备", "人员",
           "单位", "使用", "维护", "保养", "应该", "需要", "以及", "一个", "两个", "至少"]


def _norm(text: str) -> str:
    s = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"[\s，,。；;、:：/（）()【】\[\]]+", "", s)


def _bigrams(text: str) -> set[str]:
    s = _norm(text)
    return {s[i:i + 2] for i in range(max(0, len(s) - 1))}


def _dice(a: set[str], b: set[str]) -> float:
    return 2 * len(a & b) / (len(a) + len(b)) if a and b else 0.0


def _json_list(value: str | None) -> list:
    try:
        data = json.loads(value or "[]")
        return data if isinstance(data, list) else []
    except (TypeError, ValueError):
        return []


class KgV2Service:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loaded = False
        self._db_path: Path | None = None
        self._paths: list[dict] = []
        self._path_by_id: dict[str, dict] = {}
        self._components: dict[str, dict] = {}
        self._clauses: dict[str, dict] = {}
        self._lexicon: list[str] = []
        self._jte: dict[str, dict] = {}
        self._meta: dict[str, str] = {}
        self._error = ""

    # ── 加载 ────────────────────────────────────────────────
    @property
    def db_path(self) -> Path:
        p = Path(settings.kg_v2_db)
        return p if p.is_absolute() else BACKEND_DIR / p

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    @property
    def business_db_path(self) -> Path:
        p = Path(settings.sqlite_path)
        return p if p.is_absolute() else BACKEND_DIR / p

    def _load(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            if not self.db_path.exists():
                raise FileNotFoundError(f"知识图谱索引不存在：{self.db_path}")
            conn = self._connect()
            try:
                self._paths = [dict(r) for r in conn.execute("SELECT * FROM path")]
                self._components = {r["component_id"]: dict(r) for r in conn.execute("SELECT * FROM component")}
                self._clauses = {r["clause_id"]: dict(r) for r in conn.execute("SELECT * FROM clause")}
                self._meta = {r["key"]: r["value"] for r in conn.execute("SELECT * FROM meta")}
            finally:
                conn.close()
            self._path_by_id = {p["path_id"]: p for p in self._paths}
            # 预计算路径文本/2-gram，避免每次检索重复归一化 1,052 条路径
            for p in self._paths:
                text = self._path_text(p)
                p["_text"] = text
                p["_norm_text"] = _norm(text)
                p["_bg"] = _bigrams(text)
            try:
                self._jte = {str(it["no"]): it for it in json.loads(JTE_ITEMS.read_text(encoding="utf-8")).get("items", [])}
            except (OSError, ValueError):
                self._jte = {}
            self._build_lexicon()
            self._loaded = True

    def _build_lexicon(self) -> None:
        terms: set[str] = set(MECH_TERMS) | set(COMP_TERMS)
        for p in self._paths:
            for name in [p.get("component_name") or "", p.get("system_name") or "", p.get("action_name") or ""]:
                for part in re.split(r"[与及、和/（(）)]+", name):
                    part = _norm(part)
                    if 2 <= len(part) <= 14:
                        terms.add(part)
            for state in _json_list(p.get("state_names")):
                for part in re.split(r"[：:；;，,、。]+", str(state)):
                    part = _norm(part)
                    if 2 <= len(part) <= 16:
                        terms.add(part)
        for key, vals in SYNONYMS.items():
            terms.add(key)
            terms.update(v for v in vals if len(v) >= 2)
        # 长词优先
        self._lexicon = sorted(terms, key=len, reverse=True)

    def status(self) -> dict:
        try:
            self._load()
        except FileNotFoundError as exc:
            return {"available": False, "error": str(exc), "db_path": str(self.db_path)}
        return {
            "available": True,
            "db_path": str(self.db_path),
            "kg_version": self._meta.get("kg_version", ""),
            "built_at": self._meta.get("built_at", ""),
            "paths": len(self._paths),
            "components": len(self._components),
            "items": len(self._jte),
            "engine": "tfidf-lite + lexicon + graph-expansion",
        }

    # ── 查询解析 ────────────────────────────────────────────
    def _extract_terms(self, text: str) -> list[str]:
        n = _norm(text)
        found: list[str] = []
        for term in self._lexicon:
            if len(found) >= 24:
                break
            if len(term) >= 2 and term in n and term not in found:
                found.append(term)
        # 结构类表述扩展：把「未分成至少两组」映射到「双组/两组/独立」等检索词
        structural = {
            "两组": ["双组", "两组", "独立", "分组"],
            "双组": ["双组", "两组", "独立", "分组"],
            "独立": ["独立", "双组", "两组"],
            "电气装置": ["电气", "触点", "接触器"],
            "安全开关": ["安全开关", "安全触点", "电气安全"],
            "回位": ["复位", "回位", "返回"],
        }
        for key, words in structural.items():
            if key in n:
                for w in words:
                    if w not in found:
                        found.append(w)
        # 同义词补全
        for base, syns in SYNONYMS.items():
            if base in n:
                for s in syns:
                    if s not in found and len(found) < 28:
                        found.append(s)
        return found

    def _item_terms(self, item_no: str, item_name: str) -> list[str]:
        name = self._jte.get(item_no, {}).get("name") or item_name or ""
        terms = [t for t in self._lexicon if len(t) >= 2 and t in _norm(name)]
        return terms[:8]

    def _item_system(self, item_no: str, item_name: str) -> str:
        name = self._jte.get(item_no, {}).get("name") or item_name or ""
        for words, system in SYSTEM_KEYWORDS:
            if any(w in name for w in words):
                return system
        return ""

    def _path_text(self, p: dict) -> str:
        return " ".join(filter(None, [
            p.get("path_summary"), p.get("mechanism_steps"), p.get("trigger_condition"),
            p.get("barrier_condition"), p.get("inspection_method"),
            p.get("corrective_action"), p.get("verification_after_action"),
            p.get("risk_name"), p.get("component_name"), p.get("item_name"),
            p.get("state_names"),
        ]))

    # ── 检索 ────────────────────────────────────────────────
    def retrieve(self, *, item_no: str, reasons: list[str] | None = None,
                 other_text: str = "", item_name: str = "", top_k: int = 3) -> dict:
        self._load()
        reasons = [r for r in (reasons or []) if r]
        query = " ".join([item_name or self._jte.get(item_no, {}).get("name", ""), *reasons, other_text]).strip()
        terms = self._extract_terms(query)
        if not query:
            raise ValueError("请先选择情形或填写其他描述")
        qb = _bigrams(query)
        item_terms = self._item_terms(item_no, item_name)
        item_system = self._item_system(item_no, item_name)
        scored: list[tuple[float, dict]] = []
        for p in self._paths:
            text = p["_text"]
            norm_text = p["_norm_text"]
            dice = _dice(qb, p["_bg"])
            hit_weight = 0.0
            hits: list[str] = []
            for t in terms:
                if t in norm_text:
                    hits.append(t)
                    hit_weight += 1.0 + min(len(t), 6) / 8.0
            comp = p.get("component_name") or ""
            comp_bonus = 0.0
            for t in item_terms:
                if t in comp:
                    comp_bonus += 0.06
            # 命中项在部件/检查/整改字段额外加权
            field_bonus = 0.0
            for field in ("component_name", "inspection_method", "corrective_action", "risk_name"):
                fv = _norm(p.get(field) or "")
                field_bonus += sum(0.03 for t in terms if t in fv)
            term_score = min(1.0, hit_weight / 12.0)
            system_bonus = 0.10 if item_system and item_system in (p.get("system_name") or "") else 0.0
            score = (0.42 * term_score + 0.18 * dice + 0.14 * min(comp_bonus, 0.30)
                     + 0.08 * min(field_bonus, 0.12) + system_bonus)
            if score <= 0:
                continue
            scored.append((score, {**p, "_hits": hits[:8], "_dice": dice}))
        scored.sort(key=lambda x: -x[0])
        # 图邻域扩展：与 Top10 共享状态/部件的路径加权
        seeds = scored[:10]
        seed_states = set()
        seed_components = set()
        for _, p in seeds:
            seed_states.update(_json_list(p.get("state_ids")))
            seed_components.add(p.get("component_id"))
        expanded: list[tuple[float, dict]] = []
        for score, p in scored:
            bonus = 0.0
            shared_states = seed_states & set(_json_list(p.get("state_ids")))
            bonus += min(0.06, 0.01 * len(shared_states))
            if p.get("component_id") in seed_components:
                bonus += 0.02
            expanded.append((score + bonus, p))
        expanded.sort(key=lambda x: -x[0])
        # 多样性：优先不同部件，避免三条一模一样的路径
        picked: list[tuple[float, dict]] = []
        used_components: set[str] = set()
        for score, p in expanded:
            if len(picked) >= top_k:
                break
            if p.get("component_id") in used_components:
                continue
            picked.append((score, p))
            used_components.add(p.get("component_id"))
        if len(picked) < top_k:
            for score, p in expanded:
                if p not in picked:
                    picked.append((score, p))
                if len(picked) >= top_k:
                    break
        candidates = [self._candidate_payload(rank, score, p, terms) for rank, (score, p) in enumerate(picked, 1)]
        return {
            "item_no": item_no,
            "item_name": item_name or self._jte.get(item_no, {}).get("name", ""),
            "item_system": item_system,
            "query": query,
            "query_terms": terms,
            "candidates": candidates,
            "summary": self._summarize(candidates),
            "meta": {"engine": "kg_v2", "kg_version": self._meta.get("kg_version", ""),
                     "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%S")},
        }

    def _candidate_payload(self, rank: int, score: float, p: dict, terms: list[str]) -> dict:
        clause = self._clauses.get(p.get("clause_id") or "", {})
        return {
            "rank": rank,
            "score": round(float(score), 4),
            "path_id": p["path_id"],
            "path_summary": p.get("path_summary") or "",
            "system": p.get("system_name") or "",
            "component": p.get("component_name") or "",
            "states": _json_list(p.get("state_names")),
            "mechanism_steps": _json_list(p.get("mechanism_steps")),
            "trigger_condition": p.get("trigger_condition") or "",
            "barrier_condition": p.get("barrier_condition") or "",
            "risk": p.get("risk_name") or "",
            "inspection": p.get("inspection_method") or "",
            "acceptance_basis": p.get("acceptance_basis") or "",
            "action": p.get("corrective_action") or "",
            "verification": p.get("verification_after_action") or "",
            "clause": {
                "standard_code": clause.get("standard_code", ""),
                "clause_no": clause.get("clause_no", ""),
                "title": clause.get("title", ""),
                "legal_status": clause.get("legal_status", ""),
            } if clause else {},
            "confidence": p.get("confidence", 0.4),
            "verified": p.get("verified", "false"),
            "evidence_class": p.get("evidence_class", ""),
            "source_refs": _json_list(p.get("source_refs")),
            "matched_terms": [t for t in terms if t in (p.get("_norm_text") or _norm(self._path_text(p)))][:8],
        }

    def _summarize(self, candidates: list[dict]) -> dict:
        systems = sorted({c["system"] for c in candidates if c["system"]})
        components = sorted({c["component"] for c in candidates if c["component"]})
        mechanisms: list[str] = []
        for c in candidates:
            for t in MECH_TERMS:
                if t in _norm(c["path_summary"] + c["action"] + " ".join(c["mechanism_steps"])) and t not in mechanisms:
                    mechanisms.append(t)
        actions = [c["action"] for c in candidates if c["action"]]
        text = ""
        if candidates:
            text = (
                f"候选路径集中在{'、'.join(systems) or '相关系统'}，涉及{'、'.join(components[:3]) or '相关部件'}。"
                f"常见演化环节：{'、'.join(mechanisms[:4]) or '见各路径'}。"
                f"风险：{'；'.join(sorted({c['risk'] for c in candidates if c['risk']})[:2]) or '见各路径'}。"
                f"处置方向：{'；'.join(actions[:2]) or '见各路径'}。"
            )
        return {
            "text": text,
            "systems": systems,
            "components": components,
            "mechanisms": mechanisms[:8],
            "count": len(candidates),
        }

    def evidence(self, path_ids: list[str]) -> dict:
        self._load()
        picks = []
        for pid in path_ids:
            p = self._path_by_id.get(pid)
            if p:
                picks.append(self._candidate_payload(0, 0.0, p, []))
        return {"count": len(picks), "paths": picks,
                "note": "工程候选，confidence=0.4，verified=false；仅作为报告附页候选证据"}

    # ── 选择日志 ────────────────────────────────────────────
    def log_selection(self, *, report_id: str | None, item_no: str, item_name: str,
                      query: str, path_id: str | None, decision: str,
                      rank: int | None, top3: list[dict] | None,
                      operator: str = "", selection_source: str = "human",
                      model_path_id: str | None = None, model_reason: str = "") -> int:
        self._load()
        conn = sqlite3.connect(self.business_db_path, timeout=10)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS kg_selection(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_id TEXT, item_no TEXT, item_name TEXT, query_text TEXT,
                    path_id TEXT, decision TEXT, rank_selected INTEGER,
                    top3_json TEXT, operator TEXT, created_at TEXT,
                    kg_version TEXT)
            """)
            for col, ddl in (("selection_source", "TEXT"),
                             ("model_path_id", "TEXT"),
                             ("model_reason", "TEXT")):
                try:
                    conn.execute(f"ALTER TABLE kg_selection ADD COLUMN {col} {ddl}")
                except sqlite3.OperationalError:
                    pass
            cur = conn.execute(
                "INSERT INTO kg_selection(report_id,item_no,item_name,query_text,path_id,decision,"
                "rank_selected,top3_json,operator,created_at,kg_version,selection_source,"
                "model_path_id,model_reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (report_id, item_no, item_name, query, path_id, decision, rank,
                 json.dumps(top3 or [], ensure_ascii=False), operator,
                 time.strftime("%Y-%m-%dT%H:%M:%S"), self._meta.get("kg_version", ""),
                 selection_source, model_path_id, model_reason),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


kg_v2 = KgV2Service()

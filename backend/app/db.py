"""业务数据库（SQLite）：账号、会话、报告、编号流水、审计。

结构版本用 SQLite 自带的 `PRAGMA user_version` 记录，不建版本表：
    0 = 旧结构（users / sessions / report_history / form_draft）
    1 = v1 基础版（5 张表，迁移脚本跑完才置 1）

分工：Neo4j 仍是知识图谱的唯一存储；本模块只承载业务数据，
与图谱互不影响。只使用标准库 sqlite3 —— 板端离线部署不新增任何依赖。

SQL 只允许出现在 `app/repo/` 目录里（见《数据库设计 v1》§6），本模块除外：
这里只负责连接、PRAGMA、事务与建表。
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.config import settings

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _resolve_db_path() -> Path:
    """sqlite_path 为相对路径时，按 backend/ 目录解析。"""
    p = Path(settings.sqlite_path)
    if not p.is_absolute():
        p = BACKEND_DIR / p
    return p


DB_PATH = _resolve_db_path()

# ── 连接级 PRAGMA ────────────────────────────────────────
# WAL + synchronous=FULL：板端断电是常态，宁可慢一点也不能丢已提交的数据。
# foreign_keys：SQLite 默认是关的，开了外键才真的生效。
_PRAGMAS = (
    "PRAGMA journal_mode = WAL",
    "PRAGMA synchronous = FULL",
    "PRAGMA foreign_keys = ON",
    "PRAGMA busy_timeout = 10000",
    "PRAGMA temp_store = MEMORY",
)

# ── v1 基础版结构（5 张表）────────────────────────────────
# 字段与约束的说明见 docs/design/数据库设计-v1.md §4
SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS account (
    id                   INTEGER PRIMARY KEY,            -- 雪花 ID
    username             TEXT    NOT NULL,
    display_name         TEXT    NOT NULL,
    employee_no          TEXT    NOT NULL DEFAULT '',
    password_salt        TEXT    NOT NULL,
    password_hash        TEXT    NOT NULL,
    password_algo        TEXT    NOT NULL DEFAULT 'pbkdf2_sha256$120000',
    role                 TEXT    NOT NULL DEFAULT 'inspector',
    is_active            INTEGER NOT NULL DEFAULT 1,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    created_at           TEXT    NOT NULL,
    created_by           INTEGER REFERENCES account(id),
    last_login_at        TEXT,
    disabled_at          TEXT,
    disabled_by          INTEGER REFERENCES account(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_account_username ON account(username);
CREATE INDEX        IF NOT EXISTS ix_account_active   ON account(is_active);

CREATE TABLE IF NOT EXISTS session (
    token        TEXT    PRIMARY KEY,
    account_id   INTEGER NOT NULL REFERENCES account(id) ON DELETE CASCADE,
    created_at   TEXT    NOT NULL,
    expires_at   TEXT    NOT NULL,
    last_seen_at TEXT,
    origin       TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_session_account ON session(account_id);
CREATE INDEX IF NOT EXISTS ix_session_expires ON session(expires_at);

CREATE TABLE IF NOT EXISTS report (
    id              INTEGER PRIMARY KEY,                 -- 雪花 ID
    report_no       TEXT,
    status          TEXT    NOT NULL DEFAULT 'draft',
    version         INTEGER NOT NULL DEFAULT 1,
    created_by      INTEGER NOT NULL REFERENCES account(id),
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    generated_at    TEXT,
    exported_at     TEXT,
    voided_at       TEXT,
    void_reason     TEXT    NOT NULL DEFAULT '',
    client_name     TEXT    NOT NULL DEFAULT '',
    user_name       TEXT    NOT NULL DEFAULT '',
    device_category TEXT    NOT NULL DEFAULT '',
    product_no      TEXT    NOT NULL DEFAULT '',
    location        TEXT    NOT NULL DEFAULT '',
    assessed_on     TEXT    NOT NULL DEFAULT '',
    form_json       TEXT    NOT NULL DEFAULT '{}',
    items_json      TEXT    NOT NULL DEFAULT '[]',
    counters_json   TEXT    NOT NULL DEFAULT '{}',
    risks_json      TEXT    NOT NULL DEFAULT '{}',
    files_json      TEXT    NOT NULL DEFAULT '[]',
    score           INTEGER,
    grade           TEXT,
    narrative       TEXT    NOT NULL DEFAULT '',
    provenance_json TEXT    NOT NULL DEFAULT '{}',
    catalog_version TEXT    NOT NULL DEFAULT '',
    template_version TEXT   NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_report_no      ON report(report_no) WHERE report_no IS NOT NULL;
CREATE INDEX        IF NOT EXISTS ix_report_created ON report(created_at DESC);
CREATE INDEX        IF NOT EXISTS ix_report_status  ON report(status, created_at DESC);
CREATE INDEX        IF NOT EXISTS ix_report_creator ON report(created_by, created_at DESC);
CREATE INDEX        IF NOT EXISTS ix_report_client  ON report(client_name);
CREATE INDEX        IF NOT EXISTS ix_report_on      ON report(assessed_on);

CREATE TABLE IF NOT EXISTS report_no_seq (
    day      TEXT    PRIMARY KEY,
    last_seq INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY,                     -- 雪花 ID
    at          TEXT NOT NULL,
    actor_id    INTEGER,                                 -- 故意不加外键：删账号不能带走日志
    actor_name  TEXT NOT NULL DEFAULT '',
    event       TEXT NOT NULL,
    target      TEXT NOT NULL DEFAULT '',
    before_json TEXT,
    after_json  TEXT,
    result      TEXT NOT NULL DEFAULT 'ok',
    note        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_audit_at    ON audit_log(at DESC);
CREATE INDEX IF NOT EXISTS ix_audit_event ON audit_log(event, at DESC);
CREATE INDEX IF NOT EXISTS ix_audit_actor ON audit_log(actor_id, at DESC);
"""

# ── 过渡期保留的旧结构 ────────────────────────────────────
# 现有接口（auth / history）还在用这 4 张表。批 2 把接口切到新表、
# 迁移脚本把数据搬过去之后，这一段连同旧表一起删除。
SCHEMA_LEGACY = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    display_name  TEXT    NOT NULL DEFAULT '',
    password_salt TEXT    NOT NULL,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'inspector',
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT    NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS report_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at   TEXT NOT NULL,
    time_label   TEXT NOT NULL DEFAULT '',
    reg          TEXT NOT NULL DEFAULT '',
    location     TEXT NOT NULL DEFAULT '',
    items_count  INTEGER NOT NULL DEFAULT 0,
    states_count INTEGER NOT NULL DEFAULT 0,
    report_text  TEXT NOT NULL DEFAULT '',
    fault_chain  TEXT,
    form_data    TEXT,
    items_data   TEXT
);
CREATE INDEX IF NOT EXISTS idx_history_user ON report_history(user_id, id DESC);

CREATE TABLE IF NOT EXISTS form_draft (
    user_id    INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    form_data  TEXT NOT NULL DEFAULT '{}',
    items_data TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);
"""


@contextmanager
def get_conn():
    """一次短连接 = 一次事务。

    项目并发极低（一个人用一个终端），短连接够用且没有跨线程问题。
    写操作统一走这里：正常结束提交、异常回滚。
    注意：不要在同一个线程里嵌套打开两个连接做写操作（会互等锁）。
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    for pragma in _PRAGMAS:
        try:
            conn.execute(pragma)
        except sqlite3.DatabaseError:  # 例如只读介质上打不开 WAL，不影响读
            pass
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """建表（幂等），供启动时调用。不修改 user_version —— 版本由迁移脚本负责。"""
    with get_conn() as conn:
        conn.executescript(SCHEMA_V1)
        conn.executescript(SCHEMA_LEGACY)


def user_version() -> int:
    """结构版本：0=旧结构，1=v1 基础版（迁移完成）。"""
    with get_conn() as conn:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])


def set_user_version(version: int) -> None:
    with get_conn() as conn:
        conn.execute(f"PRAGMA user_version = {int(version)}")


# 带雪花主键的业务表（session 的主键是令牌，不算）
ID_TABLES = ("account", "report", "audit_log")


def max_business_id() -> int | None:
    """各业务表 MAX(id) 的全局最大值。

    启动时用它给雪花生成器设下界 —— 这是"重启后时钟回到 2021 年也不发重号"
    的关键（设计 §5.2 第 1 道防线）。
    """
    values: list[int] = []
    with get_conn() as conn:
        for table in ID_TABLES:
            row = conn.execute(f"SELECT MAX(id) AS m FROM {table}").fetchone()
            if row is not None and row["m"] is not None:
                values.append(int(row["m"]))
    return max(values) if values else None

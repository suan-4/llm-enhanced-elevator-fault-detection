"""业务数据库（SQLite）：用户账号、登录会话、报告历史、填写记录。

分工说明：
  - Neo4j 仍然是知识图谱（系统 / 部件 / 状态 / 风险 / 措施）的唯一存储；
  - 本模块只承载业务数据，与图谱互不影响。

只使用 Python 标准库 sqlite3：ARM64 板端离线部署无需新增任何依赖，
也不会像 Neo4j 那样引入 JVM 依赖。
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

_SCHEMA = """
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
    """每次操作打开一个短连接：本项目并发极低，够用且没有跨线程问题。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """建表（幂等），供启动时调用。"""
    with get_conn() as conn:
        conn.executescript(_SCHEMA)

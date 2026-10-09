from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "12345678"

    rkllm_server_url: str = "http://127.0.0.1:8080/rkllm_chat"
    rkllm_timeout: int = 600
    rkllm_temperature: float = 0.7
    rkllm_max_new_tokens: int = 512

    # ── 业务数据库（用户账号 / 报告历史 / 填写记录）──
    # 相对路径按 backend/ 目录解析；知识图谱仍在 Neo4j
    sqlite_path: str = "data/elevator.db"
    session_ttl_hours: int = 168          # 登录令牌有效期，默认 7 天
    history_limit: int = 50               # 每个用户保留的历史报告条数

    # 自助终端：前端「退出系统」按钮是否可用（关闭 kiosk 窗口返回桌面）
    kiosk_exit_enabled: bool = True

    # 首次启动时自动创建的管理员（登录后请立即修改口令）
    admin_username: str = "admin"
    admin_password: str = "admin123"
    admin_display_name: str = "系统管理员"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

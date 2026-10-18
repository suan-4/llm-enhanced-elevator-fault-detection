from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "12345678"

    rkllm_server_url: str = "http://127.0.0.1:8080/rkllm_chat"
    rkllm_timeout: int = 600
    # 连接超时单独设：模型服务"假死"（端口在但不响应）时，
    # 不能拿 600 秒的读取超时去等连接，否则报告生成会被卡住
    rkllm_connect_timeout: float = 5.0
    rkllm_temperature: float = 0.7
    rkllm_max_new_tokens: int = 512
    rkllm_context_tokens: int = 4096
    rkllm_template_reserve_tokens: int = 128
    rkllm_model_id: str = "Qwen3.5-4B_W8A8_RK3588"
    # Relative to backend/. Assets and successful calibration are offline deployment artifacts.
    rkllm_tokenizer_path: str = "data/tokenizers/qwen3.5-4b/tokenizer.json"
    rkllm_calibration_path: str = "data/tokenizers/qwen3.5-4b/calibration.json"

    # ── 业务数据库（用户账号 / 报告历史 / 填写记录）──
    # 相对路径按 backend/ 目录解析；知识图谱仍在 Neo4j
    sqlite_path: str = "data/elevator.db"
    session_ttl_hours: int = 168          # 登录令牌绝对有效期，默认 7 天
    session_idle_hours: int = 8           # 空闲多久算掉线（板端是共用终端）
    history_limit: int = 50               # 每个用户保留的历史报告条数

    # ── 新结构（v1 基础版）──
    worker_id: int = 1                    # 雪花 ID 的工作节点号（一台终端一个值）
    report_no_prefix: str = "GDSEI-JTE"   # 报告编号前缀：{前缀}-{YYYYMMDD}-{3 位流水}
    recovery_key_path: str = "/userdata/elevator/recovery.key"  # 忘记口令用的恢复口令文件
    app_version: str = "1.1.0"            # 对外展示的版本号（关于页 / setup 状态）
    backup_dir: str = "/userdata/backup"  # 备份产物目录
    backup_keep: int = 10                 # 本地保留最近几份备份
    export_dir: str = "/home/user/导出"   # PDF/Word 落盘目录（退出到桌面可取走）
    institution_name: str = "广东省特种设备检测研究院佛山检测院"  # 报告与界面署名
    worker_id_note: str = ""              # 占位：多台终端时在部署文档里登记

    # 自助终端：前端「退出系统」按钮是否可用（关闭 kiosk 窗口返回桌面）
    kiosk_exit_enabled: bool = True

    # 首次启动时自动创建的管理员（登录后请立即修改口令）
    admin_username: str = "admin"
    admin_password: str = "admin123"
    admin_display_name: str = "系统管理员"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

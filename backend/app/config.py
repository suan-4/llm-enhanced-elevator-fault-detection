import json
from pathlib import Path

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
    rkllm_max_new_tokens: int = 1024
    rkllm_context_tokens: int = 4096
    rkllm_template_reserve_tokens: int = 128
    rkllm_model_id: str = "Qwen3.5-4B_W8A8_RK3588"
    # Relative to backend/. Assets and successful calibration are offline deployment artifacts.
    rkllm_tokenizer_path: str = "data/tokenizers/qwen3.5-4b/tokenizer.json"
    rkllm_calibration_path: str = "data/tokenizers/qwen3.5-4b/calibration.json"

    # ── 业务数据库（用户账号 / 报告历史 / 填写记录）──
    # 相对路径按 backend/ 目录解析；知识图谱仍在 Neo4j
    sqlite_path: str = "data/elevator.db"
    # v2 知识图谱只读检索库（tools/kg/build_index.py 生成）；相对路径按 backend/ 解析
    kg_v2_db: str = "data/kg_v2.sqlite"
    # T3/T4 提示词链路开关：有勾选候选路径且模型可用时启用；无证据时走快速规则分析
    kg_prompt_enabled: bool = True
    # 生成前是否人工选择候选故障路径；关闭后由 AI 从 Top3 候选中自动判断
    manual_kg_selection: bool = True
    # 人工确认页「直接全权 AI」时，拼入提示词的候选数
    ai_prompt_candidate_count: int = 3
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


BACKEND_DIR = Path(__file__).resolve().parent.parent
# 系统设置「基本配置」写入的运行时覆盖；.env 是部署基线，这里优先级更高。
# 文件不存在/损坏时安静回退到 .env，避免一个坏 JSON 把服务卡在启动阶段。
RUNTIME_CONFIG_PATH = BACKEND_DIR / "data" / "runtime_config.json"


def load_runtime_overrides(path: Path | None = None) -> dict:
    target = Path(path) if path is not None else RUNTIME_CONFIG_PATH
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def apply_runtime_overrides(instance: Settings, values: dict) -> list[str]:
    """只应用 Settings 上确实存在的字段；未知键忽略（旧文件不会把启动搞挂）。"""
    applied: list[str] = []
    for key, value in values.items():
        if hasattr(instance, key):
            setattr(instance, key, value)
            applied.append(key)
    return applied


settings = Settings()
apply_runtime_overrides(settings, load_runtime_overrides())

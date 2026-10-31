"""系统设置「基本配置」：可编辑项的校验、持久化与即时生效。

设计取舍：
- .env 是部署基线（板端出厂/现场部署时写死），运行时覆盖写到
  backend/data/runtime_config.json（.gitignore 已忽略），启动时在 config.py 里
  叠加到 Settings 上，优先级高于 .env；
- 只允许白名单里的键被修改，类型/范围/格式全部在服务端校验 —— 前端只是表单，
  不能提交任意 Settings 字段；
- 改动默认即时生效（settings 是进程内共享对象），少数在启动时固化的项
  （雪花 ID 的 worker_id）返回 restart 标记，由界面提示重启；
- 每次修改写一条 config_update 审计（before/after），便于追溯是谁改了终端配置。
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from threading import RLock
from pathlib import Path

from app import db
from app.config import (
    RUNTIME_CONFIG_PATH,
    apply_runtime_overrides,
    settings,
)
from app.services import audit_service
from app.services.storage_paths import separate_storage, storage_directory

_UPDATE_LOCK = RLock()

_MODEL_NAME = "Qwen3.5-4B / RKLLM"

# 可编辑项白名单：key 必须与 Settings 字段同名
SPECS: list[dict] = [
    {
        "key": "institution_name", "label": "机构名称", "type": "str",
        "desc": "报告与界面署名", "min_length": 1, "max_length": 64, "restart": False,
    },
    {
        "key": "report_no_prefix", "label": "报告编号前缀", "type": "str",
        "desc": "编号格式：{前缀}-{YYYYMMDD}-{3 位流水}，只允许字母、数字和连字符",
        "pattern": r"^[A-Za-z0-9-]{2,20}$", "restart": False,
    },
    {
        "key": "export_dir", "label": "导出目录", "type": "str", "ui": "directory",
        "desc": "PDF/Word 落盘位置（退出系统后可取走），可点「选择…」打开系统目录选择框",
        "min_length": 1, "max_length": 512, "restart": False,
    },
    {
        "key": "backup_dir", "label": "备份目录", "type": "str", "ui": "directory",
        "desc": "备份产物目录，可点「选择…」打开系统目录选择框",
        "min_length": 1, "max_length": 512, "restart": False,
    },
    {
        "key": "backup_keep", "label": "备份保留份数", "type": "int",
        "desc": "本地保留最近几份备份", "min": 1, "max": 100, "restart": False,
    },
    {
        "key": "session_ttl_hours", "label": "会话有效期（小时）", "type": "int",
        "desc": "登录令牌绝对有效期", "min": 1, "max": 720, "restart": False,
    },
    {
        "key": "session_idle_hours", "label": "空闲掉线（小时）", "type": "int",
        "desc": "空闲多久算掉线（共用终端建议保持较短）", "min": 1, "max": 168, "restart": False,
    },
    {
        "key": "worker_id", "label": "工作节点号", "type": "int",
        "desc": "雪花 ID 的机器位；多台终端必须不同。修改后需重启后端生效",
        "min": 0, "max": 1023, "restart": True,
    },
    {
        "key": "kiosk_exit_enabled", "label": "允许退出系统", "type": "bool",
        "desc": "是否允许在界面上退出到桌面", "restart": False,
    },
    {
        "key": "manual_kg_selection", "label": "人工选择候选故障路径", "type": "bool",
        "desc": "启用：生成前进入人工确认页，可手动选择路径、展开 AI 推荐或直接拼接候选；关闭：AI 自动选择候选路径并生成",
        "restart": False,
    },
    {
        "key": "ai_prompt_candidate_count", "label": "AI 提示词候选项拼接数", "type": "int",
        "desc": "人工确认页选择「将前 N 个候选拼接进提示词」时使用；默认 3，范围 1–9",
        "min": 1, "max": 9, "restart": False,
    },
]

SPEC_BY_KEY = {spec["key"]: spec for spec in SPECS}


def _current(key: str):
    return getattr(settings, key)


def _coerce(spec: dict, raw) -> object:
    """按白名单类型转换并校验；失败抛 ValueError（消息可直接展示）。"""
    label = spec["label"]
    kind = spec["type"]

    if kind == "str":
        if not isinstance(raw, str):
            raise ValueError(f"{label} 必须是文本")
        value = raw.strip()
        if not value:
            raise ValueError(f"{label} 不能为空")
        if "\x00" in value:
            raise ValueError(f"{label} 含非法字符")
        if "min_length" in spec and len(value) < spec["min_length"]:
            raise ValueError(f"{label} 至少 {spec['min_length']} 个字符")
        if "max_length" in spec and len(value) > spec["max_length"]:
            raise ValueError(f"{label} 不能超过 {spec['max_length']} 个字符")
        if spec.get("pattern") and not re.fullmatch(spec["pattern"], value):
            raise ValueError(f"{label} 格式不正确")
        return value

    if kind == "int":
        if isinstance(raw, bool):
            raise ValueError(f"{label} 必须是整数")
        if isinstance(raw, int):
            value = raw
        elif isinstance(raw, str) and re.fullmatch(r"-?\d+", raw.strip()):
            value = int(raw.strip())
        else:
            raise ValueError(f"{label} 必须是整数")
        if "min" in spec and value < spec["min"]:
            raise ValueError(f"{label} 不能小于 {spec['min']}")
        if "max" in spec and value > spec["max"]:
            raise ValueError(f"{label} 不能大于 {spec['max']}")
        return value

    if kind == "bool":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, int) and raw in (0, 1):
            return bool(raw)
        if isinstance(raw, str) and raw.strip().lower() in ("true", "false"):
            return raw.strip().lower() == "true"
        raise ValueError(f"{label} 必须是布尔值")
    raise ValueError(f"{label} 类型不受支持")


def readonly_items() -> list[dict]:
    """只读系统信息：不可配置，不混进「基本配置」，由「关于本机」展示。"""
    return [
        {"key": "app_version", "label": "系统版本", "value": settings.app_version,
         "editable": False, "type": "str", "desc": "对外展示的版本号", "restart": False},
        {"key": "model", "label": "大模型", "value": _MODEL_NAME,
         "editable": False, "type": "str", "desc": "模型不可用或分析校验失败时，自动采用固定四段规则分析", "restart": False},
        {"key": "sqlite_path", "label": "业务库路径", "value": settings.sqlite_path,
         "editable": False, "type": "str", "desc": "SQLite 业务库位置（部署时确定）", "restart": False},
    ]


def items() -> list[dict]:
    """基本配置页数据：只有白名单内的可编辑项，只读信息见 readonly_items()。"""
    result: list[dict] = []
    for spec in SPECS:
        item = dict(spec)
        item.update({"value": _current(spec["key"]), "editable": True})
        result.append(item)
    return result


def _sync_side_effects(values: dict) -> None:
    """少数在别处被固化成模块常量的项，改完顺手同步。"""
    if "export_dir" in values:
        # export_service 的 EXPORT_DIR 是导出落盘使用的目录常量（也便于测试替换）
        from app.services import export_service

        export_service.EXPORT_DIR = Path(str(values["export_dir"]))


def _atomic_write(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=target.name + '.', suffix='.tmp', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _persist(values: dict, path: Path | None = None) -> None:
    target = Path(path) if path is not None else RUNTIME_CONFIG_PATH
    merged = {}
    try:
        merged = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(merged, dict):
            merged = {}
    except (OSError, ValueError):
        merged = {}
    merged.update(values)
    _atomic_write(target, json.dumps(merged, ensure_ascii=False, indent=1).encode('utf-8'))


def update(values: dict, *, actor: dict | None = None, path: Path | None = None) -> dict:
    """保存基本配置。校验全部通过才写入，避免半套配置落盘。"""
    with _UPDATE_LOCK:
        return _update(values, actor=actor, path=path)


def _update(values: dict, *, actor: dict | None, path: Path | None) -> dict:
    if not isinstance(values, dict) or not values:
        raise ValueError("没有需要保存的配置")
    unknown = [key for key in values if key not in SPEC_BY_KEY]
    if unknown:
        raise ValueError("未知配置项：" + "、".join(unknown))

    coerced = {key: _coerce(SPEC_BY_KEY[key], raw) for key, raw in values.items()}
    if {'export_dir', 'backup_dir'} & coerced.keys():
        for key in ('export_dir', 'backup_dir'):
            if key in coerced and coerced[key] != _current(key):
                coerced[key] = str(storage_directory(str(coerced[key])))
        separate_storage(Path(str(coerced.get('export_dir', settings.export_dir))),
                         Path(str(coerced.get('backup_dir', settings.backup_dir))))
    before = {key: _current(key) for key in coerced}
    changed = {key: value for key, value in coerced.items() if before[key] != value}
    if not changed:
        return {"updated": [], "restart_required": [], "items": items()}

    target = Path(path) if path is not None else RUNTIME_CONFIG_PATH
    snapshot = target.read_bytes() if target.exists() else None
    # A failed write must never change the running service.
    _persist(changed, path)
    try:
        with db.get_conn() as conn:
            apply_runtime_overrides(settings, changed)
            _sync_side_effects(changed)
            audit_service.record(
                conn, "config_update", actor=actor, target="settings",
                before=before, after=changed, note="基本配置更新：" + "、".join(changed),
            )
    except Exception:
        apply_runtime_overrides(settings, before)
        _sync_side_effects(before)
        if snapshot is None:
            target.unlink(missing_ok=True)
        else:
            _atomic_write(target, snapshot)
        raise

    restart = [key for key in changed if SPEC_BY_KEY[key]["restart"]]
    return {"updated": list(changed), "restart_required": restart, "items": items()}

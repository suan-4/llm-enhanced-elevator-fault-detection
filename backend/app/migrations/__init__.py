"""结构迁移。

版本号记在 SQLite 自带的 `PRAGMA user_version` 里（不建版本表）：
    0 = 旧结构（users / sessions / report_history / form_draft）
    1 = v1 基础版（account / session / report / report_no_seq / audit_log）

为什么迁移脚本里可以直接写 SQL（而平时"SQL 只准出现在 repo 里"）：
迁移要处理的是**历史结构**，而 repo 描述的是**当前结构**。
把历史结构塞进 repo 会让 repo 同时背着新旧两套表，得不偿失。
"""
from app.migrations import legacy_to_v1  # noqa: F401

__all__ = ["legacy_to_v1"]

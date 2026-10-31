# kg-prompt-v1 落成记录

日期：2026-10-27　状态：模板、校验器、T3/T4 接入已落成；默认关闭，待真实模型验证。

## 1. 评审决定

1. T4 与现有 NARRATIVE_SYSTEM **并存**：模型可用走 T3/T4，不可用/校验失败走现有规则降级；
2. 候选路径**只进附页**：T4 正文不传路径、不出现 path_id/演化链；T3 结果只用于附录/导出；
3. 先落成模板 + 校验器 + 接入开关；默认关闭，不改变现有报告结果。

## 2. 新增文件

- backend/app/services/kg_prompt.py
  - PROMPT_VERSION = kg-prompt-v1
  - SYSTEM_BASE
  - build_t1_query_prompt / build_t2_rerank_prompt
  - build_t3_item_prompt（逐项证据归纳）
  - build_t4_overview_prompt（正文，不含路径）
  - build_t5_validation_prompt（可选）
- backend/app/services/kg_validation.py
  - parse_json_output
  - validate_t3：path_ids 白名单、fault_chain 必须是证据状态有序子序列、
    action 必须与证据一致、禁止新增条款/数值、禁止「已确认/违反」等表述；
  - validate_t4：字段/长度、正文禁止 path_id/候选路径、不得新增数值/条款、
    key_findings 必须引用 item_no、limitations 必须标注候选/复核；
- backend/tests/test_kg_prompt.py（9 个测试）
- tools/kg/prompt_smoke.py（4 个真实样例冒烟）
- tools/kg/run_prompt_tests.py（无 pytest 环境运行测试）

## 3. 实测结果

处理命令：

    $env:PYTHONIOENCODING='utf-8'
    python tools/kg/prompt_smoke.py
    python tools/kg/run_prompt_tests.py

结果：

- 冒烟：5.1 制动器、1.9 限速器、7.2 门扇、自由文本「柱塞发涩松闸回位慢」全部 PASS；
- 每个 T3 提示词约 1,650–1,800 字符（单条路径），适合 4,096 context；
- 校验器正例通过；反例分别报：
  - PATH_NOT_ALLOWED（伪造 path_id）
  - ACTION_NOT_GROUNDED（整改措施不在证据中）
  - SCHEMA_INVALID（状态链不在证据里）
  - PATH_NOT_ALLOWED / NUMBER_NOT_ALLOWED（T4 正文出现路径/新数值）
- 测试：9/9 PASS。

## 4. T3/T4 接入

- report_workflow.py 新增 _run_kg_prompt_flow：有勾选证据时先 T3 逐项、再 T4 正文；
- 配置开关 kg_prompt_enabled，默认 False；只有开关打开 + 勾选路径 + use_llm 才触发；
- 任一步失败自动回退现有 NARRATIVE_SYSTEM + _kg_appendix；
- T3 输出用于附页（_t3_appendix），T4 正文不传路径；
- provenance 增加 kg_prompt_enabled / kg_prompt_used / kg_prompt_version / kg_prompt_errors / kg_prompt_validation；
- 假模型冒烟：T3/T4 成功结果 used=true，正文与附页生成；模型返回非法 JSON 时 used=false，回退；
- 假模型完整生成（kg_prompt_enabled=true）：T3/T4 成功，provenance.kg_prompt_used=true、
  kg_prompt_version=kg-prompt-v1、validation passed；narrative 含 T4 正文，附页含 T3 状态链；
- 普通生成（无勾选、use_llm=false）回归：状态 generated，kg_prompt_used=false，kg_available=false。

启用方式（默认关闭）：

    # 环境变量
    $env:KG_PROMPT_ENABLED='true'

或 backend/data/runtime_config.json：

    {"kg_prompt_enabled": true}

只有「开关打开 + 勾选了候选路径 + use_llm=true」三者同时满足才会走 T3/T4。

## 5. 板端联调（2026-10-28）

- 新版本：origin/main 未更新（仍在 9de3d54），最新版本是 PR #12 分支 codex/offline-keyboard；
  本成果以 feat/kg-v2-keyboard 分支叠加在其上，无冲突（main.py 同时注册 input/kg 路由）。
- 板端部署：push.bat 推送前端/后端 + kg_v2.sqlite 索引进 backend/data；
  健康检查、就绪探针、首页均 200。
- 板端 KG API：/api/kg/status available=true，paths=1052，items=66；
  5.1 / 1.9 / 7.2 candidates 与本地一致。
- 板端 UI 流程：主页面 → 校验并生成报告 → /kg-confirm（1 项不符合，Top3）→
  勾选 → 生成 → 报告查看；截图 board-kg-confirm.png / board-kg-report.png。
- 真实 RKLLM（板端）T3/T4 实测：
  - 首次：T4 key_findings 超 80 字，校验失败并触发回退，耗时 120s；
  - 修复：normalize_t4 截断 + T4 失败时保留 T3 附页且不再重复调用模型；
  - 复测：92.5s，llm_used=true，kg_prompt_used=true，prompt_version=kg-prompt-v1，
    validation passed；正文为 T4 概述、附页为 T3 状态链，正文无 path_id。
  - 测试后已把板端 runtime_config.json 恢复为 kg_prompt_enabled=false（默认关闭）。

## 6. 尚未做

- 未做 T3 批量（1–3 项/次）的调度；
- 未把 T3 结果渲染进 Word 独立附页（当前仍追加在叙述末尾）；
- T4 正文与规则概况的 A/B 对比尚未做。

## 7. 下一步

1. 用 20–30 个真实案例记录 JSON 合法率、action 一致率、T3/T4 耗时；
2. 把 T3 结果落到 Word 附页模板；
3. 评估是否把 kg_prompt_enabled 在板端长期开启（当前单次约 90s）。

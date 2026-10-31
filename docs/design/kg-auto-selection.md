# 人工选择候选故障路径：可配置开关

日期：2026-10-31
状态：已实现；板端本次未连接，待重新连接后部署验证。

## 1. 配置项

基本配置新增：

    人工选择候选故障路径

- 默认：启用；
- 启用：生成前进入「故障路径确认」页，人工从 Top3 中勾选；
- 关闭：不进入确认页，AI 直接读取 Top3 自动判断后生成报告。

配置键：manual_kg_selection（bool，即时生效）。

## 2. 人工模式（保留原流程）

1. 点「校验并生成报告」；
2. 保存草稿；
3. 跳转 /kg-confirm；
4. 用户为每个不符合项选择 Top3 或「无合适候选」；
5. 写 kg_selection 审计；
6. 生成报告。

## 3. 自动模式（关闭开关）

1. 点「校验并生成报告」；
2. 保存草稿；
3. 对每个不符合项取 Top3；
4. 每 3 项批量调用 /api/kg/recommend/batch；
5. 模型从 Top3 中选择一条或 none；
6. 自动写 kg_selection 审计（selection_source=model/rule）；
7. 用这些选择生成报告，不再弹出人工确认页。

模型失败时：该项降级为「无合适候选」，继续生成，不在前端阻塞。

## 4. 保留人工确认的边界

- 自动模式下仍然把 Top3 完整候选拼接进模型提示词；
- 模型不是自由生成路径，只能从 Top3 选择或 none；
- 选中路径仍会在报告里标注候选证据、未签核；
- 报告生成仍可使用规则回退；
- 人工模式不受影响。

## 5. 代码位置

- backend/app/config.py: manual_kg_selection
- backend/app/services/runtime_config.py: 基本配置白名单
- web/src/views/SettingsView.vue: 基本配置自动渲染 bool
- web/src/views/ReportView.vue: loadSelectionMode / autoSelectKg / generate 分支
- web/src/api/kg.ts: fetchKgRecommendationBatch

## 6. 待办

- 板端重新连接后执行 push.bat 部署；
- 板端设置里关闭「人工选择候选故障路径」；
- 用一份含不符合项的草稿验证：不弹确认页、自动生成、审计含 Top3 与最终 path_id。

# 报告生成前「图谱候选勾选」流程验收

日期：2026-10-26　状态：本地端到端已跑通。

## 1. 目标流程

```
主页面勾选/填写（不符合项、其他）
      ↓ 点「校验并生成报告」
故障路径确认页（/kg-confirm）
      ↓ 每个不符合项 Top3 → 人工勾选 / 无合适候选
      ↓ 点「生成报告」
生成报告并跳回报告查看页
```

没有不符合项时保持原流程直接生成，不进入确认页。

## 2. 实测记录

使用本地草稿：报告 107124294529585152（1 项不符合：1.7）。

1. 主页面显示「共 66 项　已评 66 项　不符合 1 项　未填 0 项」；
2. 点「校验并生成报告」→ 跳转 `#/kg-confirm`；
3. 确认页显示：
   - 评估项 1.7 机房工作安全空间；
   - 不符合情形原文；
   - Top3 候选 + 「无合适候选」；
   - 进度 0/1 → 选中后 1/1；
4. 点「生成报告」→ 跳回 `#/?section=reports&report=107124294529585152`；
5. 报告状态 `generated`，得分、等级、风险正常生成；
6. 报告叙述末尾出现：

```
附：故障演化候选证据（操作员勾选，未签核）
- 机房井道与底坑环境 / 机房通风与温度控制：...
  风险：电气或机械过热损伤风险
  整改：恢复批准通风条件
  复验：...
  相关要求（待核验）：TSG T5002—2017 附件A 表A-1 序号1；PDF第7页
以上为工程候选，confidence=0.4，verified=false，需人工审核。
```

7. provenance：

```json
{"kg_available": true, "kg_note": "已引用操作员勾选的候选路径",
 "kg_paths": ["PATH_V2_ENV_f4db1343dec08d"], "kg_selection_count": 1}
```

截图：

![故障路径确认页](kg-confirm-flow.png)

![生成后的报告页](kg-report-after.png)

## 3. 改动

- 主页面 `ReportView.vue`：有不符合项时先保存草稿并跳 `/kg-confirm`；无不符合项走原流程；
- 新增 `KgConfirmView.vue`：逐项 Top3、人工勾选/无候选、进度、生成；
- `stores/report.ts` / `api/reports.ts`：生成请求带 `kg_selections`；
- 后端 `schemas.py` / `api/reports.py` / `report_workflow.py`：
  - 接收人工选择；
  - 调 `kg_v2.evidence()` 组装受控证据；
  - 证据进入 prompt（kg_evidence）；
  - 叙述末尾追加确定性的候选证据附录；
  - provenance 记录 `kg_available/kg_note/kg_paths/kg_selection_count`；
- `api/kg.py`：选择日志写业务库 `kg_selection`。

## 4. 当前限制

1. 候选证据目前追加在叙述末尾，尚未做进 Word 模板的独立附页，需要后续模板落位；
2. 检索质量依赖词面/图先验；样例 1.7 的 Top1 是「机房通风与温度控制」，与「净高/通道宽度」并不完全对应，操作员应选「无合适候选」或改选（这正是人工确认存在的意义）；
3. 每个不符合项一条主路径；多故障描述尚未拆条；
4. 选择日志已写入，但尚未做「历史选择反哺 Top1」；
5. 未做板端部署。

## 5. 重启方式

```powershell
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8099
```

登录后从主页面录入 → 点「校验并生成报告」即可走完整流程。

# 文末文本分析报告流式输出

日期：2026-10-28　状态：已接入，待板端复测。

> 大模型只负责报告文末的「文本分析报告」；评估概况保持规则事实，不混入模型文字。

## 1. 参考与取舍

参考早期版本 D:\Project\elevator_kg：

- SSE 端点 `/api/report/generate-stream`
- `llm_service.generate_stream()` 解析 RKLLM 的流
- 前端 fetch + reader，边收边渲染 Markdown

当前版本把 T4 文本分析改为纯 Markdown，并直接使用模型流：

- T3 仍走非流式 JSON（逐项证据归纳、校验）；
- T4 使用 `generate_stream`，token 直接转发 SSE，前端 marked 实时渲染；
- 没有候选路径时走快速规则分析，不调用模型；
- 评估概况、风险、得分在最后的 `report` 事件中一次返回。

## 2. 接口

```
POST /api/reports/{id}/generate/stream
Content-Type: text/event-stream
```

事件：

```json
{"type":"text","text":"本次评估共发现 ..."}
{"type":"report","report":{ ...完整报告... }}
{"type":"error","message":"..."}
```

- 有候选路径时，T4 的 Markdown token 以 `text` 事件实时发送；
- 无候选路径时走规则分析，直接发 `report`，不等待模型；
- 不发送阶段进度；
- 生成期间每 10 秒发一行 SSE 注释 `: ping`，避免连接被代理提前关闭；
- 完成发送 `data: [DONE]`。

## 3. 前端

- `generateReportStream()`：fetch + ReadableStream 解析 SSE；
- `store.generate(..., onText)`：有回调时走流式接口，否则仍走原 JSON 接口；
- 新增 `StreamingOverlay.vue`：生成中显示“正在生成文末文本分析报告”，逐块追加；
- `KgConfirmView`（勾选后生成）和 `ReportView`（无不符合项直接生成）都已接入；
- 收到 `report` 后走原有报告查看流程；
- 报告查看页/Word 导出在最后新增「文本分析报告」页；评估概况仍使用规则 `narrative`。

## 4. 本地测试

- 用报告 107124294529585152，`use_llm=false`：SSE 正常返回 report 事件；
- 板端真实模型（kg_prompt_enabled=true，报告 107124008851345408）：
  - 真 token 流：首块 58.24s、总 95.97s、367 个 text 块、367 字；
  - `llm_used=true`、`kg_prompt_used=true`、errors=[]；
  - 评估概况 `narrative` 不包含分析正文，二者已分离；
- 前端 `typecheck` / `build` 通过；Word 导出追加分析页已用模板样本验证。

## 5. 板端实测（2026-10-28）

- 部署：push.bat 推送前端/后端 + KG 索引到板端，快照 20261028_210204，健康检查 200；
- 全部「无合适候选」快速路径（报告 103488310063665152，12 项不符合）：
  - 用时 **0.09s**，无 text 块；
  - `analysis_status=rule_only`、`llm_used=false`，生成 1005 字规则 Markdown；
  - 不再等待模型；
- 有候选路径、真实 RKLLM token 流（报告 107124008851345408）：
  - T3 改为程序组装后，首块 **7.56s**、总 **44.7s**、**367 块 / 367 字**；
  - `llm_used=true`、`kg_prompt_used=true`、errors=[]；
  - 输出为 Markdown（标题、段落、列表），前端用 marked 解析；
- 前端 StreamingOverlay 已随 push.bat 构建；报告查看页/Word 末尾有「文本分析报告」页；
- 板端查看页验证 Markdown 已渲染（标题/加粗/列表）；
- 板端 `kg_prompt_enabled` 已改为 true；代码默认值也改为 true。

## 6. 限制

1. T3 已改为程序组装，不再调用模型；T4 是真实 token 流，首块约 7–8s（取决于模型）；
2. 全部无候选时直接规则分析，不调用模型，故 0.09s 完成；
3. 生成失败时 SSE 返回 error 事件，前端提示后仍可用普通接口重试；
4. 自动化 UI 测试受板端草稿状态影响，尚未截到“生成中”覆盖层；接口层已完整验证。

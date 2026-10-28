# 文末文本分析报告流式输出

日期：2026-10-28　状态：已接入，待板端复测。

> 大模型只负责报告文末的「文本分析报告」；评估概况保持规则事实，不混入模型文字。

## 1. 参考与取舍

参考早期版本 D:\Project\elevator_kg：

- SSE 端点 `/api/report/generate-stream`
- `llm_service.generate_stream()` 解析 RKLLM 的流
- 前端 fetch + reader，边收边渲染 Markdown

当前版本生成包含风险评定、T3/T4 JSON、校验与落库，**不把未校验的模型 token 直接渲染**。
因此本版按你的要求：

> 流式输出只做最终文本分析报告；不显示阶段进度，也不显示未校验 JSON。

实现上：生成完成后，SSE 只把 `provenance.analysis_text`（文末文本分析报告）分块发给前端；
评估概况、风险、得分等仍在最后的 `report` 事件中一次返回。

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

- 只有文末文本分析报告会以 `text` 事件分块发送；
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
  - T3/T4 成功，SSE 返回 24 个 text 块、281 字；
  - `provenance.analysis_text` 281 字，`llm_used=true`、`kg_prompt_used=true`；
  - 评估概况 `narrative`（699 字）不包含分析正文，二者已分离；
- 前端 `typecheck` / `build` 通过；Word 导出追加分析页已用模板样本验证。

## 5. 板端实测（2026-10-28）

- 部署：push.bat 推送前端/后端 + KG 索引到板端，快照 20261028_210204，健康检查 200；
- 板端 SSE（kg_prompt_enabled=true，真实 RKLLM，报告 107124008851345408）：
  - 用时 143.7s，24 块、281 字；
  - `llm_used=true`、`kg_prompt_used=true`、`kg_prompt_partial=false`，errors=[]；
  - 分析正文提到 4.3 定转子碰擦、10.2 对重架、12.4 钢丝绳等；
  - `narrative` 仍为规则评估概况，不含分析正文；
- 前端 StreamingOverlay 已随 push.bat 构建；报告查看页/Word 末尾新增「文本分析报告」页；
- 板端查看页验证：文本含「文本分析报告」标题和模型分析正文（截图 board-analysis-page.png）；
- 测试后恢复板端 runtime_config.json 为 kg_prompt_enabled=false。

## 6. 限制

1. 正文要等生成完成才拿到，所以首字延迟 = 生成耗时；这不是模型 token 级流式；
2. 若需要真正的 token 级逐字输出，需要把 T4/最终正文改成可流式解析的纯文本协议，另行设计；
3. 生成失败时 SSE 返回 error 事件，前端提示后仍可用普通接口重试；
4. 自动化 UI 测试受板端草稿状态影响，尚未截到“生成中”覆盖层；接口层已完整验证。

# 最终正文流式输出

日期：2026-10-28　状态：本地 SSE 已跑通，待板端复测。

## 1. 参考与取舍

参考早期版本 D:\Project\elevator_kg：

- SSE 端点 `/api/report/generate-stream`
- `llm_service.generate_stream()` 解析 RKLLM 的流
- 前端 fetch + reader，边收边渲染 Markdown

当前版本生成包含风险评定、T3/T4 JSON、校验与落库，**不把未校验的模型 token 直接渲染**。
因此本版按你的要求：

> 流式输出只做最终正文；不显示阶段进度，也不显示未校验 JSON。

实现上：生成完成后，SSE 只把最终 `narrative` 分块发给前端；其余风险/得分/报告数据
在最后的 `report` 事件中一次返回。

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

- 只有最终正文会以 `text` 事件分块发送；
- 不发送阶段进度；
- 生成期间每 10 秒发一行 SSE 注释 `: ping`，避免连接被代理提前关闭；
- 完成发送 `data: [DONE]`。

## 3. 前端

- `generateReportStream()`：fetch + ReadableStream 解析 SSE；
- `store.generate(..., onText)`：有回调时走流式接口，否则仍走原 JSON 接口；
- 新增 `StreamingOverlay.vue`：生成中显示“正在生成报告正文”，正文逐块追加；
- `KgConfirmView`（勾选后生成）和 `ReportView`（无不符合项直接生成）都已接入；
- 收到 `report` 后走原有报告查看流程。

## 4. 本地测试

- 用报告 107124294529585152，`use_llm=false`：
  - SSE 返回 16 个 text 块，合计 192 字；
  - 收到 report 事件，status=generated；
  - 无 error；
- 前端 `typecheck` / `build` 通过。

## 5. 板端实测（2026-10-28）

- 部署：push.bat 推送前端/后端 + KG 索引到板端，快照 20261028_210204，健康检查 200；
- 板端 SSE（use_llm=false，报告 107124008851345408）：0.7s、59 块、699 字，report 事件正常；
- 板端 SSE（use_llm=true，真实 RKLLM）：19.1s、59 块、699 字，
  llm_used=true，无 error；正文逐块返回；
- 前端 StreamingOverlay 已随 push.bat 构建（dist 中有 StreamingOverlay 资源）；
- 板端 runtime_config.json 保持 kg_prompt_enabled=false。

## 6. 限制

1. 正文要等生成完成才拿到，所以首字延迟 = 生成耗时；这不是模型 token 级流式；
2. 若需要真正的 token 级逐字输出，需要把 T4/最终正文改成可流式解析的纯文本协议，另行设计；
3. 生成失败时 SSE 返回 error 事件，前端提示后仍可用普通接口重试；
4. 自动化 UI 测试受板端草稿状态影响，尚未截到“生成中”覆盖层；接口层已完整验证。

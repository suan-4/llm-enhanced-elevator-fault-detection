# 故障候选 AI 推荐（模式 A）

日期：2026-10-29　状态：已实现，人工确认保留。

## 1. 原则

- AI 只做预选，最终由操作员确认；
- AI 只能从本次 TopK 候选中选；
- 选不出来时返回「无合适候选」；
- 任何推荐都写审计字段，保留责任链。

## 2. 接口

    POST /api/kg/recommend
    {
      "item_no": "4.3",
      "item_name": "电动机",
      "reasons": ["工作表面有裂纹..."],
      "other_text": "",
      "top_k": 3
    }

返回：

    {
      "success": true,
      "recommendation": {
        "path_id": "PATH_V2_...",
        "rank": 1,
        "reason": "裂纹/磨损匹配...",
        "none": false
      }
    }

- 使用 T2 rerank 提示词；
- 程序校验 path_id 必须在候选白名单；
- 模型失败/越界/空选 → none=true，不影响人工选择。

## 3. 前端

- 进入 /kg-confirm 后，候选先展示；
- AI 推荐在后台加载，每行显示「AI 推荐」标签和理由；
- 推荐到达时，如果操作员还没选，自动预选；
- 操作员改选后不会被覆盖；
- 可点「采用」回到 AI 推荐；
- 同时最多 2 个推荐请求，避免 12 项不符合同时压模型。

## 4. 审计

kg_selection 新增：

- selection_source: human / model / human_override
- model_path_id
- model_reason

生成报告前写选择日志；即使日志失败也不阻塞生成。

## 5. 板端实测

- 报告 107124008851345408，项目 4.3：
  - 推荐 rank 1，PATH_V2_TRACTION_4a4101ff465800
  - 理由：聚合物应力开裂导致密集裂纹，匹配工作表面裂纹损伤
  - 耗时 26.28s（4B 模型，单项）
- 审计行已验证：selection_source=model，model_path_id、model_reason 均落库。

## 6. 风险

- 4B 模型推荐质量有限，必须人工确认；
- 多项不符合时推荐是后台任务，操作员可以先人工选择并生成；
- 建议后续统计 human_override 比例，评估模型推荐命中率。

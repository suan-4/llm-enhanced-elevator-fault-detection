# 知识图谱检索 MVP 验收记录

日期：2026-10-26　状态：本地可运行，待体验/决策是否接入正式报告生成。

## 1. 这一版做了什么

- 读取 `backend/data/kg_v2.sqlite`（v2_1000paths：1,052 条路径 / 320 部件 / 66 个 JTE 条目）；
- 新增 GraphRAG 风格检索：
  - 查询词抽取 + 同义词/结构词扩展（如「未分成至少两组」→ 双组/两组/独立）；
  - 评估项部件/系统先验；
  - 关键词加权 + 字符 2-gram 相似度 + 字段加权；
  - 图邻域扩展（共享状态/部件的路径加权）；
  - Top3 去重（优先不同部件）；
  - **系统级摘要**（规则拼装：系统、部件、常见机理、风险、处置方向）；
- 新增前端演示页：`/#/kg-demo`（登录后可用）；
- 人工勾选：选中路径 / 无合适候选，选择写入 `backend/data/elevator.db` 的 `kg_selection` 表；
- 提供「将交给大模型的证据包」预览（只读，不调用模型）。

> 本版**没有**修改现有报告生成流程；生成仍走原 `report_workflow`，不引用图谱。

## 2. 启动与访问

当前临时后端（端口 8099）：

```
http://127.0.0.1:8099/#/kg-demo
```

正常本地后端重启后也可用同路径（`/#/kg-demo`）。

手动启动（在 `backend/` 下）：

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8099
```

## 3. 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/kg/status` | 索引版本/路径数/条目数 |
| POST | `/api/kg/candidates` | 入参 `{item_no, item_name, reasons[], other_text}`，返回 Top3 + 摘要 + 检索词 |
| POST | `/api/kg/select` | 保存人工选择（selected / no_candidate） |
| POST | `/api/kg/evidence` | 按 path_ids 返回证据包 |

示例：

```json
POST /api/kg/candidates
{"item_no":"5.1","item_name":"制动器型式",
 "reasons":["参与向制动面施加制动力的制动器机械部件未分成至少两组设置。"],
 "other_text":""}
```

## 4. 实测结果

| 输入 | Top3 结果 | 评价 |
|---|---|---|
| 5.1 制动器机械部件未分两组 | 1) 手动松闸及双组机械独立性 2) 制动器承载固定 3) 制动衬 | 结构词扩展后命中「双组/独立性」相关路径 |
| 1.9 限速器运行中有异响 | 1) 限速器棘爪棘轮 2) 限速器离心重块 3) 限速器绳轮与夹绳机构 | 三条均为限速器部件，机理为磨损/误动/卡滞 |
| 7.2 门扇严重锈蚀穿孔 | 1) 层门及轿门门扇 2) 门刀与轿门耦合机构 3) 轿门开门限制装置 | Top1 直接命中门扇腐蚀穿孔路径 |
| 其他：制动器柱塞发涩、松闸后回位慢 | 1) 手动松闸及双组机械独立性 2) 制动电磁铁柱塞与衔铁 3) 手动松闸回位弹簧 | 柱塞/松闸/回位词均命中，Top2 为柱塞相关 |

- 单次检索延迟（本机）：**约 30 ms**（优化前约 515 ms；预计算路径文本/2-gram 后下降）；
- 前端：`npm run typecheck` / `npm run build` 通过；960×600 视口可操作；
- API：登录、status、candidates、select、evidence 均返回 200。

截图：

![MVP 概览](kg-demo-mvp-overview.png)

![MVP 结果页](kg-demo-mvp.png)

## 5. 已知限制

1. 未接入报告生成：勾选结果只写日志，不会进入 prompt/附页；
2. 系统级摘要为规则拼装，未调用小模型；
3. 检索是词面/字符相似度 + 图邻域，不是向量检索；口语描述召回可能不足；
4. Top3 可能包含同系统但不同部件的路径，需要人工判断；
5. 还没做「其他」的多路径/拆分；
6. 未做板端部署和触屏尺寸专项优化。

## 6. 下一步（待你确认效果后）

1. 把「故障路径确认」接到生成前：不符合项 + 其他填写均走同一套 Top3 勾选；
2. 生成 prompt 只带勾选路径证据，校验 path_id/措施白名单；
3. 报告附页/查看页展示候选证据，标注「操作员选定、未签核」；
4. 选择日志反哺 Top1 预填与映射表；
5. 板端部署与性能验收。

## 7. 变更文件

- `backend/app/services/kg_v2.py`：检索、摘要、证据、选择日志；
- `backend/app/api/kg.py`、`backend/app/main.py`：KG 路由；
- `backend/app/config.py`：`kg_v2_db`；
- `tools/kg/build_index.py`：索引增加 source_refs；
- `web/src/api/kg.ts`、`web/src/views/KgDemoView.vue`、`web/src/router/index.ts`：演示页；
- `docs/design/知识图谱v2接入与约束生成方案-v1.md`：设计稿（含 7.5/7.6/7.7）。

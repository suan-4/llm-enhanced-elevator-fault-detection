# 原生模板导出实施计划

> **For agentic workers:** 使用 superpowers:executing-plans 在本任务连续实施，不逐项停下来请求确认。

**Goal:** 用户可用完整66项报告测试原模板Word/PDF导出、可靠归档和历史查看。

**Architecture:** 现有FastAPI/Vue接口整体切换到后端报告快照，不新增数据库表。标准库ZIP/DOM仅修改模板允许的单元格；Word直接保存，PDF转换同一DOCX。最终短写事务复核快照，登记文件哈希、归档、审计；持久化pending标记处理文件/数据库中断窗口。

**Tech Stack:** Python标准库、SQLite、FastAPI/Pydantic、Vue3/TS、板端LibreOffice。

## 全局约束与依据

沿用接口设计v1 §3.6及`output/acceptance-template/artifact.md`。不改评分、不改登录/配色、不改正式历史数据、不自动push。当前分支codex/export-column-widths存在上轮修改，继续保留，不切换/重置工作区。不将试验报告写入正式库。

## Task 1 模板构建与快照导出

文件：新增`backend/app/services/native_template.py`、`report_export.py`、`backend/app/data/jte_template.docx`；修改`report_workflow.py`及`api/export.py`；测试`backend/tests/test_native_export.py`。

- [x] RED：`.venv/Scripts/python.exe backend/tests/test_native_export.py`，9项中6项失败；旧契约probe4种无效请求全部被接受。
- [x] GREEN：native_template.build_docx(report) -> bytes，保留ZIP未改部件；report_export.export_report(report_id, version, result_digest, fmt, filename, actor) -> 文件元数据。
- [x] 结果签名包含新生成nonce及真正结果数据；public_report返回签名，旧历史只能在快照结构完整且input_digest有效时导出，不重跑模型。
- [x] 测试完整DOCX内容、状态、旧版本、同输入再生成、审计失败、PDF失败、重复文件和并发变更。

## Task 2 前端联动

文件：`web/src/api/report.ts`、`types/api.ts`、`stores/report.ts`、`utils/export.ts`及相应spec。

- [x] 请求仅传fmt/report_id/version/result_digest/filename；禁止DOM HTML。
- [x] 请求期间冻结快照引用，返回只更新同一份报告的状态；归档后保存不伪称新草稿，切换新建不被无意义保存阻断。
- [x] `npm.cmd test -- --run`、`npm.cmd run build`全绿。

## Task 3 回归、板端转换、交付测试入口

- [x] 全部`backend/tests/test_*.py`、HTTP/浏览器验收；更新导出probe到新契约并保留真正成功/失败断言。
- [x] 隔离板端目录`/userdata/releases/20261020-native-export-01`，独立DB/导出目录/端口；验证完整全符合、多个不符合、长风险文本的实际DOCX/PDF。
- [x] 原模板和产物逐页渲染，核对网格、文本、缺项/重复、页眉页码、公式；发现问题先写回归再修。
- [x] 独立代码复核的两项P2及后续竞态均加回归修复，最终记录通过/未验证，测试入口与样例可用。正式部署和Git推送不自动执行。

## 执行记录

2026-10-20：用户要求一次完成。原模板66项与条目库顺序/名称/要求一致。参考渲染18页含封面空页；按既定要求正文开始，附图无输入不输出。实际参考PDF保留在隔离验收目录。产品构建不增加第三方依赖。

完成记录：见`docs/acceptance/2026-10-20-原生模板导出验收.md`。43项前端、全部后端脚本、75项HTTP、板端6个Word/PDF产物、最终浏览器两视口和全流程走查通过。用户测试入口18087转发到独立板端8087，测试账号acceptance；原8081正式服务未切换。

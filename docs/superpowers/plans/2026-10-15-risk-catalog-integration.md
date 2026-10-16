# 风险目录与评定接入 Implementation Plan

> 2026-10-16：用户已收紧实施范围，本计划中的较大v2接口/快照方案未执行，保留为历史准备记录。当前已上板的小范围实现及验证结果见[本次实施与验收](../../design/风险材料接入-本次实施与验收.md)，不以本计划未勾选任务推断当前系统状态。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 本项目默认由当前代理顺序实施；不因本计划自动开启并行代理。

**Goal:** 在现有系统中接入专家风险选项、完整草稿、已确认的类别汇总和可追溯报告数据，正式计分仅使用已批准规则。

**Architecture:** 专家目录和规则以版本化JSON发布。SQLite仍用现有五张表，通过repo整存输入与生成快照；FastAPI服务端负责校验、汇总和定级，Vue负责录入与展示。模型建议与检验员确认分开，长调用不占SQLite写锁。

**Tech Stack:** FastAPI / Pydantic / SQLite / Python 3.10板端 / Vue 3 / TypeScript / Vite / Vitest；沿用现有LibreOffice导出，不新增运行依赖。

**Spec:** [接口与数据补充](../../design/风险录入与评定-接口与数据补充-v0.1.md)、[PRD变更稿](../../prd/PRD-风险录入与评定变更-v0.1.md)。两份均待评审；本文是实施准备，不是实施完成记录。

## Global Constraints

- 同一个项目最终只有一个风险类别；存在多个风险时，以最严重的类别为准，Ⅰ类 > Ⅱ类 > Ⅲ类。
- 继续使用现有五张业务表；本次不新增业务表、不变更SQLite user_version。
- 风险目录 `I/II/III` 与现有报告 `Ⅰ类/Ⅱ类/Ⅲ类` 由服务端显式映射；Snowflake ID在接口中为字符串。
- 登录和既有白色蓝青色圆角样式不改；连续66项，逻辑600×960与960×600都要可用。
- 审核数据不直接发布；PRD Q1～Q4未解决的路径不得伪装为正式评定。
- 当前仅存最新报告生成快照，不增加完整修订历史；旧图谱41项映射不在本次自动完成范围。
- 不推送Git、不部署板端，除非用户在执行阶段明确要求。

## Review Focus

1. 老客户端/老草稿：新字段不被静默清空，旧风险文字不自动映射ID。测试归Task 2。
2. 快速切换、新建及迟到响应：旧保存或模型结果不覆盖新内容。测试归Task 2～4。
3. 目录升级、停用ID、同项目多选及跨项目ID：按锁定版本校验，未选的严重风险不参与汇总。测试归Task 1、5。
4. 模型返回未知ID、文字注入、超时或空内容：只保留建议、原文和待确认状态，不能修改确定类别。测试归Task 4。
5. 更新目录后重导出、附页多风险、12.4嵌套表：使用原生成快照，措施和阈值无遗漏。测试归Task 6。

## 范围与依赖

Task 1～3可先在开发测试中完成目录能力和草稿录入。Task 4需要确认自由描述及措施采用交互；Task 5正式规则数据发布须先解决PRD Q1～Q4。未具备业务依据时写明未决项，不以演示规则代替。Task 6的正式导出依赖已批准的评定和快照。

运行命令中的python指项目约定的Python环境；不得为跑测试临时升级板端依赖。现有后端测试是可直接运行的脚本；新增测试可用标准库unittest，无需安装pytest。

## Task 1 风险目录加载与发布检查

**Files:** Create `backend/app/services/risk_catalog.py`, `backend/tests/test_risk_catalog.py`; Modify `backend/app/api/report.py`。审核通过后才创建正式 `backend/app/data/risk_catalog.json`、`risk_policy.json`及旧目录归档文件。

**Interfaces:**
- Produces `load_catalog(version: str | None = None, *, data_dir: Path | None = None) -> dict`，返回已发布目录；None目录/未发布抛CatalogUnavailable，未知版本抛LookupError。
- Produces `get_risk(catalog: dict, item_no: str, risk_id: str) -> dict`，查找并验证项目归属和可选状态。
- Produces `load_policy(version: str | None = None, *, data_dir: Path | None = None) -> dict | None`，无已发布规则时返回None，供Task 5明确产生未决issue。
- HTTP `GET /api/report/risk-catalog` 由上述函数提供数据，不直接读审核文件。

- [ ] 写失败测试，使用独立临时目录的合成数据：`test_review_catalog_is_not_published`断言review目录被拒；`test_wrong_item_is_rejected`断言跨项目ID失败；`test_archived_version_preserves_ids`断言重排不换ID、旧版本仍可读；`test_version_cannot_escape_data_dir`断言路径穿越输入无效。
- [ ] 运行 `python -m unittest discover -s backend/tests -p test_risk_catalog.py -v`，确认因能力缺失而失败。
- [ ] 实现目录读取、来源哈希检查、唯一ID、类别枚举、合法项目和原始/规范化类别映射；建立固定版本到文件的白名单，不把请求版本直接拼成路径。
- [ ] 实现路由及503/404；重复运行上述测试应全部PASS。合成发布数据必须位于测试fixture，不进入正式data目录。
- [ ] 仅暂存本任务文件，检查diff后本地提交；不push。

## Task 2 v2完整草稿与内容冲突检查

**Files:** Modify `backend/app/models/schemas.py`, `backend/app/api/reports.py`, `backend/app/main.py`, `backend/app/services/report_workflow.py`, `backend/app/repo/report_repo.py`; Create `backend/app/services/report_state.py`, `backend/tests/test_risk_draft.py`。

**Interfaces:**
- Produces `draft_etag_of(report: dict) -> str`，哈希范围以设计§5为准。
- Add `ItemAnswerV2`, `ReportCreateV2`, `ReportSaveV2`, `OtherMatchInput`, `MeasureChoiceInput`；v2额外字段forbid，客户端不能写analysis和确认人。
- Extend `save_content(..., schema_version: int = 1, risk_catalog_version: str | None = None, draft_etag: str | None = None, upgrade_confirm: bool = False) -> dict`；保持旧参数名，v2必需字段在API模型和service共同验证。
- Extend `create_draft(..., schema_version: int = 1, risk_catalog_version: str | None = None) -> dict`，新v2草稿从创建时就锁定输入版本，无需每次提示升级。
- 创建、读取、保存回传version/ETag及输入版本。使用现有JSON列，repo仍只负责SQL和序列化。

- [ ] 写失败测试：`test_v2_round_trip_keeps_inactive_risks_and_text`断言取消其他勾选仍保存原文；`test_stale_etag_does_not_overwrite`断言第二份旧输入失败且库内新内容不变；`test_client_cannot_forge_analysis`断言422；`test_old_client_cannot_clear_v2_fields`断言拒绝v1写v2；`test_text_change_invalidates_confirmation`断言原确认不再有效；`test_no_new_business_tables`比较前后schema。
- [ ] 运行 `python -m unittest discover -s backend/tests -p test_risk_draft.py -v`，确认新用例失败。
- [ ] 实现v1/v2请求分派、目录版本锁定、显式升级确认、完整保存和服务器字段合并；短事务读-比较-写，失败整体回滚；响应返回真实status/version/ETag。补充report路由的校验异常适配，detail为字符串且issues可定位，认证路由沿用原行为。
- [ ] 重跑新测试及 `python backend/tests/test_repo.py`、`python backend/tests/test_report_workflow.py`。旧断言因正式语义调整而修改时，注明原因，不能删掉遗留保护用例。
- [ ] 检查diff并本地提交，不push。

## Task 3 前端风险ID录入与串行保存

**Files:** Modify `web/src/api/report.ts`, `web/src/api/reports.ts`, `web/src/types/api.ts`, `web/src/domain/validation.ts`, `web/src/stores/report.ts`, `web/src/components/report/ItemRow.vue`, `web/src/utils/http.ts`。Create `web/src/stores/report.spec.ts`; Extend `web/src/domain/validation.spec.ts`。

**Interfaces:**
- `ItemState`增加riskIds、otherMatch、analysis、measureChoices；保留原otherText，独立控制other_enabled。
- `serializeItems()`输出v2答案，`hydrate()`恢复服务端完整状态。
- 保存链返回Promise，`createNew/openReport`先await排空当前保存；提交和响应都绑定报告ID与请求顺序。

- [ ] 写失败测试：`new_report_waits_for_current_save`、`late_response_cannot_replace_current_report`、`switch_result_keeps_inactive_answers`、`save_updates_version_and_etag`、`missing_error_points_to_exact_item`。通过可控Promise模拟迟到响应，断言具体报告ID和状态未串写。
- [ ] 在web目录运行 `npm test -- src/stores/report.spec.ts src/domain/validation.spec.ts`，确认失败。
- [ ] 读取新目录并展示审核通过的风险选项；以risk_id而非原文作key。串行保存，输入中继续变化则排队保存最新内容；ApiError增加code/issues并保持detail旧行为；不改登录、配色和表格边框。
- [ ] 重跑定向测试，然后 `npm run typecheck`、`npm run build`。按600×960和960×600检查选项不唤起软键盘、无白屏、悬浮岛不重叠。
- [ ] 检查diff并本地提交，不push。

## Task 4 自由描述建议与人工确认

**Files:** Create `backend/app/services/risk_analysis.py`, `backend/tests/test_risk_analysis.py`; Modify `backend/app/api/reports.py`, `backend/app/models/schemas.py`, `web/src/api/reports.ts`, `web/src/stores/report.ts`, `web/src/components/report/ItemRow.vue`。

**Interfaces:**
- Produces `async analyze_other(report_id: int, item_no: str, *, version: int, draft_etag: str, actor: dict) -> dict`。
- Add `RiskAnalysisRequest`模型，字段为item_no/version/draft_etag，不接受另一份自由描述原文。
- Uses Task 1目录、Task 2的ETag和保存协议。模型结果只能引用同项目已发布风险ID，风险类别由目录决定。
- New HTTP `POST /api/reports/{id}/risk-analysis`；建议、确认和措施采用按设计§4、§6.2处理。

- [ ] 写失败测试：`unknown_model_risk_is_not_confirmed`、`text_changed_while_model_running_rejects_result`、`model_timeout_preserves_draft`、`manual_match_is_not_marked_as_llm`、`stale_measure_suggestion_is_rejected`。断言模型输出中的伪造类别/措施来源不成为确定规则。
- [ ] 运行 `python -m unittest discover -s backend/tests -p test_risk_analysis.py -v`，确认失败。
- [ ] 实现读取快照、事务外调用、结构化结果验证、提交前ETag复查；不自动确认。复用现有模型客户端，不假设模型服务支持新增结构化输出参数。
- [ ] 前端增加建议查看、拒绝/修改、确认关联；取消或修改文字后立即标记旧确认无效。模型失败保存原文并给出可理解状态。
- [ ] 后端按路由设置推理上限为90秒（现有配置更短时采用更短值），前端该请求timeout设110秒；用模拟超时测试，不通过等待90秒实现测试。保持60秒通用请求默认值不变。
- [ ] 重跑新测试、前端定向测试和typecheck；本地提交，不push。

## Task 5 规则汇总与正式生成

**Files:** Create `backend/app/services/risk_engine.py`, `backend/tests/test_risk_engine.py`; Modify `backend/app/services/risk_rules.py`, `backend/app/services/report_workflow.py`, `backend/app/models/schemas.py`, `backend/tests/test_report_workflow.py`。

**Interfaces:**
- Produces `risk_rules.worst_category(categories: list[str]) -> str | None`，输入规范代码I/II/III，无元素返回None，未知类别报错。
- Produces `risk_engine.assess_items(items: list[dict], catalog: dict, policy: dict | None) -> dict`，返回risks、issues、score、grade；未覆盖规则必须产生issue且score/grade为None。
- Add `ReportGenerateV2`模型；Extend `generate(..., schema_version: int = 1, version: int | None = None, draft_etag: str | None = None) -> dict`；模型前取快照，模型后短事务重查，再分配编号和保存。

- [ ] 写失败测试：`worst_category(['II','I','II']) == 'I'`；`worst_category([]) is None`；未选的I风险不影响实际选择II；同一ID去重但不丢其他风险；缺失规则返回unresolved；符合样例全部与24格矩阵一致；无此项按已批准Q4处理。
- [ ] 运行 `python -m unittest discover -s backend/tests -p test_risk_engine.py -v`，确认失败。
- [ ] 实现类别汇总、规则查取与issue生成。Q1/Q2未批准时只实现“未决不正式生成”的路径，不把不符合样例无条件套到具体风险，不借机改计分公式。
- [ ] 在规则批准后把正式映射和计分口径写进risk_policy，增加每条批准规则的确切结果测试，再替换演示循环。此前不得声称正式算法完成。
- [ ] 扩展生成测试：未决不占号、并发编辑后拒绝旧结果、同输入并发生成不覆盖已提交的不同快照、推理期间规则版本改变拒绝提交、模型失败只影响叙述、同项目多风险快照完整。运行新测试及现有报告工作流测试。
- [ ] 检查diff并本地提交，不push。

## Task 6 同源预览与快照导出

**Files:** Create `backend/app/services/report_renderer.py`, `backend/app/services/report_export.py`, `backend/tests/test_report_snapshot.py`; Modify `backend/app/api/reports.py`, `backend/app/models/schemas.py`, `backend/app/services/export_service.py`, `backend/app/repo/report_repo.py`, `web/src/components/report/ReportDocument.vue`, `web/src/components/report/EvaluationTable.vue`, `web/src/components/report/AppendixPage.vue`, `web/src/types/report.ts`, `web/src/api/reports.ts`, `web/src/views/ReportView.vue`。

**Interfaces:**
- Produces `render_report_html(report: dict) -> str`，仅使用已保存快照并转义所有用户文本，版式沿用JTE报告结构及现有黑白打印样式。
- Produces `export_generated(report_id: int, fmt: str, generation_hash: str, *, actor: dict) -> dict`；复用现有export_service转换，返回文件信息及哈希。
- Add `SnapshotExportRequest`模型，字段fmt/generation_hash。New HTTP `POST /api/reports/{id}/export`；v2前端不再传body_html。

- [ ] 写失败测试：`export_uses_snapshot_after_catalog_update`、`appendix_keeps_each_risk_measure`、`nested_thresholds_survive_render`（断言24/30/34、8/10/11、4/4/4、1/1/1及6d注释保留）、`user_text_is_escaped`、`draft_or_stale_snapshot_cannot_export`、`void_during_conversion_is_not_registered_as_success`。
- [ ] 运行 `python -m unittest discover -s backend/tests -p test_report_snapshot.py -v`，确认失败。
- [ ] 实现生成快照的hash、固定模板渲染、按报告ID导出、文件校验和与登记；SQLite事务不包住LibreOffice进程。测试转换使用fake，不要求本机安装LibreOffice。
- [ ] 前端预览从同一生成快照读取抬头、项目要求、评定和措施，附页key为项目编号+风险ID。空白标题背景、原布局及导出卡片行为保持。
- [ ] 跑新测试、现有 `python backend/tests/test_export_service.py`、前端test/build；开发环境核对窄屏布局。板端再真实导出PDF和Word，打开检查页首表格、12.4阈值表、多风险附页及长文本分页。没有真实打开核对前不得宣称模板版式验收通过。
- [ ] 本地提交，不push。按实际测试结果更新验收记录，列明仍未完成的业务确认和上板项。

## 计划自检

- PRD需求对应：FR-R1对应Task 2～3；FR-R2对应Task 1及发布前审核；FR-R3对应Task 4、6；FR-R4对应Task 5；FR-R5对应Task 2、5、6。
- 存储复杂度：不新增表，业务SQL在repo；v1与v2兼容有边界用例。
- 规则未决：Q1～Q4保留为发布前条件，计划不能替业务人员作答。
- 本轮仅编写设计和计划，以上checkbox均未执行；不得把它们作为代码已完成或验收通过的证据。

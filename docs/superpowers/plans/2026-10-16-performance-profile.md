# 报告生成性能计时 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 当前代理顺序执行；最后一次独立只读复核。

**Goal:** 获得可复核的报告全链路和模型内部耗时，并完成板端三场景基准分析。

**Architecture:** 请求级Trace观测现有业务，模型SDK回调输出真实指标；隔离库基准驱动与浏览器事件分别记录后端/端到端时间。不新增业务表，不修改评定逻辑。

**Tech Stack:** Python标准库、现有httpx/FastAPI/Flask/RKLLM1.3.0、Vue3/TS/Vitest、现有Chromium。

**Spec:** [测量设计](../specs/2026-10-16-performance-profile-design.md)，将用户已确认方案写明，不扩展成性能优化或新的管理界面。

**执行记录（2026-10-17）：** Task1—3实现、测试、提交完成；Task4已完成15次API、3次浏览器、10次导出实测及只读复核，见[实测报告](../../acceptance/2026-10-17-性能测试与分析.md)。下方保留原计划检查项。全程正式数据不变门禁未通过（发现跨日正式库变动，已披露、未恢复覆盖）；因此本轮交付是性能证据和本地候选，不是正式发布或全功能现场验收。不自动合并/push。

## Global Constraints

- 不改评估算法、提示词、采样参数、页面样式；不新增业务表，不读写正式报告。
- 单调时钟，单位ms；缺失SDK统计为null，不用split估算token；各层包含关系不可重复加总。
- 真模型单实例运行；先备份，再短暂重启；不重启整机、不清文件缓存，不修改调频。
- 三场景各至少5次；首次推理与重新加载单列；失败和降级不能作为成功性能样本。
- 不自动push。临时服务结束要停止，正式账号/报告哈希须前后相同。

## Review Focus

- 统计上下文并发或异常后泄漏：Task1测试并行异步上下文隔离/异常重置。
- SDK空指针/缺失/NaN统计伪造速度：Task2测试null及非法数值归一化；异常不得进入ctypes回调。
- 重复注入或上游源码漂移：Task2测试幂等及不匹配拒绝，保留原代码和备份。
- 观测失败破坏报告或吞原业务错误：Task1/3测试异常仍抛出、无观测环境降级无害。
- 汇总把冷启动/失败混入平均数、泄漏敏感输入：Task4固定手算样本测试过滤、分组及输出字段白名单。

### Task 1: 后端Trace与报告分阶段计时

**Files:** Create `backend/app/services/performance.py`, `backend/tests/test_performance.py`; Modify `backend/app/services/report_workflow.py`, `backend/app/services/llm_service.py`, `backend/app/services/export_service.py`.

**Interfaces:** `stage(name, **tags)`上下文、`record_model_call(dict)`、`traced_generation`异步装饰器；返回报告可选`performance={schema_version,total_ms,stages,model_calls}`。`total_ms`包括最终事务提交，旧elapsed_ms不改语义。

- [ ] 先写测试：阶段毫秒正确、异步并发隔离、异常重置；真实临时库生成有最终事务阶段及total>=所有非重叠外层阶段之和；失败仍保持原错误。
- [ ] 运行 `.venv/Scripts/python.exe -X utf8 backend/tests/test_performance.py`，应先FAIL（未提供Trace或生成无performance）。
- [ ] 实现Trace与分段。模型调用不改变字符串返回契约；从现有响应读取有效performance，没统计记null。导出info新增可选performance记录build/convert/publish/total。
- [ ] 重跑上述测试及全部`backend/tests/test_*.py`，全部通过后本地提交。

### Task 2: 模型服务真实计时与可回滚补丁

**Files:** Create `kiosk/rkllm_metrics.py`, `tools/instrument_rkllm.py`, `backend/tests/test_rkllm_metrics.py`.

**Interfaces:** `InferenceMetrics.start()/first_text()/finish()/snapshot()`；补丁`instrument(source: str)->str`返回仅插入观测调用的源码，重复执行不重复插入，不匹配抛ValueError。SDK统计不得修改现有ctypes结构。

- [ ] 写固定时钟测试：200ms首字、1000ms推理墙钟，500ms/100输入token=200token/s，400ms/20输出token=50token/s；非空输出才设首字；空SDK统计不估算；非法值null；原有输出文本不改变。
- [ ] 写最小Flask服务fixture运行补丁（假原生函数，非真实性能证据），验证响应usage/performance、源码幂等、源码漂移拒绝、模型初始计时独立。
- [ ] 先运行测试确认失败，再实现两个小模块及接入补丁；回归全部后端测试。
- [ ] 板端先审计原文件SHA和服务状态，备份至本次performance release；只停一个原模型实例，替换受控文件，重启健康检查。失败回滚程序，不恢复覆盖数据库。

### Task 3: 无视觉变化的前端全链路记录

**Files:** Create `web/src/utils/performance.ts`, `.spec.ts`; Modify `web/src/views/ReportView.vue`, `web/src/stores/report.ts`, `web/src/utils/export.ts`, `web/src/api/reports.ts`.

**Interfaces:** `beginInteraction(name)`返回带`stage/finish`的轻量记录；`elevator:performance`事件只含duration/status/stages，不含表单/正文/token。store生成记录save/generate_http，View在nextTick+缩放+双rAF后finish。

- [ ] 先测无performance API仍安全、异常结束不泄漏、阶段计时、双rAF尚未完成时不冒报预览已显示；观察RED。
- [ ] 实现，保持DOM/CSS/按钮文案不变；运行`npm test`、`npm run build`通过后提交。

### Task 4: 隔离板端基准与分析

**Files:** Create `tools/acceptance/performance_benchmark.py`, `tools/acceptance/performance_browser.js`, `backend/tests/test_performance_benchmark.py`, `docs/acceptance/2026-10-16-性能测试与分析.md`。

**Interfaces:** `summarize(samples)`按case和状态统计n/mean/median/min/max；`--base/--repeat/--output`驱动已初始化隔离库，正文和口令不入结果。单次结果含case/index/status/timing/resource_snapshot；先保存原始记录再汇总。

- [ ] 用固定3条成功/1条失败数据证明平均/中位和失败计数，先RED再实现；源码/工具路径不许读写正式业务库。
- [ ] 备份正式数据并记账号/报告哈希。部署观测候选到隔离API，复用唯一模型；首轮模型重新加载/首次请求单列。
- [ ] 三场景各5次串行，逐条输出进度和原始记录；每次保存指标，测量温度/内存/频率；长任务用短轮询保持进展可见。
- [ ] 浏览器真实点击各场景至少1次，测保存/生成/渲染；导出PDF/Word各5次记录转换和HTTP时间。失败如实保留，不无限重试。
- [ ] 形成分析，注明测量边界/样本量/冷态定义/无法拆分指标。回归测试，独立只读代码复核，停止隔离服务并核对正式数据未变。不自动合并或推送。

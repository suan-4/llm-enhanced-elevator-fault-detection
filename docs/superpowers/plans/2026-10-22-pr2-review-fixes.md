# PR #2 Review Fixes Implementation Plan

> **For agentic workers:** Use the approved review findings as the specification; execute inline, one regression at a time. This plan changes behavior at the failing boundaries and preserves the PR's UI design.

**Goal:** 修复 PR #2 审查确认的六项问题，保持队友的分组、方案与设置页面设计。

**Architecture:** 在 PR #2 的独立 worktree 中修复；配置服务负责验证/持久化顺序，备份与导出服务保护文件系统，报告 store 负责初始状态落库，组件暴露展开条目的接口。浏览器存储错误由 store 返回并由页面展示；Linux 目录选择仅在存在桌面会话时运行。

**Tech Stack:** Vue 3 / Pinia / TypeScript / FastAPI / SQLite / Python unittest / Vitest / Playwright。

**Evidence:** 原始审查位于主工作区 output/playwright/pr2-review-aa0c6d2/review.md；复现文件保持原样。

## Tasks

- [x] 目录保护：新增 `backend/tests/test_pr2_regressions.py`，先确认根目录/嵌套路径/备份清理/已有目录权限用例失败；修复后通过。新目录要求绝对路径，拒绝系统/用户根目录和应用代码目录；导出与备份互不嵌套；清理只删除校验通过的自有备份；已有目录不改属主权限。
- [x] 配置失败原子性：真实不可写目标与审计异常用例先失败后通过。配置写盘成功后才修改进程状态；审计失败恢复文件与内存。用锁串行化更新，唯一临时文件 fsync + replace。
- [x] 新建落库：`baseInfoPersistence.spec.ts` 验证新建及首次进入前明确保存抬头；补充保存失败重试同一草稿用例，先失败后通过。
- [x] 方案存储失败：存储配额错误不改变方案列表，最后使用键失败时回滚；页面显示失败并保留重试入口。单测与浏览器均通过。
- [x] 折叠漏填定位：`ItemTable.expandItem(no)` 先展开，ReportView 等待渲染再定位；两个视口浏览器验证通过。
- [x] 目录窗口失败：无显示环境不可用、启动异常可见、取消非错误用例通过；读取已知 kiosk 用户显示环境。EM-R16 独立模块实机验证选择中文目录、取消均通过，证据已入验收记录；整套 UI 尚未部署。
- [x] 回归与交付：后端全部12份独立脚本、前端41项测试、类型检查/构建、两个竖屏浏览器检查通过；修复分支与验收记录保留，未推送、合并或部署。

## Shared interfaces

- 目录验证与配置更新共同使用 settings 的最终 export_dir/backup_dir；先验证整套候选值再写盘。
- 方案持久化先提交存储再修改方案列表；新建落库只保存当前生效的完整表单与评价状态。
- ItemTable 保有折叠状态，ReportView 仅调用 expandItem，不复制折叠状态。

## Commands

`python backend/tests/test_pr2_regressions.py`：先失败，修复后通过。

`node web/node_modules/vitest/vitest.mjs run --root web`：新增存储/落库测试先失败，修复后全部通过。

`node web/node_modules/vue-tsc/bin/vue-tsc.js --noEmit -p web/tsconfig.json` 与 `node web/node_modules/vite/bin/vite.js build web`：通过。

`node tools/acceptance/pr2_regressions.js`：仅访问独立测试后端，两个视口均通过。

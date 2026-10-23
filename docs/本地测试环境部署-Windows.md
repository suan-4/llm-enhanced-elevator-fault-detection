# Windows 本机测试环境（前端 + 后端）

> 状态：2026-10-22 在本机部署并验收通过。
> 范围：**只搭前端 + 后端**，不含 RKLLM 推理端（本机没有 RK3588 NPU）。
> 板端部署（离线、systemd、kiosk）见 README.md 与 kiosk/README.md，两者互不影响。

## 1. 当前拓扑

| 组件 | 地址 / 位置 | 说明 |
|---|---|---|
| 系统入口（前端 + API） | http://127.0.0.1:8081 | FastAPI 同源伺服 web/dist，前端与后端一个端口 |
| 后端 API | http://127.0.0.1:8081/api | uvicorn，入口 app.main:app |
| 业务库 | backend\data\elevator.db | SQLite（WAL），账号 / 报告 / 审计 / 草稿 |
| 知识图谱 | bolt://127.0.0.1:7687，HTTP http://127.0.0.1:7474 | Neo4j 2026.05.0，Windows 服务名 neo4j |
| 大模型（RKLLM） | 未启动 | 后端连接失败会自动降级为规则摘要；诊断页显示 warn 属预期 |
| Vite 开发服务器（可选） | http://127.0.0.1:5173 | 热更新用，/api 代理到 8081；需要时加 -Dev 启动 |

运行时文件全部收在 backend\data\ 下（.gitignore 已忽略）：

    backend\data\elevator.db        业务库（含 -wal / -shm）
    backend\data\backups\           系统备份产物
    backend\data\exports\           PDF/Word 导出目录
    backend\data\logs\              启动日志与 PID 文件
    backend\data\recovery.key       恢复口令（未生成，按需生成）

## 2. 本机环境基线

| 项 | 实际值 |
|---|---|
| 操作系统 | Windows 11 (AMD64) |
| Python | D:\miniconda3\envs\elevator_kg\python.exe（Python 3.10.0，依赖已装） |
| Node.js / npm | v24.10.0 / 11.18.0 |
| Neo4j | D:\Program Files\neo4j-community-2026.05.0，Windows 服务 neo4j（手动启动） |
| 图谱数据 | 302 节点 / 392 关系（System 6、InspectionItem 41、State 67、Component 51、FaultPhenomenon 31、RiskEvent 21、CorrectiveAction 42、StandardClause 22、Evidence 21） |

配置来自 **backend\.env**（已被 .gitignore 忽略，不要提交）。要点：

- NEO4J_URI=bolt://127.0.0.1:7687，账号 neo4j / 12345678
- SQLITE_PATH=data/elevator.db（相对 backend\ 解析）
- RECOVERY_KEY_PATH / BACKUP_DIR / EXPORT_DIR 全部改到本机 backend\data\ 下（板端默认是 /userdata、/home/user/导出）
- RKLLM_SERVER_URL 保留 127.0.0.1:8080，但本机不启动推理服务：连接失败约 1 秒内返回，自动降级
- 设置页「基本配置」保存的值写到 backend\data\runtime_config.json（优先级高于 .env，.gitignore 已忽略）；部署基线仍以 .env 为准
- **注意**：pydantic-settings 对 .env 里的未知键会直接启动失败（extra_forbidden）。不要添加 config.py 里没有的配置项；旧模板中的 ELEVATOR_REPORT_TITLE 已从未使用的 .env.example 中删除

## 3. 一键启停

启动（首次会自动构建前端产物；Neo4j 未运行时会尝试拉起 Windows 服务）：

    powershell -ExecutionPolicy Bypass -File tools\dev\start-test-env.ps1

常用参数：

    -Dev       同时启动 Vite 开发服务器（5173，热更新）
    -Build     强制重新构建前端（vue-tsc + vite build）
    -SkipNeo4j 不检查/启动 Neo4j（只调试业务库相关接口时用）

停止（默认保留 Neo4j 服务，下次启动更快）：

    powershell -ExecutionPolicy Bypass -File tools\dev\stop-test-env.ps1

    # 连 Neo4j 一起停
    powershell -ExecutionPolicy Bypass -File tools\dev\stop-test-env.ps1 -IncludeNeo4j

脚本是幂等的：已在运行的服务不会重复启动；PID 记录在 backend\data\logs\*.pid，
PID 文件丢失时会按命令行特征兜底匹配（只匹配 python.exe / node.exe）。

## 4. 访问与账号

- 浏览器打开 **http://127.0.0.1:8081**
- 本机测试账号：**admin / admin123**（displayName=系统管理员）
- 空库首次打开会进入「系统初始化」向导；当前库已初始化，所以直接进登录页
- 需要重新体验初始化向导：停止后端 → 删除 backend\data\elevator.db、elevator.db-wal、elevator.db-shm → 重新启动 → 打开页面

## 4.1 前端录入规则（2026-10-22 调整）

- **评价内容与要求列已从录入页移除**（项目表只保留「项目编号 / 项目 / 评价结果」三列；报告预览与报告正文仍按模板保留该内容）。
- **新评估默认全部「符合」**：操作员只需要改例外项，不用逐条点 66 次。
- **漏填不再罗列清单**：点「校验并生成报告」时，自动滚动到第一处漏填位置（首处是自己整字段则聚焦输入框，是条目则高亮该行），同时给一个红色短 Toast，例如「还有 4 项未填写」，提示不遮挡、不弹窗。
- **「不符合」里的清单项与「其他」二选一**：勾选其中一个，另一边立即置灰并禁用；取消选择后恢复。落库时不会同时出现两种来源。
- **不符合情形展开后横跨整张表**（单独一行、跨三列），不再被「评价结果」窄列挤住，左侧项目编号/项目下方不再留大块空白；窄屏（600px）下展开项自成一张卡片、宽度用满。
- **层 / 站 / 门拆成三个数字输入框**：单位字「层」「站」「门」是固定标签，不可删除；只收数字；输入框平时**无边框**（hover / 聚焦才出现线条，与其它抬头输入一致）。旧草稿里的 `10 层　12 站　12 门` 字符串在打开时自动拆分回填；报告页仍按模板拼回「10 层　12 站　12 门」。
- **额定载重量（kg）与额定速度（m/s）单位固定**：单位字是标签不再写进输入值，数字框同样平时无边框；旧草稿里的 `/ kg`、`1000 kg` 会自动提取数字（无值即空，报告页显示「/ kg」）。
- **检测项目按项目编号分组折叠**：1.x / 2.x … 共 17 组，组名按 GB/T 42615-2023 附录 A 的表名（A.1 机器空间、滑轮间及警示标志 … A.18 乘运质量；液压部件 A.15 不适用于曳引驱动报告，故无 15.x 条目）。组头显示项数、已评与不符合数，点组头折叠/展开，默认展开。
- **基础信息可保存多套常用方案**：基础信息栏提供「方案下拉框 + 应用 / 保存新方案… / 删除」，可按不同委托单位、使用单位保存多套抬头；新建评估默认带入最近使用的一套。旧版单套快照会在我打开页面时自动迁移成一套方案。
- 对应的界面验收（tools/acceptance/ui_acceptance.js 与 walkthrough.js）已同步更新并通过。

## 4.2 页面导航（2026-10 调整）

- 左侧导航改为**项目进度 + 三个滚动锚点**：基础信息 / 检测项目填写 / 所生成报告；原先冗余的「报告预览」入口已删除。
- 「报告管理」「账号管理」不再占侧栏，统一并入**系统设置**；侧栏下移为录入页专属。
- 系统设置入口改为**右下角单个齿轮 icon**（内联 SVG，无第三方图标库依赖），点击进入设置页。
- 设置页采用**左侧树状导航 + 右侧内容**：业务管理（报告管理 / 账号管理）、系统维护（基本配置 / 审计日志 / 备份恢复 / 诊断）、关于系统；系统设置导航栏左上角有返回评估图标、底部保留注销登录，此时不显示项目侧栏。
- 旧地址 #/reports、#/accounts 自动重定向到系统设置对应节点，书签不失效。
- 右下角设置 icon 放大到 56px（窄屏 60px），改为主色渐变 + 明显投影，未在设置页时始终悬浮可见。
- 「基本配置」由只读改为**可编辑白名单**：机构名称、报告编号前缀、导出/备份目录、备份保留份数、会话时长、工作节点号、允许退出系统；保存后写入 backend/data/runtime_config.json（优先级高于 .env，重启后仍生效），工作节点号标注「重启生效」。
- 系统版本、大模型、业务库路径属于**不可配置的只读系统信息**，不再出现在「基本配置」，而是合并展示在「关于系统 → 关于本机」的信息表中（接口 /api/system/config 的 readonly_items 仍返回该数据）。
- **目录类配置支持系统文件夹选择框**（导出目录、备份目录）：点「选择…」由后端在服务端所在机器弹框，路径回填到输入框。
  - Windows：用 Python 自带 tkinter 打开资源管理器文件夹对话框；
  - Linux：优先 zenity / kdialog，其次带 DISPLAY 的 python3-tkinter（板端由 GNOME 提供）；
  - 都没有图形选择器时接口返回 503，界面按钮置灰，可直接在输入框里填绝对路径；
  - 可用性探测：GET /api/system/folder-picker（前端据此决定按钮状态），其余平台同理。
  - 实现见 backend/app/services/folder_picker.py；对话框在子进程里跑并带超时，用户取消/不操作不会卡住服务。

## 5. 验证与验收（本次实测结果）

后端单测（临时库，不碰本机业务库）：

    cd backend
    D:\miniconda3\envs\elevator_kg\python.exe -m pytest tests -q
    结果：101 passed, 5 subtests passed

前端单测与构建：

    cd web
    npm test           # 36 passed（5 个测试文件）
    npm run build      # vue-tsc 类型检查 + vite 构建 + 清理过期产物

接口层验收（对运行中的后端逐层校验，覆盖 82 项：静态资源、鉴权、账号、报告作业、备份恢复、基本配置与目录选择器、只读信息拆分、降级）：

    python tools\acceptance\http_acceptance.py
    结果：合计 82 项，通过 82，失败 0

界面层验收（Playwright + 本机 Edge 内核，覆盖 600x960 竖屏与 960x600 横屏、登录、66 条目、必填拦截、报告预览、导出结果卡、启动兜底）：

    $env:PLAYWRIGHT_MODULE = "D:\WorkSpace\llm-enhanced-elevator-fault-detection\web\node_modules\playwright"
    $env:CHROMIUM_EXE = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    $env:BASE = "http://127.0.0.1:8081"
    $env:ELEVATOR_USER = "admin"; $env:ELEVATOR_PASSWORD = "admin123"
    node tools\acceptance\ui_acceptance.js
    结果：全部通过（含两个视口与启动兜底）

说明：验收脚本里 PLAYWRIGHT_MODULE / CHROMIUM_EXE 的默认值写的是原开发机路径
（C:/Users/何/...），在本机必须用上面的环境变量覆盖。playwright 包是临时安装的
（npm install --no-save playwright，未写入 package.json），只用于界面验收。

手工冒烟清单（约 3 分钟）：

1. 打开 http://127.0.0.1:8081 → 登录 admin / admin123
2. 新建评估 → 66 条评价项目正常渲染
3. 随便填 1 项“不符合”并选一条风险 → 生成 → 报告编号 GDSEI-JTE-YYYYMMDD-XXX
4. 报告页正常分页；「导出 PDF」会提示“无法启动 LibreOffice”（本机无 LibreOffice，属预期）
5. 设置/系统页 → 诊断 → 业务库 / 条目库 / 知识图谱 / 导出目录 / 系统时间应为 ok，大模型服务 warn、文档转换 fail 属预期

## 6. 已知限制（本机特有，均不影响核心流程）

1. **没有推理端**：报告仍能生成，但叙述文字来自规则摘要；provenance.llm_used=false、llm_error 会写明原因。前端「生成」按钮不用改，后端自动降级。
2. **没有 LibreOffice**：PDF/Word 导出返回 500 + 可读提示（“导出失败：无法启动 LibreOffice…”）；诊断页“文档转换”为 fail。板端由预装 LibreOffice 完成。
3. **板端专属功能不在本机运行**：kiosk 退出、fcitx5 中文输入、屏幕旋转、GTK 原生窗口等；/api/kiosk/status 在非 Linux 下 probe_ok=false，前端会保守处理。
4. **恢复口令未生成**：/api/setup/status 的 recovery_available=false。需要时执行：

       cd backend
       D:\miniconda3\envs\elevator_kg\python.exe tools\make_recovery_key.py

5. **端口约定**：本机后端固定 8081（与 web/vite.config.ts 代理、验收脚本、板端 systemd 一致）；8080 留给板端 RKLLM，未占用。
6. **字体**：/NotoSansSymbols2.ttf 原仓库缺失（二进制被 .gitignore 排除），已补到 web/NotoSansSymbols2.ttf 与 web/public/NotoSansSymbols2.ttf，接口验收通过。

## 7. 常见问题

- 8081 被占用：先执行 stop-test-env.ps1，再 start；端口被其它程序占用时脚本会明确报错。
- 后端起不来：看 backend\data\logs\backend-8081.err.log；最常见是 backend\.env 里写了 config.py 未定义的键（ValidationError: Extra inputs are not permitted）。
- /api/health/ready 返回 503：Neo4j 服务没启动或口令不正确（服务名 neo4j，HTTP 7474 可打开确认）。
- 页面白屏：前端产物缺失或未挂载；执行 start-test-env.ps1 -Build，并确认 GET /assets/*.js 返回 200。
- 图谱数据异常：**backend/import_kg.py 用 CREATE 建点，不是幂等脚本**；重新导入前必须先清库：
  
      MATCH (n) DETACH DELETE n

  再在 backend\ 目录执行 python import_kg.py（脚本按 ../elevator_kg_csv 读 CSV）。
- 忘记 admin 口令：backend\tools\reset_password.py admin --password 新口令 --yes（走命令行直接改库）。

## 8. 本次部署新增 / 改动的文件

新增（建议提交）：

    tools/dev/start-test-env.ps1        一键启动
    tools/dev/stop-test-env.ps1         一键停止
    docs/本地测试环境部署-Windows.md     本文档
    web/NotoSansSymbols2.ttf            补回缺失字体（接口 /NotoSansSymbols2.ttf 用）
    web/public/NotoSansSymbols2.ttf     同上，构建时会被复制进 dist

修改：

    backend/.env.example                删除代码中不存在的 ELEVATOR_REPORT_TITLE（会导致启动失败）
    README.md                           文档索引增加本机测试环境入口

本机私有、不提交：

    backend/.env                        本机配置（.gitignore 已忽略）
    backend/data/                       业务库 / 日志 / 导出 / 备份（.gitignore 已忽略）
    web/node_modules/playwright/        界面验收用临时依赖（npm --no-save，不进 package.json）

## 9. 与板端的差异速查

| 项 | 板端（RK3588） | 本机（Windows） |
|---|---|---|
| 后端端口 | 8081（systemd） | 8081（脚本 / Start-Process） |
| 推理服务 | RKLLM 8080，Qwen3.5-4B | 无，后端自动降级 |
| 前端形态 | GTK/WebKit kiosk 全屏 | 普通浏览器；后端同源伺服 dist |
| 业务库路径 | /home/ubuntu/elevator/backend/data/ | backend\data\（.env 指定） |
| 备份 / 导出 | /userdata/backup、/home/user/导出 | backend\data\backups、backend\data\exports |
| 文档转换 | 预装 LibreOffice /usr/bin/soffice | 未安装，导出不可用（有可读报错） |
| 启动方式 | systemd 三服务 + kiosk 启动器 | tools/dev/start-test-env.ps1 |

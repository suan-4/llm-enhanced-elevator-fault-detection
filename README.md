# 基于知识图谱与大模型的电梯智能安全评估系统

RK3588 开发板上的**完全离线**电梯安全评估终端。依据 **GB/T 42615-2023
《在用电梯安全评估规范》**，把「检测项 → 异常状态 → 故障原因 → 风险 → 建议」
的知识图谱与大模型报告生成，做到一块触摸屏一体机上。

- **知识图谱**：Neo4j，6 大子系统 / 41 个检测项 / 67 种异常状态 / 392 条关系
- **大模型**：Qwen3-4B（W8A8）跑在 RK3588 NPU 上，经 RKLLM 推理，SSE 流式输出
- **后端**：FastAPI + SQLite（用户 / 会话 / 历史报告 / 填写记录）
- **前端**：单页应用（原生 JS，无构建步骤）
- **终端形态**：GTK3 + WebKit2GTK 原生全屏应用，开机直入，含自研软键盘 Shell 扩展

## 相关仓库

| 仓库 | 定位 | 内容 |
|---|---|---|
| **本仓库** `llm-enhanced-elevator-fault-detection` | **完整系统** | 业务代码、前端、原生应用、板端部署、知识图谱数据 |
| [rk3588-llm-inference](https://github.com/suan-4/rk3588-llm-inference) | **性能实验** | RK3588 推理性能的测量方法、实验脚本、实测数据与优化记录 |

两个仓库分工不重叠：

- **代码以本仓库为准**。这里保持"一套能跑的系统"的完整与纯粹。
- 那边只放**性能工作**：怎么测、测出什么、怎么优化。
  其中包括[对系统做过的全部性能改动记录](https://github.com/suan-4/rk3588-llm-inference/blob/main/docs/04-优化改动记录.md)
  （提示词长度约束、采样参数修复等），但不重复存放源码。

涉及推理性能的问题（为什么只有 5 tok/s、知识库变大会不会拖慢、怎么减少首字延迟），
看性能仓库；涉及功能与部署的问题，看本仓库和 `kiosk/README.md`。

## 目录结构

    backend/          FastAPI 服务
      app/api/          auth / history / report / kiosk / export / ime
      app/services/     kg_service(图谱) llm_service(模型) auth_service
                        report_service  export_service(Word/PDF)
      pkgs/             板端离线安装的 wheel（aarch64）
      import_kg.py      知识图谱导入
    web/              前端单页（index.html 是唯一入口）
    native/           elevator_app.py —— GTK3 + WebKit2 原生应用
    kiosk/            板端无人值守：安装脚本、加固、自启、启动器  ★文档最全
    osk-helper/       自研 GNOME Shell 扩展：经 D-Bus 桥接系统软键盘
    tools/            板端调试脚本 + 排查手法
    legacy/           历史部署方案（与当前板端不符，仅参考）
    elevator_kg_csv/  知识图谱的 CSV 源数据
    model/ rknn-llm/  模型与推理库（不进仓库，体积大）

## 文档在哪

| 想了解 | 看 |
|---|---|
| **板端一切细节与踩过的坑** | `kiosk/README.md` ← 最全，优先看这个 |
| 板端常用排查命令 | `tools/README.md` |
| 怎么部署到板子 | `push.bat`（头注释里写了实测布局） |
| 项目的能力清单 | `RESUME.md` |
| 后端接口 | `backend/API.md` |

## 部署到板端

板端**没有可用网络、apt 完全不可用**，只能 adb 推文件：

    push.bat          # 推 backend/app、web、native、kiosk、osk-helper 并重启服务

首次在板端装环境用 `kiosk/install_kiosk.sh`（装应用、桌面图标、
开机自启、Shell 扩展、系统加固）。已在板上跑过，日常增量更新只用 `push.bat`。

## 硬约束（改动前务必知道）

1. **板端离线**：apt / pip 联网都不可用。新依赖只能提前下好 wheel 放进
   `backend/pkgs/`。这也是导出功能选「LibreOffice 无头转换」而不是
   `python-docx` 的原因。
2. **屏幕方向由陀螺仪自动决定**，横竖屏都可能出现，且**不要**用
   `xrandr`/ApplyMonitorsConfig 去改（会把缩放重置成 1×）。
3. **不要给键盘加看门狗**。曾经的"键盘弹出后一会就消失"不是被系统回收，
   而是应用自己在错误的时机发了收起指令，看门狗只会让问题更糟。
4. **改注入到 WebView 的 JS（`native/elevator_app.py` 里的 `KBD_PROBE_JS`）
   必须重启应用**才生效；按 F5 只重载页面、不会重新注入。

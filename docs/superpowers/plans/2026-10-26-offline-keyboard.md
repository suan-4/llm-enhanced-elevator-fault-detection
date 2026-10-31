# 离线触摸键盘 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现并上板验收常见布局的离线拼音、手写与语音输入。
**Architecture:** Vue全局键盘与字段编辑适配；FastAPI本机输入接口；独立Fcitx上下文与有时限的本地录音/ASR；GTK桥抑制旧OSK。
**Tech Stack:** Vue3/TS、Fcitx5 D-Bus、HanziLookupJS、sherpa-onnx SenseVoice、PulseAudio。
**Spec:** docs/superpowers/specs/2026-10-26-offline-keyboard-design.md

## Global Constraints

- 全部运行资产在本机；不使用云端识别；单次录音最多30秒。
- 不改变评定算法，不覆盖现有草稿与方案，保留登录品牌。
- 后到的候选与语音结果不能进入已切换的字段。

## Review Focus

- 选区替换、emoji删除、maxlength与数字字段限制不能损坏表单。
- 关闭录音、路由跳转、字段被卸载后释放进程和音频。
- 拼音上下文隔离，候选选择必须验证来源，不能运行任意命令。
- 竖横屏触摸键位可用，系统与应用键盘不能同时弹出。
- 缺模型、无麦克风及静音必须明确报错，不能伪造识别结果。

### Task 1: 本机输入服务

**Files:** backend/app/services/offline_input.py、fcitx_worker.py、backend/app/api/input.py、backend/tests/test_offline_input.py、backend/app/main.py。
**Interfaces:** GET /api/input/status；POST /api/input/pinyin {actions} 返回候选/已提交；voice/start返回id，voice/stop {id}返回text，voice/cancel {id}释放。
- [x] 写服务边界测试（远程/跨源拒绝、动作限制、音频静音与长度、录音取消），运行确认缺功能失败。
- [x] 实现参数化本机命令、隔离上下文、最长30秒录音与临时文件清理；按接口回传可读错误。
- [x] 运行后端测试与板端真实拼音/ASR样本，记录性能并提交。

### Task 2: 面板与编辑

**Files:** web/src/components/input/*、web/src/utils/offlineInput.ts、web/src/domain/inputEditing.ts及测试、web/src/App.vue。
**Interfaces:** 输入组件消费Task1接口；focusin绑定原生input/textarea，setNativeValue派发input事件；Native旗标window.__elevatorInputManaged。
- [x] 写编辑边界测试并运行确认缺模块失败。
- [x] 实现选区/数字/长度编辑与面板；候选请求加版本与字段身份保护；离线手写本地资产；录音只在明确点击后开始。
- [x] 类型检查、前端全套测试、构建与浏览器交互验收，提交。

### Task 3: 原生桥与正式更新

**Files:** kiosk/install_offline_input.py、tools/acceptance/offline_input_browser.js、docs/acceptance/2026-10-26-离线键盘.md。
**Interfaces:** 安装脚本备份原生启动文件并局部更改焦点探针；/userdata/elevator/input存储固定版本ASR资产。
- [x] 候选服务和原生兼容测试，核对板端现有代码及业务数据摘要。
- [x] 明确暂停/恢复API、备份app/dist/原生启动器；复制同一已构建产物上板；重启界面并保留旧版回退路径。
- [x] 实机截图与数据不变校验；记录未能实测的麦克风人声质量；完成审查。

验收记录：`docs/acceptance/2026-10-26-离线键盘.md`。现场人声质量、实机竖屏及截图可见桌面Dock覆盖仍列为待现场确认项，不声称已通过。

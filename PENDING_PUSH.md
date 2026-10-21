# 推送状态

## 当前状态：2026-10-21 板端正式版本已更新

用户已授权更新板端正式版本并推送GitHub。当前分支为`codex/export-column-widths`，本轮包含原生JTE模板导出、报告快照、可靠归档和保存一致性修复。最新结果以本轮发布记录和Git命令为准。

正式服务已部署应用提交`f176359`，模型/Word/PDF隔离验收通过，原19份报告内容未变。恢复位置和发布结果见`docs/acceptance/2026-10-21-板端正式发布.md`。

本轮GitHub分支的实际同步状态检查：

```powershell
git fetch origin
git rev-list --left-right --count origin/codex/export-column-widths...HEAD
```

已验收制品`candidate-final.zip`的SHA256：`a498bad3e61120e8346caaa9ad8d74f0dace063a1ffd91d65cd4287adeb4d14b`。模型、离线运行库、业务数据库、密钥和测试生成文件不上传GitHub。

下面是历史记录，不代表当前已同步状态。

2026-10-13 晚上已推完，本地与远端一致：

```
本地 HEAD  = f0f9fac
远端 main  = f0f9fac
待推送数量 = 0
```

## 执行前先看命令结果，不要信这里的快照

本文里的哈希只代表写下这一刻，随时会过期。真正判断状态用：

```powershell
git fetch origin
git log --oneline origin/main..HEAD    # 列出待推送的提交
git rev-list --count origin/main..HEAD # 待推送数量，应为 0
```

## 推送

```powershell
git fetch origin
git push origin main
git rev-list --count origin/main..HEAD
```

注意：`git push` 会把进度写到 stderr，PowerShell 里可能显示成红色的
`NativeCommandError`、退出码 1，**不代表推送失败**，以上面的 `rev-list` 结果为准。

## 板端部署（与推送是两件事）

推送 ≠ 上板。前端产物按 `push.bat` 推到板端 `/home/ubuntu/elevator/web/dist`
（脚本会先快照到 `/userdata/releases/<时间戳>` 再原子替换），推完必须重启一体机
前端窗口 `elevator_app.py`，否则界面还停在旧产物上。

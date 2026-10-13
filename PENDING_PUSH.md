# 推送状态

## 当前状态：已全部推送

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

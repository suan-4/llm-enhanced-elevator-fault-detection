# 推送状态

## 当前约定

**本机网络不通，暂停推送。** 改动一律先本地提交，等网络稳定后一次性推。

远端停在：`c5455f2`（2026-10-13 上午推的最后一个提交）

## 待推送的提交

不要手工维护这里的清单（会过期），直接看命令结果：

```powershell
git log --oneline origin/main..HEAD   # 列出待推送的提交
git rev-list --count origin/main..HEAD # 待推送数量
```

## 联网后操作

```powershell
git fetch origin
git push origin main
git rev-list --count origin/main..HEAD # 推完应为 0
```

上次失败信息（非仓库问题，纯网络）：

```
fatal: unable to access 'https://github.com/suan-4/llm-enhanced-elevator-fault-detection.git/':
Failed to connect to github.com port 443 after 21119 ms: Could not connect to server
```

## 板端部署提示

推送 ≠ 上板。前端产物仍按 `push.bat` 推送到板端；目前**未在板端部署过任何新版本**。

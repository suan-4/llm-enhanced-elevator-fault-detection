# RKLLM 从 1.2.3 升级到 1.3.0（2026-09-12 实施）

## 结果

| | 升级前 | 升级后 |
|---|---|---|
| RKLLM 运行库 | 1.2.3（7543744 B） | **1.3.0**（7617472 B，build 82bf4aa8e） |
| 模型 | Qwen3-4B-Instruct-2507_W8A8_RK3588.rkllm（4.62 GB） | **Qwen3.5-4B_W8A8_RK3588.rkllm（5.16 GB）** |
| flask_server.py | 23538 B | **28927 B** |
| HTTP 路由 | /rkllm_chat | **/v1/chat/completions**（OpenAI 兼容） |

切换后 elevator-rkllm 与 elevator-api 均 active，
端到端生成报告成功（1132 字符，约 2 分 13 秒）。

## 三个必须注意的点（都是实际踩到的）

### 1. 路由变了 —— 后端会 404

1.3.0 把接口改成 OpenAI 兼容格式：

    1.2.3:  POST /rkllm_chat
    1.3.0:  POST /v1/chat/completions

**必须同步改后端的 backend/.env**，否则 elevator-api 连不上模型：

    RKLLM_SERVER_URL=http://127.0.0.1:8080/v1/chat/completions

（1.3.0 还注册了 GET /v1/models；流式 stream:true 返回标准
chat.completion.chunk 分片，后端解析逻辑不用改。）

### 2. flask_server.py 用「相对路径」加载运行库

    # 1.2.3
    rkllm_lib = ctypes.CDLL("/usr/lib/librkllmrt.so")
    # 1.3.0
    rkllm_lib = ctypes.CDLL("lib/librkllmrt.so")

所以必须在 flask_server.py **同目录**下放一个 lib/librkllmrt.so
（官方发行包里的 rkllm_server/lib/.gitkeep 就是这个意思）。
只更新 /usr/lib 那份会报：

    OSError: lib/librkllmrt.so: cannot open shared object file

服务单元是 WorkingDirectory=/home/ubuntu/elevator/rkllm，
所以路径为 /home/ubuntu/elevator/rkllm/lib/librkllmrt.so。

### 3. 大模型传输慢，先后台跑并核对字节数

5.16 GB 经 adb 约 **8.6 MB/s → 约 10 分钟**。建议后台传输，
**传完必须比对字节数**再动服务，否则会加载到截断的模型。

## 实施步骤（可复用）

    1. 备份     /root/rkllm-backup-1.2.3/（旧库 + 旧脚本 + 旧服务单元）
    2. 暂存     rkllm/_v130/{lib/librkllmrt.so, flask_server.py}
    3. 传模型   adb push Qwen3.5-4B_W8A8_RK3588.rkllm，比对字节数
    4. 停服务   systemctl stop elevator-rkllm
    5. 装库     install 到 /usr/lib/ 和 rkllm/lib/ 两处，再 ldconfig
    6. 装脚本   flask_server.py
    7. 改单元   ExecStart 的 --rkllm_model_path 指向新模型
    8. 起服务   加载 5 GB 约 20 秒
    9. 改后端   .env 的 RKLLM_SERVER_URL 换新路由
    10. 验证   流式接口 + 端到端生成报告

## 回滚

    systemctl stop elevator-rkllm
    cp -a /root/rkllm-backup-1.2.3/librkllmrt.so.usrlib /usr/lib/librkllmrt.so
    cp -a /root/rkllm-backup-1.2.3/librkllmrt.so.demo   /home/ubuntu/elevator/rkllm/demo_Linux_aarch64/lib/librkllmrt.so
    cp -a /root/rkllm-backup-1.2.3/flask_server.py      /home/ubuntu/elevator/rkllm/flask_server.py
    rm -f /home/ubuntu/elevator/rkllm/lib/librkllmrt.so
    cp -a /root/rkllm-backup-1.2.3/elevator-rkllm.service /etc/systemd/system/elevator-rkllm.service
    cp -a /root/env.bak-before-v130 /home/ubuntu/elevator/backend/.env
    ldconfig && systemctl daemon-reload
    systemctl start elevator-rkllm && systemctl restart elevator-api

> 旧模型**没有删除**，仍在 rkllm/Qwen3-4B-Instruct-2507_W8A8_RK3588.rkllm，
> 回滚不需要重新传输。
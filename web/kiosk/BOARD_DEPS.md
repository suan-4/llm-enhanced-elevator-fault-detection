# 板端环境依赖盘点：**仓库里没有、但板子必须有的东西**

> 目的：板子坏掉 / 重刷固件后，光有本仓库是**恢复不回来**的。
> 这份清单说明缺什么、从哪来、能不能重建。
> 盘点时间：2026-09-12（板端 Ubuntu 22.04.4 / EM-R16）

## 板端真实布局

    /home/ubuntu/elevator/
      backend/       FastAPI（WorkingDirectory）
      web/           前端
      rkllm/         模型 + flask_server.py（RKLLM 推理服务）
      elevator_kg_csv/  图谱源数据
    /home/ubuntu/elevator/backend/data/elevator.db   业务库（运行时自建）
    /home/user/elevator_app.py                       原生应用
    /home/user/elevator-launch.sh                    启动器
    /etc/systemd/system/elevator-{api,rkllm}.service
    /lib/systemd/system/neo4j.service
    /home/user/.local/share/gnome-shell/extensions/elevator-osk@local/

## ✅ 仓库里有，可恢复

| 东西 | 本地位置 | 大小 |
|---|---|---|
| RKLLM 模型 | `model/Qwen3-4B-Instruct-2507_W8A8_RK3588.rkllm` | 4.6 GB |
| NPU 运行库 `librkllmrt.so` | `model/demo_Linux_aarch64/lib/` | 7.2 MB |
| RKLLM 推理服务 `flask_server.py` | `rknn-llm/examples/rkllm_server_demo/rkllm_server/` | 23 KB |
| Neo4j 发行版 | `packages/neo4j.tar.gz` | 152 MB |
| 图谱源数据 | `elevator_kg_csv/` + `backend/import_kg.py` | — |
| Python wheel | `backend/pkgs/`（38 个，含 aarch64） | — |
| 业务代码 | `backend/` `web/` `native/` `kiosk/` `osk-helper/` | — |
| **systemd 服务单元** | `kiosk/systemd/` ← 本次新补 | 1 KB |
| 板端配置模板 | `backend/.env.example` | — |

## ❌ 仓库里没有，且**板端 apt 不可用 → 无法从仓库重建**

这一节是真正的风险所在。

### 1. 系统包（apt 安装）

| 包 | 谁在用 | 备注 |
|---|---|---|
| `libwebkit2gtk-4.0-37` `gir1.2-webkit2-4.0` `python3-gi` `gir1.2-gtk-3.0` | **原生应用全部依赖** | 没它 `elevator_app.py` 起不来 |
| `fcitx5` 全家桶（21 个包）+ `libpinyin13` `libpinyin-data` | 中文输入法 | |
| `libreoffice-core` (7.3.7) | **PDF / Word 导出** | 没它导出功能失效 |
| `pandoc` `poppler-utils` | 早期方案遗留 / PDF 检查 | |
| `fonts-noto-cjk` `fonts-noto-cjk-extra` | 中文显示 | 没它就是方块 |
| `openjdk-17-jdk` | **Neo4j 运行时** | |




### 2. apt 装的 Python 库（不在 `backend/pkgs/` 的 wheel 清单里）

| 模块 | 版本 | 来源 |
|---|---|---|
| `PIL` | 9.0.1 | `python3-pil` |
| `reportlab` | 3.6.8 | `python3-reportlab` |
| `yaml` | 5.4.1 | `python3-yaml` |

> 这三个都是**系统 dist-packages**，不是 pip 装的，`backend/pkgs/` 里没有对应 wheel。

### 3. 图谱数据

`/var/lib/neo4j/data` 约 **517 MB**。可以从 `elevator_kg_csv/`
配 `backend/import_kg.py` **重建**，不算致命，但要花时间。

### 4. 业务数据

`backend/data/elevator.db`（用户账号 / 报告历史 / 填写记录）。
表在启动时自建，但**用户数据只存在这里，丢了就没了**。

## 结论与建议

**可以在仓库外备份的最小集合**（用于灾后恢复）：

1. **apt 包**：`dpkg -l` 清单 + 用 `apt-get download` 把上述包全部下成 `.deb`
   （板端 apt 不可用 ≠ 开发机不可用；在能联网的 aarch64 环境或加 `--print-uris` 取）
2. **模型与运行库**：`model/` 整个目录（4.6 GB）
3. **Neo4j**：`packages/neo4j.tar.gz`，或 `/var/lib/neo4j` 整份
4. **JDK**：改用 apt 安装记录，删掉损坏的 tar 包
5. **业务库**：定期备份 `backend/data/elevator.db`

> 另外注意版本漂移：板端 `fastapi` 是 **0.138.0**，而
> `backend/pkgs/fastapi-0.136.3-...whl` 是 **0.136.3**。
> 用 wheel 重装会降级，接口行为可能有细微差异，重装后要回归验证。

# Laya 中文故障候选选择可行性（第一步 smoke）

日期：2026-10-29
状态：离线 smoke 完成，结论：零样本不可用，暂不接入。

## 1. 环境

- Laya 0.4.17
- torch 2.15.0+cpu
- 多语言 checkpoint: models--convaiinnovations--laya / multilingual
- 权重 614 MB，tokenizer 32.8 MB
- 宿主 CPU 推理；未在 RK3588 板端运行

## 2. 数据

从板端 kg_selection 去重得到 8 条有 Top3 候选的案例：

- 5 条 selected（其中 4 条是 AI 推荐后操作员确认，1 条是历史人工选择）
- 2 条 no_candidate（human / human_override）
- 1 条重复的 1.9，标签互相冲突

注意：这不是正式标注集，gold 大多来自模型推荐后的确认，结果只能作为 smoke。

候选格式：

    choice:
      p1/p2/p3 = 候选路径的 path_summary
      none = 以上都不符合，按规则表处置

输入 state 为“项目名 + 板端原始 query”。

## 3. 结果

### Laya multilingual 零样本

    案例数       8
    正确         1
    准确率       0.125
    高置信错误   2
    单次耗时     0.16–0.19s（宿主 CPU，已加载模型后）

逐项：

| 项目 | gold | Laya choice | 置信度 | 结果 |
|---|---|---|---|---|
| 1.10 夹绳器 | none | p3 | 0.39 | 错 |
| 1.9 限速器 | none | p1 | 0.36 | 错 |
| 4.5 编码器 | selected | none | 0.86 | 错，高置信 |
| 13.7 轿架 | selected | none | 0.57 | 错 |
| 12.1 钢丝绳 | selected | p3（错误部件） | 0.83 | 错，高置信 |
| 8.3 接地 | selected | none | 0.37 | 错 |
| 13.8 轿壁裂纹 | none | p1 | 0.47 | 错 |
| 1.9 限速器 | selected | p1 | 0.36 | 对 |

### Laya multilingual + JSON state

把输入从“项目名 + 描述”改成结构化 JSON：

    {"项目名称":"...","不符合描述":"..."}

结果：

    案例数       8
    正确         3
    准确率       0.375
    高置信错误   2
    单次耗时     0.15–0.19s（宿主 CPU）

比纯文本 state 好，但仍低于当前 4B T2，且仍有高置信错误：
4.5 编码器选 none（0.756）、12.1 钢丝绳选错部件（0.843）。

### 当前 4B T2 同案例

    案例数       8
    正确         6
    准确率       0.75
    单次耗时     17–26s

当前 T2 对 4.5/13.7/12.1/8.3 四条“部件明显”的项全部选对；Laya 这四条全错。
但要注意：T2 的 gold 多数来自 AI 推荐后确认，存在循环性，不能当作正式准确率。

### 更稳的子集

只看“部件非常明确”的 4 条 selected：

    Laya: 0/4
    4B T2: 4/4

看 2 条 human no_candidate：

    Laya: 0/2（都强行选了路径）
    4B T2: 0/2（也都选了路径）

## 4. 关键结论

1. **Laya 零样本中文选择不可靠**：会选错部件，也会对明显候选选 none，而且置信度不低；
2. 和其官方中文 benchmark 的低分一致：中文 choice 20/64，四问 18/64；
3. 速度很快（宿主 CPU 0.17s/项），但速度不能弥补选择错误；
4. 当前 4B T2 在同样 8 条上更好（6/8），但标签有循环性，仍需人工标注验证；
5. Laya 要做领域可用，必须**中文领域微调 + 校准 + 人工确认**，不能直接替换 T2。

## 5. 板端可行性

板端当前：

    内存 7.7GiB，可用 882MiB，无 swap
    CPU 8 核
    python 3.10，无 torch/onnxruntime

Laya multilingual 权重 614MB，加运行时后和 RKLLM 4B 共存风险很高；就算准确率解决，也需要 ONNX/INT8 和内存调度验证。当前不建议上板。

## 6. 建议

第一步已经说明：**Laya 零样本不值得接入**。

下一步按优先级：

1. 先建立 200–500 条人工确认的电梯候选数据集（含“无合适候选”），这是所有模型比较的前提；
2. 用当前 4B、确定性特征评分、Laya 三者做同集对比；
3. 如果 Laya 仍有潜力，再投入微调；否则采用确定性特征评分 + 4B 语义特征；
4. 微调后才做 ONNX/INT8 板端内存和延迟验证。

## 7. 复现

    .venv-laya\Scripts\python tools/kg/laya_eval.py --cases tools/kg/laya_eval_cases.json --device cpu

结果：

- tools/kg/laya_eval_result.json
- tools/kg/laya_eval_result_json_state.json
- tools/kg/board_t2_eval_result.json

Laya 参考：

- https://github.com/NandhaKishorM/laya
- https://github.com/NandhaKishorM/laya/blob/main/research/benchmarks/feishu_zh/README.zh-CN.md

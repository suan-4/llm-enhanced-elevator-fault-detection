# 电梯故障报告系统 — API 接口文档

## 基本信息

| 项目 | 说明 |
|------|------|
| 基础地址 | `http://localhost:8080` |
| 数据格式 | JSON |
| 字符编码 | UTF-8 |

---

## 1. 健康检查

### GET /api/health

**请求参数**: 无

**请求示例**:
```bash
curl http://localhost:8080/api/health
```

**响应示例**:
```json
{
  "status": "ok",
  "service": "elevator-report-api"
}
```

---

## 2. 生成故障报告

### POST /api/report/generate

根据检测不合格项目，查询 Neo4j 知识图谱获取故障链路，调用大模型生成评估报告。

### 请求体

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `inspection_item_ids` | `string[]` | 是 | 不通过的检测项目 ID 列表，至少 1 个 |
| `abnormal_states` | `string[]` | 否 | 前端确认的异常状态 ID 列表，默认 `[]` |
| `elevator_info` | `object` | 否 | 电梯基本信息 |
| `generate_with_llm` | `boolean` | 否 | 是否调用 LLM 生成报告，默认 `true`。`false` 时仅返回图谱数据 |

> 后端会合并 `inspection_item_ids` 关联的状态与 `abnormal_states` 直接指定的状态，统一查询风险和建议措施。

**elevator_info 字段**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `registration_id` | `string` | 否 | 电梯注册号 |
| `location` | `string` | 否 | 电梯所在位置 |
| `elevator_type` | `string` | 否 | 电梯类型，默认 `"曳引驱动乘客电梯"` |

### 响应体

| 字段 | 类型 | 说明 |
|------|------|------|
| `success` | `boolean` | 是否成功 |
| `message` | `string` | 提示信息 |
| `report` | `object` | LLM 生成的报告 |
| `report.raw_text` | `string` | LLM 原始输出文本（`generate_with_llm=false` 时返回图谱数据的 JSON 原文） |
| `fault_chain` | `object` | 图谱查询的结构化故障链路 |
| `fault_chain.inspection_results` | `array` | 各检测项的分析结果 |
| `fault_chain.all_risks` | `array` | 汇总的所有风险（去重） |
| `fault_chain.all_actions` | `array` | 汇总的所有建议措施（去重） |
| `generated_at` | `string` | 生成时间 (ISO 8601) |

**fault_chain.inspection_results 元素结构**:

```json
{
  "inspection_item": {
    "id": "INS_BRAKE_001",
    "name": "制动试验",
    "description": "检查制动器制停能力和停车距离"
  },
  "detected_states": [
    {
      "state": { "id": "STATE_BRAKE_002", "name": "制动力下降", "description": "..." },
      "component": { "id": "COMP_BRAKE_001", "name": "制动器" },
      "severity": 4,
      "state_level": "性能退化",
      "phenomena": [
        { "id": "PHEN_BRAKE_001", "name": "制停距离延长", "description": "..." }
      ],
      "risks": [
        {
          "id": "RISK_BRAKE_001",
          "name": "轿厢非正常移动",
          "description": "...",
          "extra": { "risk_level": "高风险" }
        }
      ],
      "actions": [
        {
          "id": "ACT_BRAKE_009",
          "name": "停止使用并专项检验",
          "description": "...",
          "extra": { "action_type": "风险控制" }
        }
      ],
      "coupled_states": [
        { "id": "STATE_TRACTION_002", "name": "曳引能力下降" }
      ],
      "evolved_states": [ ... ]
    }
  ]
}
```

### 错误码

| HTTP 状态码 | 说明 |
|-------------|------|
| 200 | 成功 |
| 400 | 请求参数错误或未查询到图谱数据 |
| 503 | Neo4j 数据库不可用 / RKLLM 服务不可用 |
| 500 | 服务器内部错误 |

---

## 3. 调用示例

### 示例 1：仅查询图谱（不调用 LLM）

```bash
curl -X POST http://localhost:8080/api/report/generate \
  -H "Content-Type: application/json" \
  -d '{
    "inspection_item_ids": ["INS_BRAKE_001"],
    "abnormal_states": ["STATE_BRAKE_002"],
    "generate_with_llm": false
  }'
```

### 示例 2：前端传入检测项+异常状态，调用 LLM 生成报告

```python
import httpx

async def generate_report():
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            "http://localhost:8080/api/report/generate",
            json={
                "inspection_item_ids": ["INS_BRAKE_001", "INS_DOOR_003"],
                "abnormal_states": ["STATE_BRAKE_002", "STATE_DOOR_005"],
                "elevator_info": {
                    "registration_id": "TI-2024-001",
                    "location": "XX Building A",
                    "elevator_type": "traction passenger elevator"
                },
                "generate_with_llm": True
            }
        )
        return resp.json()
```

### 示例 3：多项检测故障联动分析

```bash
curl -X POST http://localhost:8080/api/report/generate \
  -H "Content-Type: application/json" \
  -d '{
    "inspection_item_ids": [
      "INS_BRAKE_001",
      "INS_DOOR_003",
      "INS_TRACTION_003",
      "INS_BUFFER_001",
      "INS_SAFETY_001"
    ],
    "abnormal_states": [
      "STATE_BRAKE_002",
      "STATE_TRACTION_003"
    ],
    "elevator_info": {
      "registration_id": "TI-2024-002",
      "location": "XX Mall B1",
      "elevator_type": "traction freight elevator"
    },
    "generate_with_llm": true
  }'
```

### 示例 4：仅用异常状态查询（不指定检测项）

前端已经知道具体异常状态，可以直接按状态查询风险和建议：

```bash
curl -X POST http://localhost:8080/api/report/generate \
  -H "Content-Type: application/json" \
  -d '{
    "inspection_item_ids": ["INS_BRAKE_001"],
    "abnormal_states": [
      "STATE_BRAKE_001",
      "STATE_BRAKE_002",
      "STATE_BRAKE_008"
    ],
    "generate_with_llm": false
  }'
```

---

## 附录: 检测项目 ID 对照表

### 制动系统

| ID | 检测项 | 方法 |
|----|--------|------|
| `INS_BRAKE_001` | 制动试验 | 运行试验 |
| `INS_BRAKE_002` | 制动器间隙检查 | 现场测量 |
| `INS_BRAKE_003` | 制动器磨损检查 | 现场检查 |
| `INS_BRAKE_004` | 制动器释放闭合响应检查 | 运行试验 |
| `INS_BRAKE_005` | 制动器监测开关检查 | 电气测试 |
| `INS_BRAKE_006` | 制动接触器检查 | 电气检查 |
| `INS_BRAKE_007` | 手动松闸装置检查 | 现场检查 |

### 门系统

| ID | 检测项 | 方法 |
|----|--------|------|
| `INS_DOOR_001` | 门锁装置检查 | 现场检查 |
| `INS_DOOR_002` | 门锁回路测试 | 电气测试 |
| `INS_DOOR_003` | 层门自闭检查 | 现场检查 |
| `INS_DOOR_004` | 门滑块检查 | 现场检查 |
| `INS_DOOR_005` | 门机运行检查 | 运行试验 |
| `INS_DOOR_006` | 光幕安全触板试验 | 功能试验 |
| `INS_DOOR_007` | 门刀门球位置检查 | 现场检查 |

### 安全保护系统

| ID | 检测项 | 方法 |
|----|--------|------|
| `INS_SAFETY_001` | 限速器校验 | 校验试验 |
| `INS_SAFETY_002` | 安全钳联动试验 | 功能试验 |
| `INS_SAFETY_003` | 限速器钢丝绳张力检查 | 现场检查 |
| `INS_SAFETY_004` | 上行超速保护试验 | 功能试验 |
| `INS_SAFETY_005` | 非预期移动保护试验 | 功能试验 |
| `INS_SAFETY_006` | 终端限位极限开关检查 | 功能试验 |

### 电气控制系统

| ID | 检测项 | 方法 |
|----|--------|------|
| `INS_CONTROL_001` | 安全回路检查 | 电气测试 |
| `INS_CONTROL_002` | 接触器检查 | 电气检查 |
| `INS_CONTROL_003` | 控制柜故障记录检查 | 资料和现场检查 |
| `INS_CONTROL_004` | 变频器运行参数检查 | 参数检查 |
| `INS_CONTROL_005` | 编码器信号检查 | 仪器检测 |
| `INS_CONTROL_006` | 平层精度测量 | 现场测量 |
| `INS_CONTROL_007` | 位置检测装置检查 | 功能试验 |
| `INS_CONTROL_008` | 紧急报警通信试验 | 功能试验 |
| `INS_CONTROL_009` | 应急照明试验 | 功能试验 |

### 曳引系统

| ID | 检测项 | 方法 |
|----|--------|------|
| `INS_TRACTION_001` | 曳引能力试验 | 运行试验 |
| `INS_TRACTION_002` | 曳引轮槽检查 | 现场检查 |
| `INS_TRACTION_003` | 曳引钢丝绳检查 | 现场检查 |
| `INS_TRACTION_004` | 钢丝绳张力检查 | 仪器检测 |
| `INS_TRACTION_005` | 曳引机运行检查 | 运行观察 |
| `INS_TRACTION_006` | 导轨导靴检查 | 现场检查 |
| `INS_TRACTION_007` | 轮系轴承检查 | 现场检查 |

### 缓冲器与底坑

| ID | 检测项 | 方法 |
|----|--------|------|
| `INS_BUFFER_001` | 缓冲器复位检查 | 现场检查 |
| `INS_BUFFER_002` | 缓冲器油位检查 | 现场检查 |
| `INS_BUFFER_003` | 缓冲器电气开关检查 | 功能试验 |
| `INS_BUFFER_004` | 缓冲器固定和底座检查 | 现场检查 |
| `INS_BUFFER_005` | 底坑环境检查 | 现场检查 |

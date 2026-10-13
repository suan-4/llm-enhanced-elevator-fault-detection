from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class ElevatorInfo(BaseModel):
    registration_id: Optional[str] = Field(None, description="电梯注册号")
    location: Optional[str] = Field(None, description="电梯位置")
    elevator_type: Optional[str] = Field(default="曳引驱动乘客电梯", description="电梯类型")


class ReportRequest(BaseModel):
    inspection_item_ids: list[str] = Field(..., min_length=1, description="不通过的检测项目ID列表")
    abnormal_states: list[str] = Field(default=[], description="前端确认的异常状态ID列表")
    elevator_info: Optional[ElevatorInfo] = Field(default=None, description="电梯基本信息")
    generate_with_llm: bool = Field(default=True, description="是否调用LLM生成报告")


class KGNode(BaseModel):
    id: str
    name: str = ""
    description: Optional[str] = None
    extra: Optional[dict] = None


class FaultState(BaseModel):
    state: KGNode
    component: KGNode
    severity: int = 0
    state_level: Optional[str] = None
    evolved_states: list["FaultState"] = []
    phenomena: list[KGNode] = []
    risks: list[KGNode] = []
    actions: list[KGNode] = []
    coupled_states: list[KGNode] = []


class InspectionItemResult(BaseModel):
    inspection_item: KGNode
    detected_states: list[FaultState] = []


class FaultChainResponse(BaseModel):
    inspection_results: list[InspectionItemResult]
    all_risks: list[KGNode]
    all_actions: list[KGNode]


class ReportContent(BaseModel):
    raw_text: str = ""


class ReportResponse(BaseModel):
    success: bool
    message: str = ""
    report: Optional[ReportContent] = None
    fault_chain: Optional[FaultChainResponse] = None
    generated_at: Optional[datetime] = None


# ── 认证与账号 ────────────────────────────────────────────
# 注意：id 一律以**字符串**出现在响应里（雪花 ID 超出 JS 安全整数）。
class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=128)


class SetupInitRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=64)
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=8, max_length=128)


class ForgotPasswordRequest(BaseModel):
    recovery_key: str = Field(..., min_length=1, max_length=200)
    username: str = Field(..., min_length=1, max_length=64)
    new_password: str = Field(..., min_length=8, max_length=128)


class CreateAccountRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=64)
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=8, max_length=128)
    employee_no: str = Field(default="", max_length=32)
    require_change: bool = Field(default=False, description="是否要求对方首次登录改密")
    client_token: Optional[str] = Field(default=None, max_length=64)


class UpdateAccountRequest(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=64)
    employee_no: Optional[str] = Field(default=None, max_length=32)
    is_active: Optional[bool] = None
    confirm: bool = Field(default=False, description="停用等破坏性操作需要二次确认")


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=8, max_length=128)
    require_change: bool = Field(default=False)
    confirm: bool = Field(default=False)


# ── 报告作业（/api/reports）────────────────────────────────
class ItemAnswer(BaseModel):
    """一条评价结果。result 取值见《数据库设计 v1》§7.2。"""

    no: str = Field(..., max_length=16)
    result: str = Field(default="", description="fit / unfit / na / 空=未填")
    reasons: list[str] = Field(default_factory=list)
    other_text: str = Field(default="", max_length=500)


class ReportCreateRequest(BaseModel):
    form: Optional[dict] = Field(default=None, description="仅在“复制为新建”时预填抬头")
    client_token: Optional[str] = Field(default=None, max_length=64)


class ReportSaveRequest(BaseModel):
    form: dict = Field(default_factory=dict)
    items: list[ItemAnswer] = Field(default_factory=list)
    version: Optional[int] = Field(default=None, description="乐观锁：与库里不一致则 409")


class ReportGenerateRequest(BaseModel):
    use_llm: bool = Field(default=False, description="是否调用大模型生成叙述文字")
    client_token: Optional[str] = Field(default=None, max_length=64)


class ReportVoidRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=200, description="作废原因，必填")
    confirm: bool = False

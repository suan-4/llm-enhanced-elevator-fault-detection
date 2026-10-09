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


# ── 认证 ──────────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=4, max_length=128)


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=4, max_length=128)
    display_name: str = Field(default="", max_length=64)
    role: str = Field(default="inspector", description="admin 或 inspector")


class UpdateUserRequest(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=64)
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=4, max_length=128)


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str = ""
    role: str
    is_active: bool
    created_at: Optional[str] = None
    last_login_at: Optional[str] = None


# ── 报告历史 / 填写记录 ────────────────────────────────────
class HistoryCreate(BaseModel):
    time_label: str = ""
    reg: str = ""
    location: str = ""
    items_count: int = 0
    states_count: int = 0
    report_text: str = ""
    fault_chain: Optional[dict] = None
    form_data: Optional[dict] = None
    items_data: Optional[dict] = None


class HistorySummary(BaseModel):
    id: int
    time_label: str = ""
    reg: str = ""
    location: str = ""
    items_count: int = 0
    states_count: int = 0
    created_at: Optional[str] = None


class HistoryDetail(HistorySummary):
    report_text: str = ""
    fault_chain: Optional[dict] = None
    form_data: Optional[dict] = None
    items_data: Optional[dict] = None


class HistoryUpdate(BaseModel):
    report_text: Optional[str] = None


class DraftPayload(BaseModel):
    form_data: dict = Field(default_factory=dict)
    items_data: dict = Field(default_factory=dict)

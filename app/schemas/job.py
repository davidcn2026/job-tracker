from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Status = Literal["待投", "已投", "预约面试", "已面试", "已挂"]
Source = Literal["本校", "Boss直聘", "自定义", "其他"]


class JobIn(BaseModel):
    """请求体：只包含客户端允许设置的字段。

    没有 id / user_id / created_at —— 这三个由服务端决定，
    允许客户端传会造成越权（改别人的记录、往别人账下写数据）。
    """

    company: str = Field(min_length=1, max_length=100)
    position: str = Field(min_length=1, max_length=100)
    status: Status = "待投"
    source: Source = "其他"
    source_detail: str | None = Field(default=None, max_length=100)
    salary_min: int | None = Field(default=None, ge=0, le=1000)
    salary_max: int | None = Field(default=None, ge=0, le=1000)
    salary_note: str | None = Field(default=None, max_length=50)
    url: str | None = Field(default=None, max_length=500)
    published_at: date | None = None
    description: str | None = None
    company_business: str | None = Field(default=None, max_length=200)
    note: str | None = None
    next_interview_at: datetime | None = None

    @model_validator(mode="after")
    def _check_salary_range(self) -> "JobIn":
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_max < self.salary_min
        ):
            raise ValueError("薪资上限不能小于下限")
        return self


class JobOut(BaseModel):
    """列表响应：不含 JD 全文，避免列表接口响应体过大。"""

    model_config = ConfigDict(from_attributes=True)  # 允许从“对象”属性取值

    id: int
    company: str
    position: str
    status: str
    salary_min: int | None
    salary_max: int | None
    salary_note: str | None
    source: str
    source_detail: str | None
    url: str | None
    published_at: date | None
    company_business: str | None
    created_at: datetime
    next_interview_at: datetime | None = None


class JobDetail(JobOut):
    """详情响应：在列表字段基础上补 JD 全文和备注。"""

    description: str | None
    note: str | None


class JobListData(BaseModel):
    list: list[JobOut]
    total: int
    page: int
    page_size: int
    has_more: bool


class JobUpdate(BaseModel):
    company: str | None = Field(default=None, min_length=1, max_length=100)
    position: str | None = Field(default=None, min_length=1, max_length=100)
    status: Status | None = None
    source: Source | None = None
    source_detail: str | None = None
    salary_min: int | None = Field(default=None, ge=0, le=1000)
    salary_max: int | None = Field(default=None, ge=0, le=1000)
    salary_note: str | None = None
    url: str | None = None
    published_at: date | None = None
    description: str | None = None
    company_business: str | None = None
    note: str | None = None
    next_interview_at: datetime | None = None


class JobDeleted(BaseModel):
    deleted_id: int

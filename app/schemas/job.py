from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Status = Literal["待投", "已投", "预约面试", "已面试", "已挂"]
Source = Literal["本校", "Boss直聘", "自定义", "其他"]

def _clean_url(value: str | None) -> str | None:
    """规整链接：缺协议自动补 https，非 http(s) 协议直接拒绝。

    这两个字段会直接进前端 <a href>，如果放行 javascript: 之类的 scheme，
    点一下就执行脚本。但也不能太苛刻——很多人复制的是不带协议的域名，
    直接报错不如帮他补上。
    """
    if value is None:
        return None

    text = value.strip()
    if not text:
        return None

    lower = text.lower()
    if lower.startswith(("http://", "https://")):
        return text

    # 第一段里出现冒号 → 是别的协议（javascript: / ftp: / mailto:），拒绝
    if ":" in text.split("/", 1)[0]:
        raise ValueError("链接只支持 http:// 或 https://")

    # 没写协议：当作域名，补上 https
    return "https://" + text


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
    # url = 岗位详情页（看 JD）；apply_url = 投递入口（真正提交简历）
    url: str | None = Field(default=None, max_length=500)
    apply_url: str | None = Field(default=None, max_length=500)
    published_at: date | None = None
    description: str | None = None
    company_business: str | None = Field(default=None, max_length=200)
    note: str | None = None
    next_interview_at: datetime | None = None

    @field_validator("url", "apply_url")
    @classmethod
    def _validate_url(cls, value: str | None) -> str | None:
        return _clean_url(value)

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
    apply_url: str | None
    published_at: date | None
    company_business: str | None
    created_at: datetime
    next_interview_at: datetime | None = None
    match_score: int | None
    verdict: str | None = None
    analyzed_at: datetime | None
    # 有没有 JD 原文（不返回全文，只返回布尔）。
    # 前端靠它判断"该不该显示分析中"：有 JD 但没分数 = 后台正在分析，值得轮询。
    has_description: bool = False


class JobDetail(JobOut):
    """详情响应：在列表字段基础上补 JD 全文和备注。"""

    description: str | None
    note: str | None
    analysis: str | None


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
    apply_url: str | None = None
    published_at: date | None = None
    description: str | None = None
    company_business: str | None = None
    note: str | None = None
    next_interview_at: datetime | None = None

    @field_validator("url", "apply_url")
    @classmethod
    def _validate_url(cls, value: str | None) -> str | None:
        return _clean_url(value)


class JobDeleted(BaseModel):
    deleted_id: int

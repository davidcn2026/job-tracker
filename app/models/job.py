from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "company", "position", name="uk_user_company_position"),
        Index("idx_user_status", "user_id", "status"),
        Index("idx_user_published", "user_id", "published_at"),
        Index("idx_user_verdict", "user_id", "verdict"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column()

    # 岗位主体
    company: Mapped[str] = mapped_column(String(100))  # 公司名称
    position: Mapped[str] = mapped_column(String(100))  # 岗位名称
    status: Mapped[str] = mapped_column(String(20), default="待投")

    # 薪资（千元/月）
    salary_min: Mapped[int | None] = mapped_column(Integer)
    salary_max: Mapped[int | None] = mapped_column(Integer)
    salary_note: Mapped[str | None] = mapped_column(String(50))  # 备注

    # 来源与时间
    source: Mapped[str] = mapped_column(String(20), default="其他")
    source_detail: Mapped[str | None] = mapped_column(String(100))
    url: Mapped[str | None] = mapped_column(String(500))
    published_at: Mapped[date | None] = mapped_column(Date)
    next_interview_at: Mapped[datetime | None] = mapped_column(DateTime)  # 下次面试时间

    # 内容
    description: Mapped[str | None] = mapped_column(Text)  # JD
    company_business: Mapped[str | None] = mapped_column(String(200))  # 公司业务
    note: Mapped[str | None] = mapped_column(Text)  #   备注

    # 审计
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )

    match_score: Mapped[int | None] = mapped_column(Integer)
    analysis: Mapped[str | None] = mapped_column(Text)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime)

    verdict: Mapped[str | None] = mapped_column(String(20))

    @property
    def has_description(self) -> bool:
        """列表接口不返回 JD 全文，但前端需要知道"有没有 JD"。

        有 JD 却没分数 = 后台正在分析（或分析失败），前端据此决定要不要轮询。
        """
        return bool((self.description or "").strip())

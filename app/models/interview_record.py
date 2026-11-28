from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class InterviewRecord(Base):
    """一次真实面试。

    表按"一次面试一行"设计，天然支持同一个岗位记多次
    （用 interview_at 区分）。但界面暂不做轮次管理，
    round_no 恒为 1，等真要做轮次时不用改表。
    """

    __tablename__ = "interview_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    job_id: Mapped[int] = mapped_column(Integer, index=True)

    interview_at: Mapped[datetime | None] = mapped_column(DateTime)
    round_no: Mapped[int] = mapped_column(Integer, default=1)

    # pending 待结果 / passed 通过 / failed 挂了 / no_reply 没回音
    outcome: Mapped[str] = mapped_column(String(20), default="pending")
    summary: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")
    )

    # lazy="selectin" 是必须的：SQLAlchemy 2.0 异步下访问懒加载关系会抛
    # MissingGreenlet（不在 greenlet 上下文里）。selectin 会在查询时
    # 自动用第二条 SELECT 把问题一起捞出来。
    questions: Mapped[list["InterviewQuestion"]] = relationship(
        back_populates="record",
        cascade="all, delete-orphan",
        order_by="InterviewQuestion.order_no",
        lazy="selectin",
    )


class InterviewQuestion(Base):
    """面试官问过的一道题，以及我当时答得怎么样。

    单独一张表而不是塞 JSON：将来要"跨岗位看所有被问过的 Redis 问题"，
    JSON 列做不到聚合查询。
    """

    __tablename__ = "interview_questions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    record_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("interview_records.id", ondelete="CASCADE"), index=True
    )

    question: Mapped[str] = mapped_column(Text)
    my_answer: Mapped[str | None] = mapped_column(Text)

    # good 答得好 / ok 一般 / bad 答不上来
    performance: Mapped[str] = mapped_column(String(10), default="ok")
    gap: Mapped[str | None] = mapped_column(Text)
    follow_up: Mapped[str | None] = mapped_column(Text)

    order_no: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    record: Mapped[InterviewRecord] = relationship(back_populates="questions")

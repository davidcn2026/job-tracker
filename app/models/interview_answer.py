from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class InterviewAnswer(Base):
    """一道面试题的作答记录。

    用 question_hash 定位而不是题号：重新生成面试题后顺序会变，
    但题目文本不变则 hash 不变，答案就能找回来。
    """

    __tablename__ = "interview_answers"
    __table_args__ = (
        UniqueConstraint("user_id", "job_id", "question_hash", name="uk_user_job_q"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    job_id: Mapped[int] = mapped_column(Integer, index=True)
    question_hash: Mapped[str] = mapped_column(String(16))

    answer: Mapped[str | None] = mapped_column(Text)
    covered: Mapped[list | None] = mapped_column(JSON)
    wrong: Mapped[list | None] = mapped_column(JSON)
    missing: Mapped[list | None] = mapped_column(JSON)

    depth: Mapped[int] = mapped_column(Integer, default=0)
    transcript: Mapped[list | None] = mapped_column(JSON)
    finish_reason: Mapped[str | None] = mapped_column(String(20))
    last_verdict: Mapped[str | None] = mapped_column(Text)

    # untried / tried / partial / mastered / wrong
    status: Mapped[str] = mapped_column(String(20), default="untried")

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )

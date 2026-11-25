from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class AssistantMessage(Base):
    """全局助手的对话消息（一个用户一条会话线）。

    role 有三种：
      user      用户说的话
      assistant 助手的回答
      tool      工具调用结果（如 web_search 的摘要）
                —— 单独存下来，用户才能看见"助手查了什么"，而不是黑箱
    """

    __tablename__ = "assistant_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    tool_name: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

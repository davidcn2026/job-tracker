from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AssistantChatIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class AssistantMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str                      # user / assistant / tool
    content: str
    tool_name: str | None = None
    created_at: datetime


class AssistantChatOut(BaseModel):
    """一轮对话的结果。

    同时返回 user / assistant 消息是多余的（前端 localStorage 里已有用户输入），
    但显式返回能让前端"以后端为准"重绘，避免顺序错乱。
    """

    reply: AssistantMessageOut

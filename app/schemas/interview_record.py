from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# pending 待结果 / passed 通过 / failed 挂了 / no_reply 没回音
Outcome = Literal["pending", "passed", "failed", "no_reply"]

# good 答得好 / ok 一般 / bad 答不上来
Performance = Literal["good", "ok", "bad"]


class InterviewQuestionIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    my_answer: str | None = Field(default=None, max_length=4000)
    performance: Performance = "ok"
    gap: str | None = Field(default=None, max_length=2000)
    follow_up: str | None = Field(default=None, max_length=1000)


class InterviewRecordIn(BaseModel):
    interview_at: datetime | None = None
    outcome: Outcome = "pending"
    summary: str | None = Field(default=None, max_length=4000)
    # 一次面试记几十道题足够；上限是为了防止误粘贴整页文本
    questions: list[InterviewQuestionIn] = Field(default_factory=list, max_length=40)


class InterviewQuestionOut(InterviewQuestionIn):
    model_config = ConfigDict(from_attributes=True)

    id: int


class InterviewRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    interview_at: datetime | None
    round_no: int
    outcome: str
    summary: str | None
    created_at: datetime
    updated_at: datetime | None
    questions: list[InterviewQuestionOut] = Field(default_factory=list)

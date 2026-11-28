"""面试复盘的读写。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import InterviewQuestion, InterviewRecord
from app.schemas.interview_record import InterviewRecordIn


async def list_records(
    db: AsyncSession, user_id: int, job_id: int
) -> list[InterviewRecord]:
    result = await db.execute(
        select(InterviewRecord)
        .where(InterviewRecord.user_id == user_id, InterviewRecord.job_id == job_id)
        .order_by(InterviewRecord.interview_at.desc(), InterviewRecord.id.desc())
    )
    return list(result.scalars().all())


async def get_record(
    db: AsyncSession, user_id: int, record_id: int
) -> InterviewRecord | None:
    result = await db.execute(
        select(InterviewRecord).where(
            InterviewRecord.id == record_id, InterviewRecord.user_id == user_id
        )
    )
    return result.scalar_one_or_none()


def _build_questions(
    user_id: int, payload: InterviewRecordIn
) -> list[InterviewQuestion]:
    """按提交顺序生成问题行。order_no 显式写，避免依赖数据库默认值排序。"""
    rows = []
    for index, item in enumerate(payload.questions):
        rows.append(
            InterviewQuestion(
                user_id=user_id,
                question=item.question.strip(),
                my_answer=(item.my_answer or "").strip() or None,
                performance=item.performance,
                gap=(item.gap or "").strip() or None,
                follow_up=(item.follow_up or "").strip() or None,
                order_no=index,
            )
        )
    return rows


async def create_record(
    db: AsyncSession, user_id: int, job_id: int, payload: InterviewRecordIn
) -> InterviewRecord:
    record = InterviewRecord(
        user_id=user_id,
        job_id=job_id,
        interview_at=payload.interview_at or datetime.now(),
        outcome=payload.outcome,
        summary=(payload.summary or "").strip() or None,
        questions=_build_questions(user_id, payload),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def replace_record(
    db: AsyncSession, record: InterviewRecord, payload: InterviewRecordIn
) -> InterviewRecord:
    """整份替换（含问题列表）。

    为什么是整份替换而不是逐题 diff：
        一次面试的问题通常一起录入、一起修正，前端也整体提交。
        逐题 diff 要处理新增/删除/改序三种情况，代码量和出错面都大得多。
    """
    record.interview_at = payload.interview_at or record.interview_at
    record.outcome = payload.outcome
    record.summary = (payload.summary or "").strip() or None
    # cascade="all, delete-orphan" 会把被替换掉的旧问题删掉
    record.questions = _build_questions(record.user_id, payload)

    await db.commit()
    await db.refresh(record)
    return record


async def delete_record(db: AsyncSession, record: InterviewRecord) -> None:
    await db.delete(record)
    await db.commit()

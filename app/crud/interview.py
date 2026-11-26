"""面试作答记录的读写。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import InterviewAnswer


async def get_answer(
    db: AsyncSession, user_id: int, job_id: int, question_hash: str
) -> InterviewAnswer | None:
    result = await db.execute(
        select(InterviewAnswer).where(
            InterviewAnswer.user_id == user_id,
            InterviewAnswer.job_id == job_id,
            InterviewAnswer.question_hash == question_hash,
        )
    )
    return result.scalar_one_or_none()


async def list_answers(
    db: AsyncSession, user_id: int, job_id: int
) -> list[InterviewAnswer]:
    result = await db.execute(
        select(InterviewAnswer)
        .where(InterviewAnswer.user_id == user_id, InterviewAnswer.job_id == job_id)
        .order_by(InterviewAnswer.id)
    )
    return list(result.scalars().all())


async def upsert_answer(
    db: AsyncSession,
    user_id: int,
    job_id: int,
    question_hash: str,
    **fields,
) -> InterviewAnswer:
    """按 (user, job, 题目指纹) 更新或新建。

    用 upsert 而不是"先建后改"：前端可能重复提交同一题，
    唯一键会撞，upsert 是最省事且不会报错的写法。
    """
    record = await get_answer(db, user_id, job_id, question_hash)

    if record is None:
        record = InterviewAnswer(
            user_id=user_id,
            job_id=job_id,
            question_hash=question_hash,
        )
        db.add(record)

    for key, value in fields.items():
        setattr(record, key, value)
    record.updated_at = datetime.now()

    await db.commit()
    await db.refresh(record)
    return record

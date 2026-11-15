from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.schemas.job import JobIn, JobUpdate


async def list_jobs(
    db: AsyncSession, user_id: int, page: int, page_size: int
) -> tuple[list[Job], int]:
    """返回 (当前页数据, 总数)。所有查询强制带 user_id。"""
    where = Job.user_id == user_id

    total = await db.scalar(select(func.count()).select_from(Job).where(where)) or 0

    result = await db.execute(
        select(Job)
        .where(where)
        .order_by(Job.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars().all()), total


async def get_job(db: AsyncSession, user_id: int, job_id: int) -> Job | None:
    """查单条。不属于该用户的记录同样返回 None（对外统一 404，不泄露存在性）。"""
    result = await db.execute(select(Job).where(Job.id == job_id, Job.user_id == user_id))
    return result.scalar_one_or_none()


async def create_job(db: AsyncSession, user_id: int, data: JobIn) -> Job:
    """新建。user_id 由调用方（服务端身份）提供，不接受客户端传入。"""
    job = Job(user_id=user_id, **data.model_dump())
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def update_job(db: AsyncSession, user_id: int, job_id: int, data: JobUpdate) -> Job | None:
    """部分更新。查不到（或不属于该用户）返回 None。"""
    result = await db.execute(select(Job).where(Job.id == job_id, Job.user_id == user_id))
    job = result.scalar_one_or_none()
    if job is None:
        return None

    payload = data.model_dump(exclude_unset=True)
    for key, value in payload.items():
        setattr(job, key, value)

    await db.commit()
    await db.refresh(job)
    return job


async def delete_job(db: AsyncSession, user_id: int, job_id: int) -> bool:
    """删除。删成功返回 True；不存在（或不属于该用户）返回 False。"""
    result = await db.execute(select(Job).where(Job.id == job_id, Job.user_id == user_id))
    job = result.scalar_one_or_none()
    if job is None:
        return False

    await db.delete(job)
    await db.commit()
    return True

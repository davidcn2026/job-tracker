from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.schemas.job import JobIn, JobUpdate
from app.schemas.llm import AnalysisResult, InterviewPrep


async def list_jobs(
    db: AsyncSession,
    user_id: int,
    page: int,
    page_size: int,
    status: str | None = None,
    source: str | None = None,
    q: str | None = None,
) -> tuple[list[Job], int]:
    """返回 (当前页数据, 总数)。所有查询强制带 user_id。

    三个筛选项互相独立、可任意组合（按 BACKLOG 已定结论：
    筛选靠 query 参数，不新增 /jobs/search 这类路由）。
    """
    where = [Job.user_id == user_id]

    if status:
        where.append(Job.status == status)
    if source:
        where.append(Job.source == source)
    if q:
        # 模糊搜索公司名 / 岗位名 / 公司业务。
        # 不搜 JD 全文：data 量大且 MySQL 的 LIKE %x% 无法走索引，
        # 真要全文搜索应该上 FULLTEXT 或独立搜索引擎，不在这里假装支持。
        like = f"%{q}%"
        where.append(
            or_(
                Job.company.like(like),
                Job.position.like(like),
                Job.company_business.like(like),
            )
        )

    total = await db.scalar(select(func.count()).select_from(Job).where(*where)) or 0

    result = await db.execute(
        select(Job)
        .where(*where)
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


async def save_analysis(db: AsyncSession, job: Job, result: AnalysisResult) -> Job:
    """写入 AI 分析结果。

    analysis 存完整 JSON（而不只是结论文字），便于将来回看模型当时给出的
    全部细节（matched / gaps / blocking_gaps）。analyzed_at 用本地时间，
    与数据库 DATETIME 的存储约定保持一致。
    """
    job.match_score = result.match_score
    job.verdict = result.verdict
    job.analysis = result.model_dump_json()
    job.analyzed_at = datetime.now()

    await db.commit()
    await db.refresh(job)
    return job


async def clear_analysis(db: AsyncSession, job: Job) -> Job:
    """作废已有的分析结果。

    JD 改了之后旧分数就没有意义了（可能从 82 分掉到 45 分）。
    清空四个字段 → 岗位回到"未分析"分组 → 由自动分析重新打分。
    """
    job.match_score = None
    job.verdict = None
    job.analysis = None
    job.analyzed_at = None

    await db.commit()
    await db.refresh(job)
    return job


async def save_interview_prep(db: AsyncSession, job: Job, prep: InterviewPrep) -> Job:
    """写入面试准备（JSON）。

    存下来而不是每次现生成：生成一次约 20 秒、几千 token，
    用户会反复回来复习，重复生成纯属浪费。
    """
    job.interview_prep = prep.model_dump_json()
    job.interview_prep_at = datetime.now()

    await db.commit()
    await db.refresh(job)
    return job


async def clear_interview_prep(db: AsyncSession, job: Job) -> Job:
    """作废面试准备。JD 改了之后，原来生成的预测题就没有意义了。"""
    job.interview_prep = None
    job.interview_prep_at = None

    await db.commit()
    await db.refresh(job)
    return job

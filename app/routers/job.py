from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.crud import job as crud_job
from app.db.session import get_database
from app.models import User
from app.schemas.job import JobDeleted, JobDetail, JobIn, JobListData, JobOut, JobUpdate
from app.schemas.response import Resp
from app.services.llm import LLMError, analyze_jd

router = APIRouter(prefix="/api/v1", tags=["jobs"])


@router.get("/jobs", response_model=Resp[JobListData])
async def list_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
):
    rows, total = await crud_job.list_jobs(db, current_user.id, page, page_size)

    return Resp(
        data=JobListData(
            list=[JobOut.model_validate(r) for r in rows],
            total=total,
            page=page,
            page_size=page_size,
            has_more=page * page_size < total,
        )
    )


@router.get("/jobs/{job_id}", response_model=Resp[JobDetail])
async def get_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database)
):

    job = await crud_job.get_job(db, current_user.id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"没有 id={job_id} 这条岗位")
    return Resp(data=JobDetail.model_validate(job))


@router.post("/jobs", status_code=201, response_model=Resp[JobDetail])
async def create_job(
    payload: JobIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database)
):

    try:
        job = await crud_job.create_job(db, current_user.id, payload)
    except IntegrityError:
        raise HTTPException(status_code=409, detail="该公司下已有这个岗位") from None
    return Resp(code=201, data=JobDetail.model_validate(job))


@router.patch("/jobs/{job_id}", response_model=Resp[JobDetail])
async def update_job(
    job_id: int,
    payload: JobUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
):
    try:
        job = await crud_job.update_job(db, current_user.id, job_id, payload)
    except IntegrityError:
        raise HTTPException(status_code=409, detail="该公司下已有这个岗位") from None

    if job is None:
        raise HTTPException(status_code=404, detail=f"没有 id={job_id} 这条岗位")
    return Resp(data=JobDetail.model_validate(job))


@router.delete("/jobs/{job_id}", response_model=Resp[JobDeleted])
async def delete_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database)
):

    deleted = await crud_job.delete_job(db, current_user.id, job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"没有 id={job_id} 这条岗位")
    return Resp(data=JobDeleted(deleted_id=job_id))

@router.post("/jobs/{job_id}/analyze", response_model=Resp[JobDetail])
async def analyze_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
) -> Resp[JobDetail]:
    """对已录入的岗位跑 AI 匹配分析，写入分数与投递建议档位。"""

    # TODO(1/5) 查岗位
    #   用 crud_job.get_job(db, current_user.id, job_id) 拿到 job
    #   job is None → raise HTTPException(404, detail=f"没有 id={job_id} 这条岗位")
    job = await crud_job.get_job(db, current_user.id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"没有 id={job_id} 这条岗位")

    # TODO(2/5) 没有 JD 原文就拒绝
    #   条件：job.description 为空，或去掉空白后为空
    #   → raise HTTPException(422, detail="这条记录没有 JD 原文，无法分析")
    if not job.description or not job.description.strip():
        raise HTTPException(status_code=422, detail="这条记录没有 JD 原文，无法分析")

    # TODO(3/5) 防重复触发
    #   job.analyzed_at 不为 None 时，算它距今多少秒
    #   小于 10 秒 → raise HTTPException(429, detail="分析过于频繁，请 10 秒后再试")
    #   注意：这一步必须在调 LLM 之前，否则等于"先花钱再拒绝"
    if job.analyzed_at is not None:
        elapsed = (datetime.now() - job.analyzed_at).total_seconds()
        if elapsed < 10:
            raise HTTPException(status_code=429, detail="分析过于频繁，请 10 秒后再试")

    # TODO(4/5) 调模型
    #   result = await analyze_jd(job.description)
    #   用 try / except LLMError 包住
    #   → raise HTTPException(503, detail="AI 分析暂时不可用，请稍后重试") from None
    try:
        result = await analyze_jd(job.description)
    except LLMError:
        raise HTTPException(status_code=503, detail="AI 分析暂时不可用，请稍后重试") from None

    # TODO(5/5) 保存并返回（下面两行已给出，不用改）
    job = await crud_job.save_analysis(db, job, result)
    return Resp(data=JobDetail.model_validate(job))
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.crud import job as crud_job
from app.db.session import get_database
from app.models import User
from app.schemas.job import JobDeleted, JobDetail, JobIn, JobListData, JobOut, JobUpdate
from app.schemas.response import Resp

router = APIRouter(prefix="/api/v1", tags=["jobs"])


@router.get("/jobs")
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


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database)
):

    job = await crud_job.get_job(db, current_user.id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"没有 id={job_id} 这条岗位")
    return Resp(data=JobDetail.model_validate(job))


@router.post("/jobs", status_code=201)
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


@router.patch("/jobs/{job_id}")
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


@router.delete("/jobs/{job_id}")
async def delete_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database)
):

    deleted = await crud_job.delete_job(db, current_user.id, job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"没有 id={job_id} 这条岗位")
    return Resp(data=JobDeleted(deleted_id=job_id))

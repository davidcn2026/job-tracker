"""面试复盘接口：记录真实被问到的问题。

单独一个文件而不是塞进 routers/job.py：
    job.py 已经有 CRUD + 截图识别 + AI 分析 + 自动打分。
    面试复盘是独立的一生（录入、修正、将来做题库聚合），值得自己的位置。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.crud import interview_record as crud_record
from app.crud import job as crud_job
from app.db.session import get_database
from app.models import User
from app.schemas.interview_record import InterviewRecordIn, InterviewRecordOut
from app.schemas.response import Resp

router = APIRouter(prefix="/api/v1", tags=["interview-record"])

# 记了一次真实面试，岗位状态理应往前推。
# 只在这三个状态时改，已面试/已挂不动 —— 不动用户已经确认过的结果。
_STATUS_TO_ADVANCE = ("待投", "已投", "预约面试")


async def _get_job_or_404(db: AsyncSession, user_id: int, job_id: int):
    job = await crud_job.get_job(db, user_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"没有 id={job_id} 这条岗位")
    return job


@router.get("/jobs/{job_id}/interviews", response_model=Resp[list[InterviewRecordOut]])
async def list_interviews(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
) -> Resp[list[InterviewRecordOut]]:
    await _get_job_or_404(db, current_user.id, job_id)
    records = await crud_record.list_records(db, current_user.id, job_id)
    return Resp(data=[InterviewRecordOut.model_validate(r) for r in records])


@router.post("/jobs/{job_id}/interviews", response_model=Resp[InterviewRecordOut])
async def create_interview(
    job_id: int,
    payload: InterviewRecordIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
) -> Resp[InterviewRecordOut]:
    job = await _get_job_or_404(db, current_user.id, job_id)

    record = await crud_record.create_record(db, current_user.id, job_id, payload)

    # 记了面试就说明面过了：状态停在"待投/已投/预约面试"时往前推一格
    if job.status in _STATUS_TO_ADVANCE:
        job.status = "已面试"
        await db.commit()

    return Resp(data=InterviewRecordOut.model_validate(record))


@router.patch(
    "/jobs/{job_id}/interviews/{record_id}", response_model=Resp[InterviewRecordOut]
)
async def update_interview(
    job_id: int,
    record_id: int,
    payload: InterviewRecordIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
) -> Resp[InterviewRecordOut]:
    await _get_job_or_404(db, current_user.id, job_id)

    record = await crud_record.get_record(db, current_user.id, record_id)
    if record is None or record.job_id != job_id:
        raise HTTPException(status_code=404, detail="没有这条面试记录")

    record = await crud_record.replace_record(db, record, payload)
    return Resp(data=InterviewRecordOut.model_validate(record))


@router.delete("/jobs/{job_id}/interviews/{record_id}", response_model=Resp[dict])
async def delete_interview(
    job_id: int,
    record_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
) -> Resp[dict]:
    await _get_job_or_404(db, current_user.id, job_id)

    record = await crud_record.get_record(db, current_user.id, record_id)
    if record is None or record.job_id != job_id:
        raise HTTPException(status_code=404, detail="没有这条面试记录")

    await crud_record.delete_record(db, record)
    return Resp(data={"deleted_id": record_id})

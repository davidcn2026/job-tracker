"""面试准备接口。

单独一个文件而不是塞进 routers/job.py：
    job.py 已经有 5 个 CRUD + 截图识别 + AI 分析，再塞一个"生成面试题"就成混合文件了。
    这个功能有独立的一生（生成、缓存、按 JD/简历变化作废），值得自己的位置。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.crud import job as crud_job
from app.db.session import get_database
from app.models import User
from app.schemas.job import JobDetail
from app.schemas.response import Resp
from app.services.llm import LLMError, generate_interview_prep

router = APIRouter(prefix="/api/v1", tags=["interview"])


@router.get("/jobs/{job_id}/interview-prep", response_model=Resp[JobDetail])
async def read_interview_prep(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
) -> Resp[JobDetail]:
    """读已生成的面试准备（没有就是 None，前端据此显示"生成"按钮）。"""
    job = await crud_job.get_job(db, current_user.id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"没有 id={job_id} 这条岗位")
    return Resp(data=JobDetail.model_validate(job))


@router.post("/jobs/{job_id}/interview-prep", response_model=Resp[JobDetail])
async def create_interview_prep(
    job_id: int,
    force: bool = Query(False, description="已生成过时强制重新生成"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
) -> Resp[JobDetail]:
    """按 JD + 简历生成面试准备（预测题 + 参考答案 + 弱点标注）。

    生成一次约 20 秒、几千 token，所以结果存库：用户会反复回来看，
    重复生成纯属浪费。改了 JD 会自动作废（PATCH /jobs 里处理）；
    改了简历想重算，加 force=true。
    """
    job = await crud_job.get_job(db, current_user.id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"没有 id={job_id} 这条岗位")

    if not (job.description or "").strip():
        raise HTTPException(status_code=422, detail="这条记录没有 JD 原文，无法预测面试题")

    profile = (current_user.profile_text or "").strip()
    if not profile:
        raise HTTPException(
            status_code=422,
            detail="请先在右上角「简历」里上传你的简历，面试题要按你的经历来出",
        )

    if job.interview_prep and not force:
        raise HTTPException(
            status_code=409,
            detail="这个岗位已经生成过面试准备；改了 JD 会自动失效，改了简历可加 force=true 重生成",
        )

    try:
        prep = await generate_interview_prep(job.description, profile)
    except LLMError:
        raise HTTPException(status_code=503, detail="生成面试准备失败，请稍后重试") from None

    job = await crud_job.save_interview_prep(db, job, prep)
    return Resp(data=JobDetail.model_validate(job))

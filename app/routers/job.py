
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.crud import job as crud_job
from app.db.session import get_database
from app.models import User
from app.schemas.job import JobDeleted, JobDetail, JobIn, JobListData, JobOut, JobUpdate
from app.schemas.llm import JobDraft
from app.schemas.response import Resp
from app.services import auto_analyze
from app.services.llm import LLMError, analyze_jd, extract_job_from_image

router = APIRouter(prefix="/api/v1", tags=["jobs"])

# 截图大小上限。手机上长截图常见 1~3 MB，10 MB 足够，也防止有人传巨大文件耗内存。
MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


@router.get("/jobs", response_model=Resp[JobListData])
async def list_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None, description="按状态筛选"),
    source: str | None = Query(None, description="按招聘渠道筛选"),
    q: str | None = Query(None, max_length=50, description="按公司/岗位/业务模糊搜索"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
):
    rows, total = await crud_job.list_jobs(
        db, current_user.id, page, page_size,
        status=status, source=source, q=q,
    )

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
        raise HTTPException(status_code=409, detail="该公司这个岗位已通过同一渠道录入过") from None

    # 录入即分析：用户不该为了拿到分数去点按钮。
    # 有 JD 才排队；没简历时后台会自己跳过（拿别人的经历评判会失真）。
    if (payload.description or "").strip():
        auto_analyze.schedule(job.id, current_user.id)

    return Resp(code=201, data=JobDetail.model_validate(job))


@router.post("/jobs/extract", response_model=Resp[JobDraft])
async def extract_job(
    image: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """招聘截图 → 岗位草稿。

    **只返回草稿，不写库。** 前端拿到后预填到「新增」表单，由用户确认再保存。
    这样模型看错时你能当场发现，而不是错误数据静默进库。
    """
    mime = (image.content_type or "").lower()
    if mime not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"不支持的图片格式：{mime or '未知'}，请上传 PNG/JPEG/WebP",
        )

    content = await image.read()
    if not content:
        raise HTTPException(status_code=422, detail="图片内容为空")
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=422,
            detail=f"图片太大（{len(content) // 1024} KB），上限 10 MB",
        )

    try:
        draft = await extract_job_from_image(content, mime)
    except LLMError:
        raise HTTPException(status_code=503, detail="截图识别暂时不可用，请稍后重试") from None

    return Resp(data=draft)


@router.patch("/jobs/{job_id}", response_model=Resp[JobDetail])
async def update_job(
    job_id: int,
    payload: JobUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
):
    # JD 改了就作废旧分数：岗位可能从 82 分掉到 45 分，留着旧分是误导。
    # 所以先取旧值比对，更新后再决定是否重算。
    before = await crud_job.get_job(db, current_user.id, job_id)
    if before is None:
        raise HTTPException(status_code=404, detail=f"没有 id={job_id} 这条岗位")
    old_description = (before.description or "").strip()

    try:
        job = await crud_job.update_job(db, current_user.id, job_id, payload)
    except IntegrityError:
        raise HTTPException(status_code=409, detail="该公司这个岗位已通过同一渠道录入过") from None

    if job is None:
        raise HTTPException(status_code=404, detail=f"没有 id={job_id} 这条岗位")

    new_description = (job.description or "").strip()
    if new_description and new_description != old_description:
        await crud_job.clear_analysis(db, job)
        auto_analyze.schedule(job.id, current_user.id)

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
    """对已录入的岗位跑 AI 匹配分析，写入分数与投递建议档位。

    判断顺序是刻意安排的：
      404 没这个岗位 → 422 没 JD → 422 没简历 → 429 太频繁 → 调模型 → 保存
    越便宜的检查越靠前；尤其 429 必须在调模型之前，否则等于"先花钱再拒绝"。
    """
    job = await crud_job.get_job(db, current_user.id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"没有 id={job_id} 这条岗位")

    if not job.description or not job.description.strip():
        raise HTTPException(status_code=422, detail="这条记录没有 JD 原文，无法分析")

    # 简历现在是"用户上传"的，不再是代码里写死的。
    # 没有简历就不做分析：拿别人的经历评判你的岗位匹配度，结论毫无意义。
    profile = (current_user.profile_text or "").strip()
    if not profile:
        raise HTTPException(
            status_code=422,
            detail="请先在右上角「简历」里上传你的简历，AI 才能做个性化匹配分析",
        )

    # 打分是幂等的：已经分析过就不再重算。
    # 只有 JD 改动时（PATCH 里会清空 analyzed_at）才允许重新打分，
    # 所以这个接口现在只用于"补跑"老数据，或自动分析失败后的手动兜底。
    if job.analyzed_at is not None:
        raise HTTPException(
            status_code=409,
            detail="这个岗位已经打过分了。只有修改 JD 后才会重新分析，避免重复花钱。",
        )

    try:
        result = await analyze_jd(job.description, profile)
    except LLMError:
        raise HTTPException(status_code=503, detail="AI 分析暂时不可用，请稍后重试") from None

    job = await crud_job.save_analysis(db, job, result)
    return Resp(data=JobDetail.model_validate(job))
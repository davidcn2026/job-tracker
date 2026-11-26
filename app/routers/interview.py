"""面试练习接口：拆关键点、提交回答（评估+追问）、手动标记状态。

单独一个文件而不是塞进 routers/job.py：
    job.py 已经有 CRUD + 截图识别 + AI 分析，再塞"面试练习"就成混合文件了。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.crud import interview as crud_interview
from app.crud import job as crud_job
from app.db.session import get_database
from app.models import User
from app.schemas.job import JobDetail
from app.schemas.llm import InterviewPrep, InterviewQuestion
from app.schemas.response import Resp
from app.services.interview import (
    MAX_DEPTH,
    derive_status,
    evaluate_answer,
    extract_key_points,
    question_hash,
)
from app.services.llm import LLMError, generate_interview_prep

router = APIRouter(prefix="/api/v1", tags=["interview"])


# ---------- 请求体 ----------


class AnswerIn(BaseModel):
    question_hash: str = Field(min_length=8, max_length=16)
    answer: str = Field(min_length=1, max_length=8000)


class StatusIn(BaseModel):
    status: str = Field(pattern="^(wrong|tried|mastered)$")


# ---------- 工具 ----------


def _load_prep(job) -> InterviewPrep:
    """把 job.interview_prep 解析成结构。没有就 422。"""
    if not job.interview_prep:
        raise HTTPException(
            status_code=422, detail="这个岗位还没生成面试准备，先生成再练"
        )
    try:
        return InterviewPrep.model_validate_json(job.interview_prep)
    except Exception:
        raise HTTPException(
            status_code=422, detail="面试准备数据损坏，请重新生成"
        ) from None


def _find_question(prep: InterviewPrep, target_hash: str) -> InterviewQuestion:
    for question in prep.questions:
        if question_hash(question.question) == target_hash:
            return question
    raise HTTPException(
        status_code=404, detail="没找到这道题（可能面试准备已重新生成）"
    )


# ---------- 接口 ----------


@router.post("/jobs/{job_id}/interview-prep/key-points", response_model=Resp[JobDetail])
async def fill_key_points(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
) -> Resp[JobDetail]:
    """给已有的面试题批量补「必须说到的要点」。

    为什么单独一个接口而不是重新生成整套：
        重新生成会覆盖已有题目（用户可能已经练过），
        而且要多等 26 秒。这里只补一个字段。
    """
    job = await crud_job.get_job(db, current_user.id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"没有 id={job_id} 这条岗位")

    prep = _load_prep(job)
    pending = [q for q in prep.questions if not q.key_points]
    if not pending:
        return Resp(data=JobDetail.model_validate(job))

    try:
        points = await extract_key_points(pending)
    except LLMError:
        raise HTTPException(status_code=503, detail="拆解关键点失败，请稍后重试") from None

    for question, item in zip(pending, points, strict=False):
        question.key_points = item

    job.interview_prep = prep.model_dump_json()
    await db.commit()
    await db.refresh(job)
    return Resp(data=JobDetail.model_validate(job))


@router.get("/jobs/{job_id}/answers", response_model=Resp[list[dict]])
async def list_answers(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
) -> Resp[list[dict]]:
    """这道岗位下所有题的练习状态（前端据此渲染进度和错题本）。"""
    records = await crud_interview.list_answers(db, current_user.id, job_id)
    return Resp(
        data=[
            {
                "question_hash": r.question_hash,
                "status": r.status,
                "depth": r.depth,
                "covered": r.covered or [],
                "wrong": r.wrong or [],
                "missing": r.missing or [],
                "answer": r.answer,
                "transcript": r.transcript or [],
                "finish_reason": r.finish_reason,
                "verdict": r.last_verdict,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in records
        ]
    )


@router.post("/jobs/{job_id}/answers", response_model=Resp[dict])
async def submit_answer(
    job_id: int,
    payload: AnswerIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
) -> Resp[dict]:
    """提交一次回答：评估关键点覆盖 + 按当前层数给出下一层追问。

    评估和追问合并成一次调用——两者输入完全相同，分开只是多花输入 token。

    层数流转（每题最多 4 次提交）：
      depth 0 → 追问第 1 层（事实）
      depth 1 → 追问第 2 层（决策）
      depth 2 → 追问第 3 层（边界）
      depth 3 → 不再追问，收口出总结
    """
    job = await crud_job.get_job(db, current_user.id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"没有 id={job_id} 这条岗位")

    prep = _load_prep(job)
    question = _find_question(prep, payload.question_hash)

    # 没有要点就没法判断覆盖，先补
    if not question.key_points:
        raise HTTPException(
            status_code=422, detail="这道题还没拆解关键点，先点「拆解关键点」"
        )

    record = await crud_interview.get_answer(
        db, current_user.id, job_id, payload.question_hash
    )
    # 必须逐条拷成新 dict：JSON 列不检测嵌套原地修改，
    # 直接 list() 浅拷贝再改 transcript[-1]["answer"] 不会落库。
    transcript = [dict(item) for item in (record.transcript or [])] if record else []
    depth = record.depth if record else 0

    # transcript 的语义：每一轮是「问了什么 + 答了什么」的完整配对。
    # 还没被回答的那条追问以 answer=None 存着，等下次提交时补上。
    if not transcript:
        # 第一次提交：这一答对应的是卡片上的原题
        transcript.append(
            {"layer": "0", "question": question.question, "answer": payload.answer}
        )
        history: list[dict] = []
    else:
        # 后续提交：这一答对应上一条待答的追问
        transcript[-1]["answer"] = payload.answer
        # 历史 = 除刚答的这条之外的所有已完成轮次（当前答案单独传）
        history = transcript[:-1]

    try:
        evaluation = await evaluate_answer(question, history, payload.answer, depth)
    except LLMError:
        raise HTTPException(status_code=503, detail="评估失败，请稍后重试") from None

    if evaluation.next_question:
        # 挂一条待答的追问，等用户下次提交时补答案
        transcript.append(
            {
                "layer": str(depth + 1),
                "question": evaluation.next_question,
                "answer": None,
            }
        )
        new_depth = min(depth + 1, MAX_DEPTH)
        finish_reason = None
    else:
        new_depth = depth
        finish_reason = "max_depth"

    status = derive_status(
        covered=len(evaluation.covered),
        total=len(question.key_points),
        depth=new_depth,
    )

    await crud_interview.upsert_answer(
        db,
        current_user.id,
        job_id,
        payload.question_hash,
        answer=payload.answer,
        covered=evaluation.covered,
        wrong=[item.model_dump() for item in evaluation.wrong],
        missing=evaluation.missing,
        depth=new_depth,
        transcript=transcript,
        finish_reason=finish_reason,
        last_verdict=evaluation.verdict,
        status=status,
    )

    return Resp(
        data={
            "covered": evaluation.covered,
            "wrong": [item.model_dump() for item in evaluation.wrong],
            "missing": evaluation.missing,
            "verdict": evaluation.verdict,
            "next_question": evaluation.next_question,
            "next_layer": evaluation.next_layer,
            "depth": new_depth,
            "max_depth": MAX_DEPTH,
            "status": status,
            "total_points": len(question.key_points),
            "transcript": transcript,
        }
    )


@router.patch("/jobs/{job_id}/answers/{target_hash}", response_model=Resp[dict])
async def set_status(
    job_id: int,
    target_hash: str,
    payload: StatusIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
) -> Resp[dict]:
    """手动标记状态：我不会 / 练过了 / 已掌握。

    **不调用模型**——用户说"我不会"时，模型必然判全部 missing，
    没必要花一次调用去确认已知事实。
    """
    record = await crud_interview.upsert_answer(
        db, current_user.id, job_id, target_hash, status=payload.status
    )
    return Resp(
        data={
            "question_hash": record.question_hash,
            "status": record.status,
            "depth": record.depth,
        }
    )


@router.post("/jobs/{job_id}/interview-prep", response_model=Resp[JobDetail])
async def create_interview_prep(
    job_id: int,
    force: bool = Query(False, description="已生成过时强制重新生成"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
) -> Resp[JobDetail]:
    """按 JD + 简历生成面试准备（预测题 + 参考答案 + 弱点标注）。"""
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


@router.get("/jobs/{job_id}/interview-prep", response_model=Resp[JobDetail])
async def read_interview_prep(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
) -> Resp[JobDetail]:
    """读已生成的面试准备。"""
    job = await crud_job.get_job(db, current_user.id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"没有 id={job_id} 这条岗位")
    return Resp(data=JobDetail.model_validate(job))



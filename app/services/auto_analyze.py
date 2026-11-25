"""录入岗位后自动分析（打分），用户不需要点任何按钮。

为什么放后台任务而不是在 POST /jobs 里同步跑：
    一次分析要 2~10 秒，塞进创建接口会让"保存"按钮卡住。
    先返回 201，分析在后台跑，前端轮询拿结果。

进程内状态 `_inflight` 的作用：
    防止同一个岗位被并发分析两次（连点保存、或创建和编辑几乎同时发生）。
    进程重启会丢，但那只影响"这一次没跑完"，前端轮询会发现仍无分数，
    用户可以手动点一次「AI 分析」兜底。

失败不重试：失败就留在"未分析"分组里，可见、可手动补。
静默重试会让账单不可预期。
"""

from __future__ import annotations

import asyncio
import logging

from app.crud import job as crud_job
from app.db.session import AsyncSessionLocal
from app.models import User
from app.services.llm import LLMError, analyze_jd

logger = logging.getLogger(__name__)

_inflight: set[int] = set()


def schedule(job_id: int, user_id: int) -> None:
    """把一个岗位排进后台分析队列（立即返回）。"""
    if job_id in _inflight:
        return
    _inflight.add(job_id)
    asyncio.create_task(_run(job_id, user_id))


async def _run(job_id: int, user_id: int) -> None:
    try:
        # 后台任务必须自己开 session：请求的 session 在这个任务跑完前就关闭了
        async with AsyncSessionLocal() as db:
            job = await crud_job.get_job(db, user_id, job_id)
            if job is None:
                return

            if not (job.description or "").strip():
                return  # 没有 JD 就没什么可分析的

            user = await db.get(User, user_id)
            profile = (user.profile_text or "").strip() if user else ""
            if not profile:
                # 没简历：分析会失真（拿别人的经历评判），宁可不做
                logger.info("跳过自动分析 job_id=%s：用户还没有简历", job_id)
                return

            result = await analyze_jd(job.description, profile)
            await crud_job.save_analysis(db, job, result)
            logger.info(
                "自动分析完成 job_id=%s score=%s verdict=%s",
                job_id, result.match_score, result.verdict,
            )
    except LLMError as e:
        logger.warning("自动分析失败 job_id=%s：%s", job_id, e)
    except Exception:
        logger.exception("自动分析异常 job_id=%s", job_id)
    finally:
        _inflight.discard(job_id)


def is_running(job_id: int) -> bool:
    return job_id in _inflight

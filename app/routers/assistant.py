from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_database
from app.models import AssistantMessage, Job, User
from app.schemas.assistant import AssistantChatIn, AssistantChatOut, AssistantMessageOut
from app.schemas.response import Resp
from app.services.assistant import chat
from app.services.llm import LLMError

router = APIRouter(prefix="/api/v1", tags=["assistant"])

# 一次最多返回多少条历史。手机端渲染太多会卡，且模型只吃最近 12 条。
HISTORY_PAGE = 80


@router.get("/assistant/messages", response_model=Resp[list[AssistantMessageOut]])
async def list_messages(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
) -> Resp[list[AssistantMessageOut]]:
    """当前用户的助手对话历史（含工具调用记录）。"""
    rows = await db.execute(
        select(AssistantMessage)
        .where(AssistantMessage.user_id == current_user.id)
        .order_by(AssistantMessage.id.desc())
        .limit(HISTORY_PAGE)
    )
    messages = list(reversed(rows.scalars().all()))
    return Resp(data=[AssistantMessageOut.model_validate(m) for m in messages])


@router.post("/assistant/messages", response_model=Resp[AssistantChatOut])
async def send_message(
    payload: AssistantChatIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
) -> Resp[AssistantChatOut]:
    """给助手发一句话，返回它的回答。

    助手是**全局唯一**的（不是每个岗位一个对话），它能读到整个岗位库，
    需要公司信息时会自己调用 web_search。
    """
    jobs = list(
        (
            await db.execute(select(Job).where(Job.user_id == current_user.id))
        ).scalars().all()
    )

    try:
        reply = await chat(db, current_user, payload.content.strip(), jobs)
    except LLMError:
        raise HTTPException(status_code=503, detail="助手暂时不可用，请稍后重试") from None

    return Resp(data=AssistantChatOut(reply=AssistantMessageOut.model_validate(reply)))


@router.delete("/assistant/messages", response_model=Resp[dict])
async def clear_messages(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
) -> Resp[dict]:
    """清空对话历史（岗位库和简历不受影响）。"""
    await db.execute(
        delete(AssistantMessage).where(AssistantMessage.user_id == current_user.id)
    )
    await db.commit()
    return Resp(data={"cleared": True})

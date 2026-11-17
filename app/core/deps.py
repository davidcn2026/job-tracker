from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import token_hash
from app.db.session import get_database
from app.models.user import User


async def get_current_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_database),
) -> User:
    # ① 没带这个头 → 401
    if not authorization:
        raise HTTPException(status_code=401, detail="未认证或登录已失效")

    # ② 到这里 authorization 一定是 str，可以安全调用 .removeprefix()
    token = authorization.removeprefix("Bearer ").strip()

    user = await db.scalar(select(User).where(User.token == token_hash(token)))
    if user is None:
        raise HTTPException(status_code=401, detail="未认证或登录已失效")
    return user
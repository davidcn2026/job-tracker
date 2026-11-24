from datetime import datetime, timedelta

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import token_hash
from app.db.session import get_database
from app.models.user import User

UNAUTHORIZED = "未认证或登录已失效"


def token_expiry(now: datetime | None = None) -> datetime:
    """新建 token 时用的过期时间。"""
    base = now or datetime.now()
    return base + timedelta(days=settings.token_ttl_days)


async def get_current_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_database),
) -> User:
    # ① 没带这个头 → 401
    if not authorization:
        raise HTTPException(status_code=401, detail=UNAUTHORIZED)

    # ② 到这里 authorization 一定是 str，可以安全调用 .removeprefix()
    token = authorization.removeprefix("Bearer ").strip()

    user = await db.scalar(select(User).where(User.token == token_hash(token)))
    if user is None:
        raise HTTPException(status_code=401, detail=UNAUTHORIZED)

    # ③ 过期检查 + 滑动续期
    #    token_expires_at 为 NULL 的历史 token 视为不过期（向后兼容，不会突然把人踢掉）
    if user.token_expires_at is not None:
        now = datetime.now()

        if user.token_expires_at < now:
            # 过期：顺手清掉库里的 token，让这个 token 立刻彻底作废
            user.token = None
            user.token_expires_at = None
            await db.commit()
            raise HTTPException(status_code=401, detail="登录已过期，请重新登录")

        # 滑动续期：只在剩余不足 token_renew_window_days 天时才续。
        # 这样正常每天使用的人会一直被续满，而写库频率大约是每 23 天才 1 次，
        # 不是每个请求都 UPDATE。
        remaining = user.token_expires_at - now
        if remaining < timedelta(days=settings.token_renew_window_days):
            user.token_expires_at = token_expiry(now)
            await db.commit()

    return user

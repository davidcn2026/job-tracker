from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.security import generate_token, hash_password, token_hash, verify_password
from app.crud import user as crud_user
from app.db.session import get_database
from app.models import User
from app.schemas.response import Resp
from app.schemas.user import LoginIn, RegisterIn, TokenOut, UserOut

router = APIRouter(prefix="/api/v1", tags=["auth"])

@router.post("/auth/login", response_model=Resp[TokenOut])
async def login(
    payload: LoginIn,
    db: AsyncSession = Depends(get_database),
) -> Resp[TokenOut]:

    user = await db.scalar(select(User).where(User.name == payload.name))

    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = generate_token()
    user.token = token_hash(token)
    await db.commit()

    return Resp(data=TokenOut(token=token, user=UserOut.model_validate(user)))

@router.get("/users/me", response_model=Resp[UserOut])
async def read_me(current_user: User = Depends(get_current_user),) -> Resp[UserOut]:

    return Resp(data=UserOut.model_validate(current_user))

@router.post("/auth/register", response_model=Resp[TokenOut], status_code=201)
async def register(
    payload: RegisterIn,
    db: AsyncSession = Depends(get_database),
) -> Resp[TokenOut]:
    # 准入（开关 + 邀请码）
    if not settings.register_open:
        raise HTTPException(status_code=403, detail="注册当前未开放")
    if settings.register_code and payload.code != settings.register_code:
        raise HTTPException(status_code=403, detail="邀请码不正确")

    # 创建（唯一约束兜住并发竞态）
    try:
        user = await crud_user.create_user(
            db,
            payload.name,
            hash_password(payload.password),
        )
    except IntegrityError:
        raise HTTPException(status_code=409, detail="用户名已被占用") from None
    # 直接发 token （省一次登录请求）
    token = generate_token()
    user.token = token_hash(token)
    await db.commit()

    return Resp(code=201, data=TokenOut(token=token,user=UserOut.model_validate(user)))
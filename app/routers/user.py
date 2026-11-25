from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user, token_expiry
from app.core.security import generate_token, hash_password, token_hash, verify_password
from app.crud import user as crud_user
from app.db.session import get_database
from app.models import User
from app.schemas.response import Resp
from app.schemas.user import (
    LoginIn,
    ProfileImportOut,
    ProfileIn,
    ProfileOut,
    RegisterIn,
    TokenOut,
    UserOut,
)
from app.services.resume import ResumeError, extract_resume_text_async

router = APIRouter(prefix="/api/v1", tags=["auth"])

# 简历文件大小上限：PDF 一般 100~500 KB，10 MB 足够，也防超大文件占内存
MAX_RESUME_BYTES = 10 * 1024 * 1024

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
    # 记首次过期时间；之后由 get_current_user 做滑动续期
    user.token_expires_at = token_expiry()
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
    user.token_expires_at = token_expiry()
    await db.commit()

    return Resp(code=201, data=TokenOut(token=token,user=UserOut.model_validate(user)))


# ===== 简历 =====
# 为什么解析和保存分成两个接口：
#   解析可能出错（PDF 是扫描件、排版复杂、OCR 认错字）。
#   先返回文本让用户看一眼、改一改，确认后才 PUT 保存 ——
#   和截图识别岗位是同一个原则：机器给草稿，人做决定。


def _profile_out(user: User) -> ProfileOut:
    text = user.profile_text
    return ProfileOut(
        text=text,
        updated_at=user.profile_updated_at,
        chars=len(text) if text else 0,
    )


@router.get("/users/me/profile", response_model=Resp[ProfileOut])
async def read_profile(current_user: User = Depends(get_current_user)) -> Resp[ProfileOut]:
    """读取当前用户的简历。没上传过时 text 为 null。"""
    return Resp(data=_profile_out(current_user))


@router.put("/users/me/profile", response_model=Resp[ProfileOut])
async def save_profile(
    payload: ProfileIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
) -> Resp[ProfileOut]:
    """保存简历文本（直接粘贴，或确认过解析结果后保存）。"""
    current_user.profile_text = payload.text
    current_user.profile_updated_at = datetime.now()
    await db.commit()
    await db.refresh(current_user)
    return Resp(data=_profile_out(current_user))


@router.delete("/users/me/profile", response_model=Resp[ProfileOut])
async def clear_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
) -> Resp[ProfileOut]:
    """清空简历。清空后 AI 分析会提示先上传简历。"""
    current_user.profile_text = None
    current_user.profile_updated_at = None
    await db.commit()
    await db.refresh(current_user)
    return Resp(data=_profile_out(current_user))


@router.post("/users/me/profile/import", response_model=Resp[ProfileImportOut])
async def import_profile(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> Resp[ProfileImportOut]:
    """上传 PDF / DOCX / TXT / 图片 → 解析出文本。

    **不保存**。前端拿到文本后填进编辑框，用户确认后才调用 PUT 保存。
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="文件内容为空")
    if len(data) > MAX_RESUME_BYTES:
        raise HTTPException(
            status_code=422,
            detail=f"文件太大（{len(data) // 1024} KB），上限 10 MB",
        )

    try:
        text = await extract_resume_text_async(
            data, file.filename or "", file.content_type or ""
        )
    except ResumeError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None

    return Resp(
        data=ProfileImportOut(text=text, chars=len(text), filename=file.filename)
    )
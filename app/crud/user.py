from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def get_by_name(db: AsyncSession, name: str) -> User | None:
    return await db.scalar(select(User).where(User.name == name))


async def create_user(db: AsyncSession, name: str, password_hash: str) -> User:
    user = User(name=name, password_hash=password_hash)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user
"""创建用户。

本项目没有注册接口（见 docs/API.md 非目标），账号由管理员手工创建。

用法:
    python create_user.py <用户名> <密码>
"""

import asyncio
import sys

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal, engine
from app.models.user import User


async def create(name: str, password: str) -> None:
    async with AsyncSessionLocal() as db:
        existing = await db.scalar(select(User).where(User.name == name))
        if existing is not None:
            print(f"用户已存在: {existing.name} (id={existing.id})")
            return

        user = User(name=name, password_hash=hash_password(password))
        db.add(user)
        await db.commit()
        await db.refresh(user)
        print(f"已创建用户: {user.name} (id={user.id})")


async def _run(name: str, password: str) -> None:
    try:
        await create(name, password)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    asyncio.run(_run(sys.argv[1], sys.argv[2]))

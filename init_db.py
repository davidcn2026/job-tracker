import asyncio

import app.models  # noqa: F401  导入包 → 所有模型注册到 Base.metadata
from app.db.base import Base
from app.db.session import engine


async def main() -> None:
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        print("建表完成，当前模型中的表：")
        for name in Base.metadata.tables:
            print("  -", name)
    finally:
        # 必须在同一个事件循环里 dispose，否则会报 "Event loop is closed"
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
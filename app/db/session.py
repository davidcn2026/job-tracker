from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,  # 只有 DEBUG=true 才打 SQL，否则每条查询都刷屏
    pool_size=10,  # 设置连接池活跃的连接数
    max_overflow=20,  # 允许额外的连接数
)

# 需求:查询接口的功能，查询图书 -> 依赖注入: 创建依赖项获取数据库会话 + Depends 注入路由处理函数
AsyncSessionLocal = async_sessionmaker(
    bind=engine,  # 绑定数据库引擎
    class_=AsyncSession,  # 指定会话类
    expire_on_commit=False,  # 提交后会话不过期，不会重新查询数据库
)


async def get_database() -> AsyncGenerator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        try:
            yield session  # 返回数据库会话给路由处理函数
            await session.commit()  # 提交事务
        except Exception:
            await session.rollback()  # 有异常，回滚
            raise
        finally:
            await session.close()

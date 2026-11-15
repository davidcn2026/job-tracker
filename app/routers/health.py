from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_database

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
async def health(db: AsyncSession = Depends(get_database)):
    try:
        await db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="数据库不可用") from None

    return {"status": "ok", "db": "ok"}

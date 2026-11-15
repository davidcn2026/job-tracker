from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Resp(BaseModel, Generic[T]):
    """统一响应包装：{"code": 200, "message": "success", "data": ...}"""

    code: int = 200
    message: str = "success"
    data: T | None = None

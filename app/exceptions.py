import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings

logger = logging.getLogger(__name__)

# MySQL 常见的约束错误码
ERR_DUPLICATE = 1062
ERR_NOT_NULL = 1048
ERR_FK_DELETE = 1451
ERR_FK_INSERT = 1452
ERR_DATA_TOO_LONG = 1406

STATUS_MESSAGES = {
    400: "请求参数有误",
    401: "未认证，请先登录",
    403: "没有权限",
    404: "资源不存在",
    409: "数据冲突",
    422: "参数校验失败",
    500: "服务器内部错误",
    503: "数据库暂时不可用，请稍后重试",
}


def _payload(code: int, message: str, data=None) -> dict:
    """统一响应结构，保证每个 handler 输出的形状一致。"""
    return {"code": code, "message": message, "data": data}


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """
    处理 HTTPException 异常
    """
    # HTTPException 通常是业务逻辑主动抛出的，data保持 None
    message = exc.detail or STATUS_MESSAGES.get(exc.status_code, "请求失败")

    return JSONResponse(
        status_code=exc.status_code,
        content=_payload(exc.status_code, message),
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Pydantic 校验失败（422）。字段级错误放 data，方便前端定位到具体字段。"""
    return JSONResponse(
        status_code=422,
        content=_payload(422, "参数校验失败", jsonable_encoder(exc.errors())),
    )


async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    """约束冲突兜底。

    正常情况下 router 会先捕获并翻译成更精确的 409；
    这里处理"漏网"的情况，只给通用文案，不泄露表名/约束名。
    """
    errno = int(exc.orig.args[0]) if (exc.orig and exc.orig.args) else 0

    logger.warning("完整性约束冲突 errno=%s path=%s", errno, request.url.path, exc_info=errno == 0)

    messages = {
        ERR_DUPLICATE: "记录已存在",  # 1062
        ERR_NOT_NULL: "缺少必填字段",  # 1048
        ERR_FK_DELETE: "存在关联数据，无法删除",  # 1451
        ERR_FK_INSERT: "关联的数据不存在",  # 1452
        ERR_DATA_TOO_LONG: "字段内容过长",  # 1406
    }
    return JSONResponse(status_code=409, content=_payload(409, messages.get(errno, "数据冲突")))


async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    """其他数据库错误（连接失败、SQL 语法错等）→ 503，表示"服务暂时不可用"。"""
    logger.exception("数据库错误 path=%s", request.url.path)
    message = str(exc) if settings.debug else STATUS_MESSAGES[503]
    return JSONResponse(status_code=503, content=_payload(503, message))


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """最后兜底。没有它，未捕获异常返回的是纯文本 Internal Server Error。"""
    logger.exception("未处理异常 path=%s", request.url.path)
    message = str(exc) if settings.debug else STATUS_MESSAGES[500]
    return JSONResponse(status_code=500, content=_payload(500, message))


def register_exception_handlers(app: FastAPI) -> None:
    """集中注册。由 main.py 调用——app 是传进来的，避免循环 import。"""
    # Starlette 把 handler 的形参类型声明为基类 Exception，
    # 但注册时的 key 决定了它只会收到 StarletteHTTPException 实例，运行安全。
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    app.add_exception_handler(SQLAlchemyError, sqlalchemy_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

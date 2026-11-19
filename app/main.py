from pathlib import Path

from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.exceptions import register_exception_handlers
from app.routers import health, job, user

app = FastAPI(
    title="投递记录服务",
    version="1.0.0",
    docs_url=None,  # 关掉默认 /docs（它从被墙的 jsdelivr CDN 拉资源）
    redoc_url=None,
)
register_exception_handlers(app)

app.include_router(health.router)
app.include_router(job.router)
app.include_router(user.router)

# 本地静态资源（Swagger UI 的 js/css 已下载到 static/swagger/）
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui() -> HTMLResponse:
    """用本地资源渲染 Swagger UI，不依赖外网 CDN。"""
    return get_swagger_ui_html(
        openapi_url=app.openapi_url or "/openapi.json",
        title=f"{app.title} - Swagger UI",
        swagger_js_url="/static/swagger/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger/swagger-ui.css",
    )

# python:3.13-slim 与本地开发环境对齐（都是 3.13）。
# slim 比默认 python:3.13 小约 800MB，且本项目依赖都有预编译 wheel，
# 不需要 gcc / build-essential。
FROM python:3.13-slim

# PYTHONDONTWRITEBYTECODE: 不生成 .pyc（容器里没必要，还占体积）
# PYTHONUNBUFFERED: 日志立即输出，否则 docker logs 里看不到 print / logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 先只拷依赖清单并安装。
# 这是 Docker 层缓存的关键：改代码时 requirements.txt 没变，
# 这一层就命中缓存，不会重新 pip install（否则每次改代码都要等 1 分钟）。
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 再拷应用代码（这一层变得频繁，但很快）
# static/ 必须拷：app/main.py 会挂载 /app/static 提供离线 Swagger UI，
# 目录不存在会直接 RuntimeError 启动失败。
COPY app/ ./app/
COPY static/ ./static/
COPY migrations/ ./migrations/

# 运维工具：容器里没有注册开关时，用它创建第一个账号
#   docker compose exec app python create_user.py 用户名 密码
COPY create_user.py ./

# 非 root 运行：容器被攻破时不会是 root 权限，能做的破坏有限。
# 先建用户再切换，顺序不能反。
RUN useradd --create-home --shell /bin/bash appuser
USER appuser

EXPOSE 8000

# --host 0.0.0.0 是必需的：容器内如果只监听 127.0.0.1，
# 宿主机（和 docker 的端口映射）都连不进来。
# 不用 --reload：那是开发期热重载，生产用会额外吃 CPU。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

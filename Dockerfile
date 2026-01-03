# 使用 Python 3.11 作为基础镜像
FROM python:3.11-slim as builder

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libmariadb-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --user --no-cache-dir -r requirements.txt

# 生产阶段
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 创建非root用户
RUN groupadd -r quant && useradd -r -g quant -s /bin/false quant

# 从构建阶段复制已安装的包
COPY --from=builder /root/.local /root/.local

# 复制应用代码
COPY . .

# 创建必要的目录
RUN mkdir -p /app/logs /app/data && chown -R quant:quant /app

# 设置环境变量
ENV PATH=/root/.local/bin:$PATH \
    PYTHONPATH=/app

# 切换用户
USER quant

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.path.insert(0, '/app'); from app.infrastructure.database.session import db_manager; exit(0 if db_manager.health_check() else 1)"

# 启动命令
CMD ["uvicorn", "app.web.main:app", "--host", "0.0.0.0", "--port", "8000"]
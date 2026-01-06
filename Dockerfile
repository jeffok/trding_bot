# Dockerfile
# 使用官方 Python 3.10 Slim 版本 (V8.3 推荐)
FROM python:3.10-slim

# 1. 设置时区 (V8.3 1.2 强制)
# 安装 tzdata 并设置 Asia/Hong_Kong
RUN apt-get update && apt-get install -y tzdata && \
    ln -fs /usr/share/zoneinfo/Asia/Hong_Kong /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata && \
    apt-get clean

# 2. 工作目录
WORKDIR /app

# 3. 依赖安装
# 复制依赖文件
COPY requirements.txt .
# 安装依赖 (增加 --no-cache-dir 减小体积)
RUN pip install --no-cache-dir -r requirements.txt

# 4. 复制项目代码
COPY . .

# 5. 环境变量默认值 (会被 docker-compose 覆盖)
ENV TZ=Asia/Hong_Kong
ENV PYTHONPATH=/app

# 6. 入口点 (默认启动 help，实际由 compose 指定)
CMD ["python", "--version"]
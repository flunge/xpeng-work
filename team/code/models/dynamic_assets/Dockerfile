# 使用官方 Python 3.12 镜像（推荐，稳定）
# 如果 Python 3.13.5 已正式发布，可改为 python:3.13.5 或 python:3.13-slim
FROM python:3.13.5

# 设置工作目录
WORKDIR /app

# 安装系统依赖（如 zip、curl，用于 ossutil 安装）
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        zip \
        curl \
        ca-certificates \
        zstd \
    && rm -rf /var/lib/apt/lists/*

# 安装 ossutil（根据你的命令）
RUN curl https://gosspublic.alicdn.com/ossutil/install.sh | bash

# 将 ossutil 加入 PATH（根据 install.sh 默认安装路径）
ENV PATH="/root:$PATH"

# 复制 Python 依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制你的项目代码（假设代码在当前目录）
COPY . .

# 关键：开放 /app 权限给非 root 用户
RUN chmod -R a+rwX /app

# 可选：设置默认命令（例如运行 main.py）
# CMD ["python", "main.py"]
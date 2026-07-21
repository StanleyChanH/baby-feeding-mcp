# baby-feeding-mcp —— 纯 streamable-http MCP server（连小智由 XiaozhiMCPManager 负责）
# 基础镜像靠宿主 daemon 的 registry-mirrors 加速（见 README）
FROM python:3.12-slim

# apt 换清华源（bookworm 用 DEB822 debian.sources，旧版用 sources.list，兼容两种）
RUN { sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; } \
 && { sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list 2>/dev/null || true; }

ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple \
    UV_PYTHON_PREFERENCE=only-system \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH=/app/.venv/bin:$PATH

# 装 tzdata 并设本地时区（修记录时间戳偏 8 小时）；装 uv（走清华 pip 源）
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
 && echo $TZ > /etc/timezone \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir uv

WORKDIR /app

# 先拷依赖描述，命中缓存层（改 server.py 不重装依赖）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# 再拷业务代码（纯 server，不再需要 mcp_config.json——清单归 manager）
COPY server.py ./

EXPOSE 8000

# 直接跑 streamable-http server（host/port 由 env 注入，compose 设 0.0.0.0:8000）
CMD ["python", "server.py"]

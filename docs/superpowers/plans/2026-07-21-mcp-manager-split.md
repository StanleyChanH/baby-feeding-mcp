# MCP Server / Xiaozhi Manager 拆分 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 baby-feeding-mcp 瘦身为纯 streamable-http MCP server，新建 XiaozhiMCPManager 用 mcp2xiaozhi 统一桥接多个 MCP 到小智。

**Architecture:** baby-feeding-mcp 跑 FastMCP streamable-http（`0.0.0.0:8000/mcp`），只持自己的美柚凭据；XiaozhiMCPManager 跑 mcp2xiaozhi，mcp_config.json 列出各 MCP 的 URL，连小智 wss。两者经 external docker network `mcp-net` 互通。

**Tech Stack:** Python 3.12-slim, uv, FastMCP streamable-http, mcp2xiaozhi 0.2.1, Docker Compose。

**Spec:** [docs/superpowers/specs/2026-07-21-mcp-manager-split-design.md](../specs/2026-07-21-mcp-manager-split-design.md)

## Global Constraints

- Python `requires-python = ">=3.11,<3.13"`；基础镜像固定 `python:3.12-slim`。
- **统一用 uv** 管理环境与包（`pyproject.toml` + `uv.lock`，`[tool.uv] package=false`）。
- pip/uv 走 `https://pypi.tuna.tsinghua.edu.cn/simple`；apt 走 `mirrors.tuna.tsinghua.edu.cn`；基础镜像靠宿主 daemon registry-mirrors。
- 两个 compose 都引用 external network `mcp-net`（`external: true`）。
- 各 MCP 自持凭据：baby-feeding 持 `BABY_*`/`LINGGAN_*`；manager 持 `MCP_ENDPOINT`。
- 依赖修正（spec 细化）：baby-feeding 用 `mcp>=1.0.0`（核心已含 uvicorn/starlette/sse-starlette，无需 `[cli]`），不用 mcp2xiaozhi。
- `.env` 永不进镜像层（`.dockerignore` 排除 + compose env_file 注入）。

**分支/仓库：**
- baby-feeding-mcp 工作在分支 `feat/split-server-and-manager`（已创建，spec 已提交），cwd = `/home/hajimi/Projects/baby-feeding-mcp`。
- XiaozhiMCPManager 是**新仓库**，cwd = `/home/hajimi/Projects/XiaozhiMCPManager`，Task 4 中 `git init`。

---

## File Structure

### baby-feeding-mcp（改造）

| 文件 | 职责 | 动作 |
|---|---|---|
| `server.py` | FastMCP 工具 + 启动 | 修改（构造 host/port + run transport） |
| `pyproject.toml` | 依赖（uv） | 重写（去 mcp2xiaozhi，加 mcp，v1.1.0） |
| `uv.lock` | 锁文件 | 重新生成 |
| `Dockerfile` | 镜像 | 修改（CMD python server.py，EXPOSE 8000） |
| `docker-compose.yml` | 编排 | 重写（mcp-net，expose，去 volume） |
| `.env.example` | env 模板 | 修改（去 MCP_ENDPOINT，加 HOST/PORT） |
| `README.md` | 文档 | 重写 |
| `mcp_config.json` | 旧桥接配置 | 删除 |

### XiaozhiMCPManager（新建）

| 文件 | 职责 |
|---|---|
| `pyproject.toml` | 依赖（仅 mcp2xiaozhi） |
| `uv.lock` | 锁文件 |
| `Dockerfile` | 镜像（mcp2xiaozhi + 国内源） |
| `docker-compose.yml` | 编排（mcp-net，挂载 mcp_config.json） |
| `mcp_config.json` | MCP URL 清单 |
| `.env.example` | MCP_ENDPOINT/TZ/LOG_LEVEL |
| `.dockerignore` / `.gitignore` | 排除规则 |
| `README.md` | 上手 + 如何加 MCP |

---

## Task 1: baby-feeding-mcp 改为 streamable-http server（代码 + 依赖）

**Working dir:** `/home/hajimi/Projects/baby-feeding-mcp`（分支 `feat/split-server-and-manager`）

**Files:**
- Modify: `server.py`（FastMCP 构造 + `__main__` 启动块）
- Rewrite: `pyproject.toml`
- Regenerate: `uv.lock`

**Interfaces:**
- Produces: `server.py` 以 `mcp.run(transport="streamable-http")` 启动，监听 `0.0.0.0:8000/mcp`（host/port 由 env `HOST`/`PORT` 控制）。

- [ ] **Step 1: 改 `server.py` 的 FastMCP 构造，注入 host/port**

把（`load_dotenv()` 与 `CN_TZ`/`REQUEST_TIMEOUT` 定义之后、`def _age_components` 之前）这一段：

```python
# 创建 MCP 服务器
mcp = FastMCP("BabyFeedingRecord")
```

替换为：

```python
# 创建 MCP 服务器
# host/port 是 FastMCP 构造参数（不是 run() 参数），存入 settings 供 streamable-http 使用。
# 默认 host=127.0.0.1 在容器内不可达，必须显式 0.0.0.0。
mcp = FastMCP(
    "BabyFeedingRecord",
    host=os.getenv("HOST", "0.0.0.0"),
    port=int(os.getenv("PORT", "8000")),
)
```

- [ ] **Step 2: 改 `server.py` 的启动块，传输改 streamable-http**

把文件末尾：

```python
# 启动服务器
if __name__ == "__main__":
    validate_config()
    mcp.run(transport="stdio")
```

替换为：

```python
# 启动服务器（streamable-http，默认 0.0.0.0:8000/mcp）
if __name__ == "__main__":
    validate_config()
    logger.info(f"启动 streamable-http server: {os.getenv('HOST', '0.0.0.0')}:{os.getenv('PORT', '8000')}/mcp")
    mcp.run(transport="streamable-http")
```

- [ ] **Step 3: 重写 `pyproject.toml`（去 mcp2xiaozhi，加 mcp）**

把整个 `pyproject.toml` 替换为：

```toml
[project]
name = "baby-feeding-mcp"
version = "1.1.0"
description = "宝宝抚养记录 MCP Server（纯 streamable-http 服务，不连小智）"
readme = "README.md"
requires-python = ">=3.11,<3.13"
dependencies = [
    "mcp>=1.0.0",
    "requests>=2.28.0",
    "python-dotenv>=1.0.0",
]

[tool.uv]
package = false
```

（`mcp` 核心已含 uvicorn/starlette/sse-starlette，无需 `[cli]`；移除 mcp2xiaozhi——桥接归 manager。）

- [ ] **Step 4: 重新生成 `uv.lock`**

Run:
```bash
cd /home/hajimi/Projects/baby-feeding-mcp
rm -rf .venv
uv lock
```
Expected: 输出 `Resolved N packages`，含 `mcp`、`uvicorn`、`starlette`、`sse-starlette`、`requests`、`python-dotenv`；**不再含** `mcp2xiaozhi`。

- [ ] **Step 5: 本地装依赖并验证 import + 构造**

Run:
```bash
uv sync --no-dev
.venv/bin/python -c "import server; print('host=', server.mcp.settings.host, 'port=', server.mcp.settings.port)"
```
Expected: 第一行成功；第二行打印 `host= 0.0.0.0 port= 8000`（env 未设时用默认）。若 `mcp.settings` 取不到 host/port，改用 `.venv/bin/python -c "import server; print('IMPORT_OK')"` 至少确认 import 无 ImportError（说明 starlette/uvicorn 装好了）。

- [ ] **Step 6: 本地冒烟——启动 server 并打一次 initialize**

Run（后台起 server，5s 后用 httpx 打 initialize，再关 server）:
```bash
cd /home/hajimi/Projects/baby-feeding-mcp
HOST=127.0.0.1 PORT=8765 BABY_TOKEN=t BABY_ID=1 COMMON_BABY_ID=2 BABY_BIRTHDAY=2025-01-01 .venv/bin/python server.py & 
SERVER_PID=$!
sleep 5
.venv/bin/python -c "
import httpx
r = httpx.post('http://127.0.0.1:8765/mcp', headers={'Accept':'application/json, text/event-stream','Content-Type':'application/json','MCP-Protocol-Version':'2025-06-18'}, json={'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'t','version':'1'}}}, timeout=10)
print('STATUS', r.status_code); print('BODY', r.text[:200])
"
kill $SERVER_PID 2>/dev/null
```
Expected: `STATUS 200`，BODY 含 `"result"` 与 `"serverInfo"`（或 `"BabyFeedingRecord"`）。若 STATUS 非 200，检查 host/port 是否生效、streamable-http 依赖是否齐全。

- [ ] **Step 7: 提交**

```bash
git add server.py pyproject.toml uv.lock
git commit -m "$(cat <<'EOF'
refactor(server): switch to pure streamable-http server, drop mcp2xiaozhi

- FastMCP constructed with host/port from env (HOST/PORT, default
  0.0.0.0:8000); run(transport="streamable-http"). Default path /mcp.
- pyproject: replace mcp2xiaozhi with mcp>=1.0.0 (core already bundles
  uvicorn/starlette/sse-starlette; no [cli] needed); bump to 1.1.0
  (breaking: stdio bridge -> standalone HTTP MCP server).
- Regenerate uv.lock.

The xiaozhi connection moves to the new XiaozhiMCPManager repo.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: baby-feeding-mcp 容器化为纯 server

**Working dir:** `/home/hajimi/Projects/baby-feeding-mcp`

**Files:**
- Modify: `Dockerfile`
- Rewrite: `docker-compose.yml`
- Delete: `mcp_config.json`
- Modify: `.env.example`

- [ ] **Step 1: 改 `Dockerfile`（CMD + EXPOSE，去掉 mcp_config.json 的 COPY）**

把 `Dockerfile` 中这一段：

```dockerfile
# 再拷业务代码
COPY server.py mcp_config.json ./

# mcp2xiaozhi 作桥接，按 mcp_config.json 拉起所有启用的 server
CMD ["mcp2xiaozhi", "run", "--all"]
```

替换为：

```dockerfile
# 再拷业务代码（纯 server，不再需要 mcp_config.json——清单归 manager）
COPY server.py ./

EXPOSE 8000

# 直接跑 streamable-http server（host/port 由 env 注入，compose 设 0.0.0.0:8000）
CMD ["python", "server.py"]
```

并把文件首行注释：

```dockerfile
# baby-feeding-mcp —— 由 mcp2xiaozhi 桥接 server.py 到小智AI
```

改为：

```dockerfile
# baby-feeding-mcp —— 纯 streamable-http MCP server（连小智由 XiaozhiMCPManager 负责）
```

- [ ] **Step 2: 重写 `docker-compose.yml`（mcp-net，expose，去 volume）**

把整个 `docker-compose.yml` 替换为：

```yaml
# baby-feeding-mcp —— 纯 MCP server
# 1. docker network create mcp-net（若没有）
# 2. cp .env.example .env 填 BABY_* / LINGGAN_*（本服务不需要 MCP_ENDPOINT）
# 3. docker compose up -d --build
# 连小智请部署 XiaozhiMCPManager，其 mcp_config.json 指向 http://baby-feeding-mcp:8000/mcp
services:
  baby-feeding-mcp:
    build: .
    image: baby-feeding-mcp:latest
    container_name: baby-feeding-mcp      # manager 靠此容器名寻址
    restart: unless-stopped
    init: true
    env_file: .env
    environment:
      TZ: Asia/Shanghai
      HOST: "0.0.0.0"
      PORT: "8000"
    expose:
      - "8000"                            # 仅 mcp-net 内可达，不映射宿主
    # 本地调试可临时打开：ports: ["127.0.0.1:8000:8000"]
    networks:
      - mcp-net
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

networks:
  mcp-net:
    external: true
```

- [ ] **Step 3: 删除 `mcp_config.json`**

Run:
```bash
cd /home/hajimi/Projects/baby-feeding-mcp
git rm mcp_config.json
```
Expected: 标记 deleted。

- [ ] **Step 4: 改 `.env.example`（去 MCP_ENDPOINT，加 HOST/PORT）**

把整个 `.env.example` 替换为：

```env
# baby-feeding-mcp 自持的凭据（调美柚 API 用）
# 小智连接（MCP_ENDPOINT）已移到 XiaozhiMCPManager 的 .env
BABY_TOKEN="XDS your_token_here"
BABY_ID=123456789
COMMON_BABY_ID=987654321
BABY_BIRTHDAY=2025-08-20
BABY_GENDER=1

# 每日变化建议 API（美柚 linggan），可留空
LINGGAN_ACCESS_TOKEN=
LINGGAN_ACCESS_INFO=

# streamable-http server 监听
HOST=0.0.0.0
PORT=8000

# 时区与日志
TZ=Asia/Shanghai
LOG_LEVEL=INFO
```

- [ ] **Step 5: 建网络 + 构建镜像**

Run:
```bash
cd /home/hajimi/Projects/baby-feeding-mcp
docker network create mcp-net 2>/dev/null || true
docker compose build 2>&1 | tr '\r' '\n' | grep -iE 'ERROR|naming to|Successfully' | tail -5
```
Expected: 末尾 `naming to docker.io/library/baby-feeding-mcp:latest done`，无 ERROR。（基础镜像本机已缓存，构建应较快。）

- [ ] **Step 6: 起容器并验证 HTTP 端点（容器内 httpx 打自己的 8000）**

Run:
```bash
cd /home/hajimi/Projects/baby-feeding-mcp
# 先准备最小 .env（若用户已有 .env 可跳过；此处仅用于冒烟）
[ -f .env ] || cp .env.example .env
docker compose up -d 2>&1 | tail -2
sleep 6
docker exec baby-feeding-mcp python -c "
import httpx, os
r = httpx.post('http://127.0.0.1:8000/mcp', headers={'Accept':'application/json, text/event-stream','Content-Type':'application/json'}, json={'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'t','version':'1'}}}, timeout=10)
print('STATUS', r.status_code); print('BODY', r.text[:160])
"
```
Expected: 容器 `Started`；`STATUS 200`，BODY 含 `"result"`/`"serverInfo"`。若 STATUS 非 200，看 `docker compose logs` 排查（常见：env 缺失 validate_config 崩、或 host/port 未生效）。

- [ ] **Step 7: 提交**

```bash
git add Dockerfile docker-compose.yml .env.example
git commit -m "$(cat <<'EOF'
feat(docker): run as standalone MCP server on external mcp-net

- Dockerfile: CMD python server.py (was mcp2xiaozhi), EXPOSE 8000,
  stop copying mcp_config.json.
- compose: join external mcp-net, expose 8000 (no host port), set
  HOST=0.0.0.0/PORT=8000, drop mcp_config.json volume mount.
- .env.example: drop MCP_ENDPOINT (moved to manager), add HOST/PORT.
- Delete mcp_config.json (roster now lives in XiaozhiMCPManager).

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: baby-feeding-mcp README 重写

**Working dir:** `/home/hajimi/Projects/baby-feeding-mcp`

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 重写「快速开始」+「本地开发」+ 目录结构段**

把 `README.md` 中「## 快速开始（Docker Compose，推荐）」整段（从该标题到「## 工具参数详解」之前，含配置项说明表、本地开发、国内镜像加速）替换为：

````markdown
## 这是什么

宝宝抚养记录的 **MCP server**（FastMCP streamable-http）。它只负责暴露 MCP 工具、调美柚 API 记录数据，**不连接小智**。要接入小智AI，请部署 [XiaozhiMCPManager](../XiaozhiMCPManager)，在它的 `mcp_config.json` 里指向本服务。

## 快速开始（Docker Compose）

```bash
# 一次性建共享网络（manager 与各 MCP 都用它）
docker network create mcp-net

cp .env.example .env   # 填 BABY_TOKEN / BABY_ID 等
docker compose up -d --build
```

服务在 `mcp-net` 内以 `http://baby-feeding-mcp:8000/mcp` 提供 streamable-http MCP 接口（不暴露宿主端口）。

### 配置项

| 变量 | 说明 |
|------|------|
| `BABY_TOKEN` | 美柚API授权Token（含空格务必加引号） |
| `BABY_ID` / `COMMON_BABY_ID` | 宝宝ID / 通用宝宝ID |
| `BABY_BIRTHDAY` | 宝宝生日 YYYY-MM-DD |
| `BABY_GENDER` | 0=女孩，1=男孩（默认） |
| `LINGGAN_ACCESS_TOKEN` / `LINGGAN_ACCESS_INFO` | 每日变化建议API凭据（可留空） |
| `HOST` / `PORT` | streamable-http 监听，默认 `0.0.0.0:8000` |
| `TZ` / `LOG_LEVEL` | 时区 / 日志级别 |

## 本地开发（uv）

```bash
uv sync
uv run python server.py                 # 启动 streamable-http，127.0.0.1:8000/mcp
```

用 MCP Inspector 或任意 streamable-http 客户端连 `http://localhost:8000/mcp` 调试工具。

## 国内镜像加速

构建时 pip/apt 已指向清华源；基础镜像建议在 `/etc/docker/daemon.json` 配 `registry-mirrors`（详见 XiaozhiMCPManager README）。
````

- [ ] **Step 2: 更新「目录结构」段（去掉 mcp_config.json）**

把 `README.md` 的目录结构块替换为：

```markdown
## 目录结构

```
baby-feeding-mcp/
├── server.py            # MCP Server 主程序（FastMCP 工具，streamable-http）
├── Dockerfile           # 镜像（uv + 国内源）
├── docker-compose.yml   # 编排（external mcp-net）
├── .dockerignore
├── .env.example         # 环境变量模板（不含 MCP_ENDPOINT）
├── .env                 # 环境变量（自行创建，不提交）
├── pyproject.toml       # 依赖（uv）
├── uv.lock
└── README.md
```
```

- [ ] **Step 3: 提交**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs(readme): reposition as standalone MCP server (no xiaozhi)

Point users to XiaozhiMCPManager for xiaozhi connectivity; document
mcp-net + http://baby-feeding-mcp:8000/mcp endpoint, uv local dev,
and updated directory structure (no mcp_config.json).

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: 新建 XiaozhiMCPManager 仓库骨架

**Working dir:** `/home/hajimi/Projects/XiaozhiMCPManager`（**新目录**，先 `mkdir`）

**Files:**
- Create: `pyproject.toml`, `uv.lock`, `.gitignore`, `.dockerignore`

- [ ] **Step 1: 建目录并 `git init`**

Run:
```bash
mkdir -p /home/hajimi/Projects/XiaozhiMCPManager
cd /home/hajimi/Projects/XiaozhiMCPManager
git init -b main 2>&1 | tail -1
```
Expected: `Initialized empty Git repository ...`（默认分支 main）。

- [ ] **Step 2: 创建 `pyproject.toml`**

新建 `/home/hajimi/Projects/XiaozhiMCPManager/pyproject.toml`：

```toml
[project]
name = "xiaozhi-mcp-manager"
version = "0.1.0"
description = "统一桥接多个 MCP server 到小智AI（mcp2xiaozhi 容器化）"
requires-python = ">=3.11,<3.13"
dependencies = [
    "mcp2xiaozhi>=0.2.1",
]

[tool.uv]
package = false
```

- [ ] **Step 3: 生成 `uv.lock`**

Run:
```bash
cd /home/hajimi/Projects/XiaozhiMCPManager
uv lock 2>&1 | tail -3
```
Expected: `Resolved N packages`，含 `mcp2xiaozhi` 及其传递依赖（`mcp`、`websockets`、`httpx` 等）。

- [ ] **Step 4: 创建 `.gitignore`**

新建 `/home/hajimi/Projects/XiaozhiMCPManager/.gitignore`：

```
# Python
__pycache__/
*.py[cod]
.venv/
venv/

# 敏感配置
.env

# IDE / Claude
.vscode/
.idea/
.claude/
CLAUDE.md

# OS
.DS_Store
```

- [ ] **Step 5: 创建 `.dockerignore`**

新建 `/home/hajimi/Projects/XiaozhiMCPManager/.dockerignore`：

```
.env
.env.*
.git/
.venv/
venv/
__pycache__/
*.pyc
.claude/
CLAUDE.md
docs/
```

- [ ] **Step 6: 首次提交**

```bash
cd /home/hajimi/Projects/XiaozhiMCPManager
git add pyproject.toml uv.lock .gitignore .dockerignore
git commit -m "$(cat <<'EOF'
chore: scaffold XiaozhiMCPManager (mcp2xiaozhi + uv)

Empty manager skeleton: pyproject pins mcp2xiaozhi>=0.2.1 (uv-managed,
package=false), uv.lock generated, .gitignore/.dockerignore exclude
.env/.venv.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: XiaozhiMCPManager Docker + 清单 + env

**Working dir:** `/home/hajimi/Projects/XiaozhiMCPManager`

**Files:**
- Create: `Dockerfile`, `docker-compose.yml`, `mcp_config.json`, `.env.example`

- [ ] **Step 1: 创建 `Dockerfile`**

新建 `/home/hajimi/Projects/XiaozhiMCPManager/Dockerfile`：

```dockerfile
# XiaozhiMCPManager —— mcp2xiaozhi 桥接多个 MCP 到小智AI
# 基础镜像靠宿主 daemon 的 registry-mirrors 加速
FROM python:3.12-slim

# apt 换清华源
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

RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
 && echo $TZ > /etc/timezone \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY mcp_config.json ./

CMD ["mcp2xiaozhi", "run", "--all"]
```

- [ ] **Step 2: 创建 `docker-compose.yml`**

新建 `/home/hajimi/Projects/XiaozhiMCPManager/docker-compose.yml`：

```yaml
# XiaozhiMCPManager —— 统一桥接多个 MCP 到小智AI
# 1. docker network create mcp-net（与各 MCP 共用）
# 2. cp .env.example .env 填 MCP_ENDPOINT（小智 wss）
# 3. docker compose up -d --build
services:
  xiaozhi-mcp-manager:
    build: .
    image: xiaozhi-mcp-manager:latest
    container_name: xiaozhi-mcp-manager
    restart: unless-stopped
    init: true                # tini PID1，转发信号
    env_file: .env
    environment:
      TZ: Asia/Shanghai
    volumes:
      - ./mcp_config.json:/app/mcp_config.json:ro   # 改清单免重建
    networks:
      - mcp-net
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

networks:
  mcp-net:
    external: true
```

- [ ] **Step 3: 创建 `mcp_config.json`（MCP 清单）**

新建 `/home/hajimi/Projects/XiaozhiMCPManager/mcp_config.json`：

```json
{
  "mcpServers": {
    "baby-feeding": {
      "type": "streamablehttp",
      "url": "http://baby-feeding-mcp:8000/mcp"
    }
  }
}
```

（新增 MCP：在此加条目，`type` 可为 `streamablehttp`/`sse`/`stdio`，并确保该 MCP 容器加入 `mcp-net`。）

- [ ] **Step 4: 创建 `.env.example`**

新建 `/home/hajimi/Projects/XiaozhiMCPManager/.env.example`：

```env
# 小智AI MCP接入点（从小智控制台获取）
MCP_ENDPOINT=wss://api.xiaozhi.me/mcp/?token=YOUR_TOKEN_HERE

# 时区与日志
TZ=Asia/Shanghai
LOG_LEVEL=INFO
```

- [ ] **Step 5: 构建镜像验证**

Run:
```bash
cd /home/hajimi/Projects/XiaozhiMCPManager
docker compose build 2>&1 | tr '\r' '\n' | grep -iE 'ERROR|naming to|Successfully' | tail -5
docker compose run --rm --no-deps xiaozhi-mcp-manager sh -c 'which mcp2xiaozhi && mcp2xiaozhi version'
```
Expected: 构建出现 `naming to docker.io/library/xiaozhi-mcp-manager:latest done`；`which` 为 `/app/.venv/bin/mcp2xiaozhi`，版本 `0.2.1`（或更高）。

- [ ] **Step 6: 提交**

```bash
cd /home/hajimi/Projects/XiaozhiMCPManager
git add Dockerfile docker-compose.yml mcp_config.json .env.example
git commit -m "$(cat <<'EOF'
feat(docker): mcp2xiaozhi bridge with MCP roster, 国内镜像源

- Dockerfile: python:3.12-slim, apt+pip 清华源, tzdata, uv sync --frozen,
  CMD mcp2xiaozhi run --all.
- compose: init:true, env_file, mcp_config.json ro mount, external mcp-net.
- mcp_config.json: baby-feeding via streamablehttp on mcp-net.
- .env.example: MCP_ENDPOINT + TZ + LOG_LEVEL.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: XiaozhiMCPManager README

**Working dir:** `/home/hajimi/Projects/XiaozhiMCPManager`

**Files:**
- Create: `README.md`

- [ ] **Step 1: 创建 `README.md`**

新建 `/home/hajimi/Projects/XiaozhiMCPManager/README.md`：

````markdown
# XiaozhiMCPManager

统一桥接**多个 MCP server** 到小智AI 的部署。内部跑 [`mcp2xiaozhi`](https://github.com/StanleyChanH/MCP2Xiaozhi)，按 `mcp_config.json` 清单把每个 MCP 经 streamable-http 接入，统一连小智 wss。

## 架构

```
小智AI ◄wss► XiaozhiMCPManager (mcp2xiaozhi)
                  │ mcp-net (external docker network)
                  ├──► baby-feeding-mcp  http://baby-feeding-mcp:8000/mcp
                  └──► <其它 MCP>        http://<name>:<port>/mcp
```

各 MCP server 是独立项目、独立部署、自持凭据；本管理器只持 `MCP_ENDPOINT`（小智 wss）+ MCP URL 清单。

## 上手

1. 建共享网络（一次性，与各 MCP 共用）：

```bash
docker network create mcp-net
```

2. 配置：

```bash
cp .env.example .env
# 编辑 .env，填 MCP_ENDPOINT（小智 wss）
# 编辑 mcp_config.json，列出要接入的 MCP（默认已含 baby-feeding）
```

3. 启动：

```bash
docker compose up -d --build
docker compose logs -f
```

> 各 MCP server 须**先于**或同时启动（本管理器对 wss 与每个 HTTP MCP 都有断线重连，顺序不强制但建议先起 MCP）。

## 如何加一个新 MCP

1. 该 MCP 作为 streamable-http server 跑起来，并让其容器加入 `mcp-net`（在其 compose 里 `networks: [mcp-net]` + `external: true`）。
2. 在本仓库 `mcp_config.json` 加一条：

```json
"你的-mcp": { "type": "streamablehttp", "url": "http://<容器名>:<端口>/mcp" }
```

3. `docker compose restart xiaozhi-mcp-manager`（改清单免重建镜像，因为是挂载的）。

## 配置项

| 变量 | 说明 |
|------|------|
| `MCP_ENDPOINT` | 小智AI 的 MCP WebSocket 接入点 |
| `TZ` / `LOG_LEVEL` | 时区 / 日志级别 |

## 国内镜像加速

Dockerfile 内 pip/apt 已指向清华源。基础镜像建议在 `/etc/docker/daemon.json` 配 `registry-mirrors`：

```json
{ "registry-mirrors": ["https://docker.mirrors.ustc.edu.cn", "https://hub-mirror.c.163.com"] }
```

配置后 `sudo systemctl restart docker`。

## 目录结构

```
XiaozhiMCPManager/
├── mcp_config.json      # MCP URL 清单
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── pyproject.toml       # mcp2xiaozhi 依赖（uv）
├── uv.lock
└── README.md
```
````

- [ ] **Step 2: 提交**

```bash
cd /home/hajimi/Projects/XiaozhiMCPManager
git add README.md
git commit -m "$(cat <<'EOF'
docs: XiaozhiMCPManager README (setup, add-an-MCP, mirrors)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: 端到端集成验证

**Working dirs:** 两个仓库。**无代码提交**（仅本地 `.env` + 验证；`.env` 不提交）。

**Interfaces:**
- 消费：Task 1-3 的 baby-feeding-mcp（HTTP server）+ Task 4-6 的 XiaozhiMCPManager（bridge）。
- 需要用户的真实凭据：`MCP_ENDPOINT`（小智 wss token）、`BABY_TOKEN`/`BABY_ID`/`COMMON_BABY_ID`/`BABY_BIRTHDAY`/`LINGGAN_*`。

- [ ] **Step 1: 准备 baby-feeding-mcp 的本地 `.env`（移除 MCP_ENDPOINT）**

Run:
```bash
cd /home/hajimi/Projects/baby-feeding-mcp
# 若 .env 已存在且含 MCP_ENDPOINT，删掉那行（小智连接归 manager）
```
手动确保 `.env` 含 `BABY_TOKEN`（带引号）/`BABY_ID`/`COMMON_BABY_ID`/`BABY_BIRTHDAY`/`BABY_GENDER`/`LINGGAN_*`，**不含** `MCP_ENDPOINT`。确认未被追踪：
```bash
git -C /home/hajimi/Projects/baby-feeding-mcp check-ignore .env && echo "(.env ignored)"
```
Expected: 打印 `.env` + `(ignored)`。

- [ ] **Step 2: 准备 XiaozhiMCPManager 的本地 `.env`（MCP_ENDPOINT 在此）**

Run:
```bash
cd /home/hajimi/Projects/XiaozhiMCPManager
cp .env.example .env
```
手动把 `.env` 的 `MCP_ENDPOINT` 改为真实小智 wss（从 baby-feeding 旧 .env 迁过来的 token）。确认忽略：
```bash
git check-ignore .env && echo "(.env ignored)"
```

- [ ] **Step 3: 起 baby-feeding-mcp**

Run:
```bash
cd /home/hajimi/Projects/baby-feeding-mcp
docker network create mcp-net 2>/dev/null || true
docker compose up -d 2>&1 | tail -2
sleep 6
docker compose ps --format '{{.Name}} {{.Status}}'
```
Expected: `baby-feeding-mcp Up`。

- [ ] **Step 4: 起 XiaozhiMCPManager，看是否桥接成功**

Run:
```bash
cd /home/hajimi/Projects/XiaozhiMCPManager
docker compose up -d 2>&1 | tail -2
sleep 8
docker compose logs --tail=30 xiaozhi-mcp-manager 2>&1 | sed -E 's/token=[^ ]+/token=<redacted>/' | grep -iE 'registered|connected|baby-feeding|streamable|error|traceback|ListTools' | tail -12
```
Expected: 日志出现 `Registered server 'baby-feeding' (streamablehttp)`、`WebSocket connected`（连上小智）、`Processing request of type ListToolsRequest`；**无** `缺少环境变量`/连接 `baby-feeding-mcp` 失败的 error。（ListToolsRequest 由小智发起，证明整条链路通：小智 → manager → baby-feeding → 返回 9 个工具。）

- [ ] **Step 5: 信号/退出验证（两边）**

Run:
```bash
cd /home/hajimi/Projects/XiaozhiMCPManager && time docker compose stop 2>&1 | tail -2
cd /home/hajimi/Projects/baby-feeding-mcp && time docker compose stop 2>&1 | tail -2
docker inspect baby-feeding-mcp --format 'baby exit={{.State.ExitCode}}' 2>/dev/null
docker inspect xiaozhi-mcp-manager --format 'mgr exit={{.State.ExitCode}}' 2>/dev/null
```
Expected: 两个 stop 都在数秒内完成；exit code 均为 `0`。

- [ ] **Step 6: （可选）重新拉起留作用户小智实测**

Run:
```bash
cd /home/hajimi/Projects/baby-feeding-mcp && docker compose up -d 2>&1 | tail -1
cd /home/hajimi/Projects/XiaozhiMCPManager && docker compose up -d 2>&1 | tail -1
```
然后由用户对小智说「记录喝奶 180 毫升」「宝宝多大」「最近一次喝奶」，确认美柚侧记录 + 本地时间戳。

（本任务无 git 提交。）

---

## Self-Review（已执行）

**1. Spec 覆盖：**
- §3 架构（streamable-http + mcp-net）→ Task 1（server transport）+ Task 2（compose 网络）+ Task 5（manager 网络/清单）✓
- §4 baby-feeding 改动：server.py(Task1)✓ pyproject(Task1)✓ Dockerfile(Task2)✓ compose(Task2)✓ 删 mcp_config.json(Task2)✓ .env.example(Task2)✓ README(Task3)✓ uv.lock(Task1)✓
- §5 manager 新仓库：全部文件(Task4 骨架 + Task5 docker + Task6 README)✓
- §6 数据流 → Task 7 验证（ListToolsRequest）✓
- §7 验证计划 → Task 2 Step6（HTTP 端点）+ Task 5 Step5（manager 构建）+ Task 7（端到端）✓
- §8 迁移注意 → Task 7 Step1/2（MCP_ENDPOINT 迁移）✓
- 统一 uv（Global Constraints + 各 Task 用 uv lock/uv sync）✓
- 国内镜像源（Task2/Task5 Dockerfile）✓

**2. 占位符扫描：** 无 TBD/TODO；每步含完整代码或确切命令 + 预期输出。

**3. 类型/命名一致性：** `HOST`/`PORT` 在 Task1（server.py 读取 + pyproject 间接）→ Task2（compose 注入 + .env.example 声明）一致；`mcp-net` 在 Task2/Task5/Task7 一致；`container_name: baby-feeding-mcp` 与 Task5 mcp_config 的 URL `http://baby-feeding-mcp:8000/mcp` 一致；manager 服务名 `xiaozhi-mcp-manager` 在 Task5/Task6/Task7 一致。

**spec 细化（已并入）：** §4.2 写 `mcp[cli]>=1.0.0`；核查 mcp 包 METADATA 发现 uvicorn/starlette/sse-starlette 是**核心**依赖，故 Task1 改用更精简的 `mcp>=1.0.0`（无需 `[cli]`），已在 Task1 Step3 注明。

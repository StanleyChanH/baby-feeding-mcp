# Design: 拆分 MCP Server 与 Xiaozhi 连接管理器

- 日期: 2026-07-21
- 状态: 已批准（待 spec 复核）
- 范围: 两个仓库
  - `~/Projects/baby-feeding-mcp`（现有，改造）
  - `~/Projects/XiaozhiMCPManager`（新建）

## 1. 背景与目标

当前 baby-feeding-mcp 既是一个 FastMCP 工具服务，又内嵌 mcp2xiaozhi 桥接、直连小智AI。要把「MCP server」与「连接小智」两件事拆开：

- **baby-feeding-mcp** 瘦身为**纯 MCP server**（FastMCP streamable-http），不再连小智。
- **XiaozhiMCPManager**（新仓库）用 mcp2xiaozhi 统一管理**多个** MCP server，把它们都桥接到小智。

目标：baby-feeding 是「N 个 MCP 之一」，manager 是「统一入口」。以后新增 MCP 只改 manager 的清单，不动各 MCP 仓库。

## 2. 关键决策（已与用户确认）

1. **传输方式**：`streamable-http`。mcp2xiaozhi 的 `streamable_http` transport 用 `mcp.client.streamable_http.streamable_http_client` 直连远端 MCP（无需 mcp-proxy）；FastMCP 原生支持 streamable-http server，默认路径 `/mcp`。
2. **网络模型**：共享 **external docker network `mcp-net`**。两个 compose 都以 `external: true` 引用。manager 用容器名 DNS（如 `http://baby-feeding-mcp:8000/mcp`）访问各 MCP，不暴露宿主端口。一次性 `docker network create mcp-net`。
3. **配置/凭据归属**：各 MCP 自持自己的 `.env`（baby-feeding 自己持 `BABY_TOKEN` 等调美柚 API 的凭据）。manager 只持 `MCP_ENDPOINT`（小智 wss）+ MCP URL 清单。
4. **环境与包管理**：两个仓库**统一用 uv**（`pyproject.toml` + `uv.lock`，`[tool.uv] package=false`）。
5. **国内镜像源**：两个 Dockerfile 都配清华 pip/apt 源；基础镜像靠宿主 daemon 的 registry-mirrors。
6. **HTTP 端点认证**：私有 docker 网络内，暂不加 token；manager 的 `mcp_config.json` 预留 `headers` 字段位，日后需要可加。

**已否决方案**：让 manager 用 stdio 方式 spawn 各 MCP——要求 manager 容器内装有每个 MCP 的代码/运行时，破坏独立项目边界。HTTP 方式让每个 MCP 独立部署、manager 只认 URL，胜出。

## 3. 架构

```
                ┌──────────────── XiaozhiMCPManager (新, docker compose) ────────────────┐
   小智AI ◄wss► │  mcp2xiaozhi run --all                                                   │
                │  mcp_config.json:                                                        │
                │    baby-feeding → http://baby-feeding-mcp:8000/mcp  (streamablehttp)    │
                │    <其它 MCP>    → http://<name>:<port>/mcp             (streamablehttp)    │
                │  .env: MCP_ENDPOINT                                                       │
                └───────────────────────────┬─────────────────────────────────────────────┘
                                             │ external network: mcp-net
   ┌─────────────────────────────────────────┴───────────────────────────────────────────┐
   │ baby-feeding-mcp (现仓库, docker compose) ── 纯 MCP server                          │
   │   FastMCP streamable-http, 0.0.0.0:8000/mcp                                        │
   │   .env: BABY_TOKEN/BABY_ID/COMMON_BABY_ID/BABY_BIRTHDAY/BABY_GENDER/LINGGAN_*      │
   └──────────────────────────────────────────────────────────────────────────────────────┘
```

关键实现细节（spec-critical）：
- **FastMCP 的 `host`/`port` 是构造参数，不是 `run()` 参数**。`run(transport="streamable-http")` 只接受 `transport`/`mount_path`。host/port 在 `FastMCP("name", host=, port=)` 构造时传入，存入 settings，由 `run_streamable_http_async` 使用。FastMCP 默认 host=`127.0.0.1`（容器内不可达），**必须显式传 `host="0.0.0.0"`**。
- 默认 streamable-http 路径 `/mcp`（`streamable_http_path` 构造参数，不改）。

## 4. baby-feeding-mcp 改动

### 4.1 server.py（最小改动）

仅改两处，工具代码与全部 bug 修复**原样保留**：

1. FastMCP 构造（顶部，`load_dotenv()` 之后）：
   ```python
   mcp = FastMCP(
       "BabyFeedingRecord",
       host=os.getenv("HOST", "0.0.0.0"),
       port=int(os.getenv("PORT", "8000")),
   )
   ```
2. 启动块：
   ```python
   if __name__ == "__main__":
       validate_config()
       mcp.run(transport="streamable-http")
   ```
   （从 `mcp.run(transport="stdio")` 改为 `streamable-http`。`validate_config()` 保留——env 缺失时 fail fast，容器 restart 循环可见。）

### 4.2 pyproject.toml

```toml
[project]
name = "baby-feeding-mcp"
version = "1.1.0"   # breaking: stdio 桥接 → 纯 HTTP server
description = "宝宝抚养记录 MCP Server"
readme = "README.md"
requires-python = ">=3.11,<3.13"
dependencies = [
    "mcp[cli]>=1.0.0",
    "requests>=2.28.0",
    "python-dotenv>=1.0.0",
]

[tool.uv]
package = false
```

依赖变化：移除 `mcp2xiaozhi>=0.2.1`，加回 `mcp[cli]>=1.0.0`（提供 FastMCP + streamable-http server 所需的 uvicorn/starlette/sse-starlette）。`requests`/`python-dotenv` 不变。

### 4.3 Dockerfile

基础结构不变（python:3.12-slim + 清华 apt/pip 源 + tzdata + uv + `UV_DEFAULT_INDEX=清华` + `PATH=/app/.venv/bin`）。改动：
- `COPY server.py`（**不再** COPY `mcp_config.json`）。
- `EXPOSE 8000`。
- `CMD ["python", "server.py"]`（替代 `mcp2xiaozhi run --all`）。

### 4.4 docker-compose.yml

```yaml
services:
  baby-feeding-mcp:
    build: .
    image: baby-feeding-mcp:latest
    container_name: baby-feeding-mcp      # manager 靠此名寻址
    restart: unless-stopped
    init: true
    env_file: .env
    environment:
      TZ: Asia/Shanghai
      HOST: "0.0.0.0"
      PORT: "8000"
    expose:
      - "8000"                            # 仅 mcp-net 内可达，不映射宿主
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

去掉旧的 `volumes: mcp_config.json`。注释提示本地调试可临时加 `ports: ["127.0.0.1:8000:8000"]`。

### 4.5 删除

- `mcp_config.json`（桥接配置归 manager）。

### 4.6 .env.example

移除 `MCP_ENDPOINT`（归 manager）。新增 `HOST`/`PORT`。保留 `BABY_TOKEN`（带引号）/`BABY_ID`/`COMMON_BABY_ID`/`BABY_BIRTHDAY`/`BABY_GENDER`/`LINGGAN_ACCESS_TOKEN`/`LINGGAN_ACCESS_INFO`/`TZ`/`LOG_LEVEL`。

### 4.7 README.md

重写定位为「纯 MCP server」：暴露 `http://<container>:8000/mcp`（mcp-net 内），接小智请配 XiaozhiMCPManager。本地开发：`uv sync` → `uv run python server.py`（启动后用 MCP 客户端连 `http://localhost:8000/mcp`）。说明需先 `docker network create mcp-net`。

### 4.8 uv.lock

重新生成（`uv lock`）：移除 mcp2xiaozhi 及其独有传递依赖；确保 `mcp[cli]` + uvicorn/starlette 等在锁内。

## 5. 新仓库 XiaozhiMCPManager（`~/Projects/XiaozhiMCPManager`）

极简部署，几乎无 Python 代码——「mcp2xiaozhi + 一份清单」的容器化。用 uv 管理（与 baby-feeding 一致）。

### 5.1 目录

```
XiaozhiMCPManager/
├── Dockerfile
├── docker-compose.yml
├── mcp_config.json        # MCP URL 清单
├── pyproject.toml         # 仅 mcp2xiaozhi 依赖
├── uv.lock
├── .env.example
├── .dockerignore
├── .gitignore
└── README.md
```

### 5.2 pyproject.toml

```toml
[project]
name = "xiaozhi-mcp-manager"
version = "0.1.0"
description = "统一桥接多个 MCP server 到小智AI"
requires-python = ">=3.11,<3.13"
dependencies = [
    "mcp2xiaozhi>=0.2.1",
]

[tool.uv]
package = false
```

### 5.3 Dockerfile

与 baby-feeding 同构：python:3.12-slim + 清华 apt/pip 源 + tzdata + uv（`uv sync --frozen --no-dev` 装到 `/app/.venv`）+ `PATH=/app/.venv/bin`。`COPY pyproject.toml uv.lock` → `uv sync` → `COPY mcp_config.json`。`CMD ["mcp2xiaozhi", "run", "--all"]`。

### 5.4 docker-compose.yml

```yaml
services:
  xiaozhi-mcp-manager:
    build: .
    image: xiaozhi-mcp-manager:latest
    container_name: xiaozhi-mcp-manager
    restart: unless-stopped
    init: true
    env_file: .env
    environment:
      TZ: Asia/Shanghai
    volumes:
      - ./mcp_config.json:/app/mcp_config.json:ro
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

### 5.5 mcp_config.json

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

（0.2.1 已修 env 继承 bug；streamablehttp 无 stdio 子进程，无 env 问题。新增 MCP 照此加条目，`type` 也可是 `sse`/`stdio`。）

### 5.6 .env.example

```env
# 小智AI MCP接入点
MCP_ENDPOINT=wss://api.xiaozhi.me/mcp/?token=YOUR_TOKEN_HERE

# 时区与日志
TZ=Asia/Shanghai
LOG_LEVEL=INFO
```

### 5.7 .dockerignore / .gitignore

`.dockerignore` 排除 `.env`/`.env.*`/`.git`/`.venv`/`__pycache__`/`*.pyc`/`docs`。
`.gitignore` 排除 `.env`/`.venv`/`__pycache__`/`*.pyc`/`.claude`/`CLAUDE.md`。

### 5.8 README.md

三步上手：① `docker network create mcp-net`（若没有）② `cp .env.example .env` 填 `MCP_ENDPOINT` ③ `docker compose up -d --build`。「如何加一个新 MCP」小节（在 mcp_config.json 加条目 + 该 MCP 容器加入 mcp-net）。国内镜像加速说明（daemon registry-mirrors）。

## 6. 数据流

小智语音 → wss → manager(mcp2xiaozhi) → 按 mcp_config 清单，对每个 MCP 用 streamable_http_client 连 `http://<name>:8000/mcp` → 聚合各 MCP 工具列表返回给小智 → 小智选工具 → manager 转发到对应 MCP → MCP 执行（baby-feeding 调美柚 API）→ 结果回流。mcp2xiaozhi 负责断线重连（对 wss 和每个 HTTP MCP 都有）。

## 7. 验证计划

1. `docker network create mcp-net`。
2. **baby-feeding-mcp**：`uv lock` → `docker compose build` → `docker compose up -d`。
   - 验证 HTTP 端点：`docker run --rm --network mcp-net curlimages/curl -s -X POST -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}' http://baby-feeding-mcp:8000/mcp` 应返回 initialize 响应。
3. **XiaozhiMCPManager**：`uv lock` → `docker compose build` → `docker compose up -d`。
   - 日志确认：连上小智 wss + 桥接 `baby-feeding`（streamablehttp），`ListToolsRequest` 返回 9 个 baby-feeding 工具。
4. 用户小智实测（说「记录喝奶 180 毫升」等）。
5. `docker compose stop` 验证两边都干净退出（init:true）。

## 8. 迁移注意（对用户现有部署）

- 用户当前 baby-feeding-mcp 在跑旧版（内嵌 mcp2xiaozhi 直连小智）。改造后 baby-feeding 不再连小智，需**另部署 manager**。
- 用户的 `MCP_ENDPOINT`（小智 wss token）要从 baby-feeding 的 `.env` **移到 manager 的 `.env`**；baby-feeding 的 `.env` 只留 `BABY_*`/`LINGGAN_*`。
- 改造期间若 manager 还没起来，baby-feeding 仍是可用 MCP server，只是没人桥接。

## 9. 不在范围内

- 不给 HTTP 端点加鉴权（私有网络，预留 headers 字段）。
- manager 不做 Web UI / 动态加载清单（纯静态 mcp_config.json，改了重启）。
- 不迁移现有 git 历史或 token（上轮已处理）。

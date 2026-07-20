# Design: Docker Compose 迁移 + 代码修复

- 日期: 2026-07-20
- 状态: 已批准（待 spec 复核）
- 范围: baby-feeding-mcp 单仓库

## 1. 背景与目标

当前 baby-feeding-mcp 通过手写的 `mcp_pipe.py`（stdio↔WebSocket 管道）连接小智AI，部署方式为 systemd 服务。代码审查（49 个 agent、对抗式验证）发现约 25 个真实缺陷，分布在 `server.py`、`mcp_pipe.py`、`start.sh` 与配置文件。

本次目标：

1. **去除 systemctl 部署**，全部改用 docker compose。
2. 用作者维护的 [`mcp2xiaozhi`](https://github.com/StanleyChanH/MCP2Xiaozhi) 包（PyPI 发布、uv 管理、原生 SIGINT/SIGTERM、抖动重连、协议级中继）**替换手写的 `mcp_pipe.py`**，顺带消灭 mcp_pipe 的一整类 bug。
3. **修复 server.py 全部已确认 bug**（用户选择「全部修复」）。
4. 构建镜像时使用**国内镜像源**（pip/apt 走清华，基础镜像走 daemon registry-mirror）。
5. Python 环境用 **uv** 管理。
6. 将硬编码的真实 `linggan_access_token` 移到 env，并**重写 git 历史**抹除。

## 2. 架构

```
小智AI (MCP client) ◄── wss ──► │ 容器 baby-feeding-mcp (init:true / tini 做 PID1)
                                 │   mcp2xiaozhi run --all
                                 │     └─ stdio 拉起 ─► python /app/server.py (FastMCP 工具)
```

- `server.py` 保持 FastMCP stdio 服务不变，仅修 bug。
- `mcp_config.json` 描述如何启动 `server.py`，由 mcp2xiaozhi 读取。
- `.env`（仅本地、gitignored）注入 `MCP_ENDPOINT` 与各 `BABY_*` / `LINGGAN_*` 密钥到容器环境，stdio 子进程继承。

## 3. 文件变更

### 新增

#### `Dockerfile`

- `FROM python:3.12-slim`（靠宿主 daemon 的 `registry-mirrors` 加速拉取）。
- apt 换国内源：将 bookworm 的 `deb.debian.org` → `mirrors.tuna.tsinghua.edu.cn`（处理 `/etc/apt/sources.list.d/debian.sources` DEB822 格式）。
- 装 `tzdata`，设 `TZ=Asia/Shanghai`，软链 `/etc/localtime`（修记录时间戳 8 小时偏差）。
- 设 `UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple`、`UV_PYTHON_PREFERENCE=only-system`、`PIP_INDEX_URL=...tsuna...`。
- `pip install uv`（走清华源，避免拉 ghcr 的 uv 镜像）。
- 先 `COPY pyproject.toml uv.lock`，`uv sync --frozen --no-dev`（`package=false` 故无需 `--no-install-project`；先拷 lock 利用缓存层）。
- 再 `COPY server.py mcp_config.json` 到 `/app`。
- `ENV TZ=Asia/Shanghai PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH=/app/.venv/bin:$PATH`。
- `WORKDIR /app`。
- `CMD ["mcp2xiaozhi", "run", "--all"]`（uv sync 已把 `mcp2xiaozhi` 装进 `/app/.venv/bin`，PATH 已覆盖）。

#### `docker-compose.yml`

- 服务 `baby-feeding-mcp`：`build: .`，`image: baby-feeding-mcp:latest`，`container_name: baby-feeding-mcp`。
- `init: true`（tini 做 PID1，转发信号、回收僵尸子进程）。
- `restart: unless-stopped`。
- `env_file: .env`；`environment:` 显式 `TZ: Asia/Shanghai`（双保险）。
- `volumes: ./mcp_config.json:/app/mcp_config.json:ro`（可改配置免重建）。
- `logging: json-file, max-size 10m, max-file 3`。

#### `.dockerignore`

排除：`.env`、`.env.*`、`.git/`、`.venv/`、`venv/`、`__pycache__/`、`*.pyc`、`.claude/`、`CLAUDE.md`、`docs/`、`README.md`（可选）、`tests/`（若有）。关键：**防止 `.env` 进镜像层**。

### 修改

#### `server.py`（修复清单见 §4）

#### `mcp_config.json`

删除会覆盖真实环境变量的 `env` 块（`${BABY_TOKEN}` 等字面量从不会被展开，且 `child_env[k]=v` 会覆盖 os.environ 里由 env_file 注入的真值）。改为：

```json
{
  "mcpServers": {
    "baby-feeding": {
      "type": "stdio",
      "command": "python",
      "args": ["/app/server.py"]
    }
  }
}
```

（容器内子进程继承 os.environ，BABY_* 由 env_file 提供。）

#### `pyproject.toml`

- 删除无效的 `[tool.hatch.build.targets.wheel] packages=["."]`（本仓库不是可安装包，server.py 作脚本运行；保留会产出损坏 wheel）。
- 依赖收敛为：`mcp2xiaozhi>=0.2.0`、`requests>=2.28.0`、`python-dotenv>=1.0.0`（mcp2xiaozhi 已带入 `mcp`、`websockets`，无需再列）。
- `requires-python = ">=3.11,<3.13"`（与 uv.lock 对齐，避免拉 3.13）。
- 加 `[tool.uv] package = false`：本仓库是应用而非可安装库，让 uv 只管理依赖、不把 `server.py` 当包构建；这样无需 `[build-system]`，也不需要 `--no-install-project` 标志。移除 `[build-system]` 与 `[tool.hatch...]`。

#### `.env.example`

- `BABY_TOKEN="XDS your_token_here"`（加引号，防空格截断）。
- 新增：`LINGGAN_ACCESS_TOKEN=`、`LINGGAN_ACCESS_INFO=`、`TZ=Asia/Shanghai`、`LOG_LEVEL=INFO`。
- 保留 `MCP_ENDPOINT`、`BABY_ID`、`COMMON_BABY_ID`、`BABY_BIRTHDAY`、`BABY_GENDER`。

#### `README.md`

- 删除「方式二：systemd 服务」段（76-107 行）与目录结构中的 `mcp_pipe.py`/`start.sh`/`requirements.txt`。
- 「运行」改为：方式一 `uv run python server.py`（本地调试）；方式二 `docker compose up -d --build`（推荐）。
- 新增「国内镜像加速」小节：附 `/etc/docker/daemon.json` 的 `registry-mirrors` 示例（阿里云/网易）。
- 更新目录结构，加入 `Dockerfile`/`docker-compose.yml`/`.dockerignore`。

### 删除

- `mcp_pipe.py`（由 mcp2xiaozhi 包替代）
- `start.sh`（compose 接管启动与 env）
- `requirements.txt`（收敛到 pyproject.toml + uv.lock）

## 4. server.py 修复清单（全部已对抗式验证）

| 严重度 | 位置 | 修复 |
|---|---|---|
| 🔴 安全 | `get_daily_change` 338-339 | `linggan_access_token`/`linggan_access_info` 改 `os.getenv`；移除冗余 `birthday_str` 入参，复用 `self.birthday` |
| 🟠 健壮 | `_post_request`/`get_records`/`get_daily_change` | 所有 `requests` 调用加 `timeout=(5, 15)`；改用模块级 `requests.Session`（连接池复用） |
| 🟠 正确 | `_calc_age_params` 310-313 | 抽出 `_age_components(birthday, today)` 用**真实日历**算 year/month/day，替换 `//365`+`//30`（修 364 天显示「12 个月」、365 天显示「1 岁 0 个月」的边界 bug） |
| 🟠 正确 | `record_bath` 150-164 | 补回 `baby_id` 与 `birthday`（其余 4 个 record_* 都有） |
| 🟠 正确 | `get_last_record` 工具 528 | 未知 `record_type` 返回 `{success:False, message:"未知类型"}`，不再静默返回任意记录 |
| 🟡 可用 | 模块顶部 16 | `logging.basicConfig(level=LOG_LEVEL, stream=sys.stderr, ...)`（**stderr**，stdout 留给 MCP 通信） |
| 🟡 正确 | `_get_times` 51-55 | 格式非法时 `logger.warning` 并抛 `ValueError`，由工具层返回错误；不再静默用 `now()` 记错时间 |
| 🟡 优化 | `get_recorder` 372 | 改单例（模块级缓存），不再每次工具调用重建 headers/解析生日 |
| 🟢 健壮 | `get_recorder` 378、`get_baby_info` 604 | `int(os.getenv("BABY_GENDER") or "1")` |
| 🟢 正确 | `get_recent_records` 562-573 | 去掉 `3 天×10 条=30` 的静默硬上限，让 `size` 语义一致 |
| 🟢 健壮 | `_get_times` | 轻量校验：`start_at` 不超现在、`end_at` 不早于 `start_at`（仅 warning） |
| 🟢 复用 | `get_baby_info` 610-621 | 复用 §4 的 `_age_components`，删除重复的月龄算法 |

注：`birthday_ms` naive timestamp（server.py:34）修为 UTC 确定性计算（`datetime(..., tzinfo=timezone.utc).timestamp()*1000` 或 `calendar.timegm`）。

## 5. 国内镜像源（写进 Dockerfile）

- **pip / uv**：`UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple`、`UV_PYTHON_PREFERENCE=only-system`、`PIP_INDEX_URL=...tsuna...`。
- **apt**：sed 替换 bookworm 源为 `mirrors.tuna.tsinghua.edu.cn`（装 tzdata）。
- **基础镜像**：`FROM python:3.12-slim`，README 附 daemon.json `registry-mirrors`（不在 Dockerfile 写死第三方 registry）。

## 6. git 历史重写（用户已确认）

`server.py:338` 的真实 token（`***REMOVED***` 与 base64 `***REMOVED***`）即使在 §4 移到 env，仍在历史 commit `64957b4` 中。

- 用 `git filter-repo --replace-text`（不可用则 `git filter-branch`）替换上述两串为 `***REMOVED***`。
- **会改写所有 commit hash**，需 force-push。
- 作为**最后一步单独执行**，执行前再次向用户确认；先在本地验证 `git log -S <token>` 无命中。

## 7. 验证计划

1. 本地 `.env` 填入用户提供的测试 wss token（**仅本地、不提交**）与各 `BABY_*`、`LINGGAN_*`。
2. `uv lock`（更新 lock 文件）→ `docker compose up -d --build`。
3. `docker compose logs -f` 确认 mcp2xiaozhi 连上小智（无 `${BABY_TOKEN}` 字面量报错、无 int() 异常）。
4. 用小智触发一次「记录喝奶 180ml」→ 确认美柚侧**记录时间戳为本地时间**（验证 TZ 修复）。
5. 触发「宝宝多大」→ 确认月龄计算正确（验证日历算法修复）。
6. `docker compose down` → 确认 SIGTERM 干净退出（init:true 生效）。

## 8. 不在范围内

- 不新增测试框架（仓库目前无测试；如需可后续加）。
- 不做多服务/多宝宝支持（mcp2xiaozhi 支持，但本仓库单宝宝）。
- 不改各 record_* 的 API payload 业务字段（仅修 baby_id/birthday 缺失）。

## 9. 风险

- **git 历史重写**：改写所有 hash、需 force-push；若仓库有其他克隆需同步。执行前确认。
- **mcp2xiaozhi 版本**：依赖 PyPI 的 `mcp2xiaozhi>=0.2.0`；若需特定版本，pin 到 uv.lock。
- **uv 本地可用性**：实现时需确认本机有 `uv`；无则先 `pip install uv`。
- **tzdata**：python:slim 默认无；已通过 apt 装 tzdata + 设 TZ 解决。

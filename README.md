# Baby Feeding MCP Server

宝宝抚养记录 MCP Server，用于接入小智AI语音助手。

## 功能

提供以下 MCP 工具：

| 工具名 | 功能 | 触发词 |
|--------|------|--------|
| `record_formula_milk` | 记录配方奶 | 喝奶、喂奶、吃奶粉 |
| `record_diaper` | 记录换尿布 | 换尿布、拉屎、尿尿 |
| `record_bath` | 记录洗澡 | 洗澡 |
| `record_food` | 记录辅食 | 辅食、米粉、果泥 |
| `record_water` | 记录喝水 | 喝水、喂水 |
| `get_last_record` | 获取最近一次记录 | 最近一次喂奶、上次换尿布 |
| `get_recent_records` | 获取最近记录列表 | 今天喂了几次 |
| `get_daily_change` | 获取每日变化建议 | 宝宝发育建议、身高体重参考 |
| `get_baby_info` | 获取宝宝基本信息 | 宝宝多大、宝宝生日、宝宝性别 |

## 快速开始（Docker Compose，推荐）

1. 复制环境变量模板并填写：

```bash
cp .env.example .env
# 编辑 .env，填入 MCP_ENDPOINT / BABY_TOKEN / BABY_ID 等
```

2. 启动：

```bash
docker compose up -d --build
docker compose logs -f
```

容器内 `mcp2xiaozhi` 会自动连接小智AI 并桥接 `server.py` 的 MCP 工具。断线自动重连。

### 配置项说明

| 变量 | 说明 |
|------|------|
| `MCP_ENDPOINT` | 小智AI的MCP WebSocket接入点 |
| `BABY_TOKEN` | 美柚API的授权Token（含空格务必加引号） |
| `BABY_ID` | 宝宝ID |
| `COMMON_BABY_ID` | 通用宝宝ID |
| `BABY_BIRTHDAY` | 宝宝生日，格式 YYYY-MM-DD |
| `BABY_GENDER` | 宝宝性别，0=女孩，1=男孩（默认） |
| `LINGGAN_ACCESS_TOKEN` | 每日变化建议API凭据（可选，留空则该工具不可用） |
| `LINGGAN_ACCESS_INFO` | 同上 |
| `TZ` | 容器时区，默认 Asia/Shanghai |
| `LOG_LEVEL` | 日志级别，默认 INFO |

## 本地开发（不使用 Docker）

需要 Python 3.11-3.12 与 [uv](https://docs.astral.sh/uv/)：

```bash
uv sync
# 直接调试 server.py（stdio）
uv run python server.py
# 或经 mcp2xiaozhi 桥接
uv run mcp2xiaozhi run --all
```

## 国内镜像加速

构建时 pip 与 apt 已在 Dockerfile 内指向清华源。基础镜像 `python:3.12-slim` 默认从 Docker Hub 拉取，国内建议在 `/etc/docker/daemon.json` 配置 registry-mirrors：

```json
{
  "registry-mirrors": [
    "https://docker.mirrors.ustc.edu.cn",
    "https://hub-mirror.c.163.com"
  ]
}
```

配置后 `sudo systemctl restart docker`。

## 工具参数详解

### record_formula_milk（配方奶）

```python
record_formula_milk(
    capacity_ml: int = 180,  # 奶量（毫升），默认180
    start_at: str = "",      # 开始时间，格式 "YYYY-MM-DD HH:MM:SS"，空=现在
    remark: str = ""         # 备注
)
```

### record_diaper（换尿布）

```python
record_diaper(
    category_type: str,         # "pee"(尿) / "poo"(屎) / "both"(都有)
    start_at: str = "",         # 时间，空=现在
    red_buttock: bool = False,  # 是否红屁屁
    remark: str = ""            # 备注
)
```

### record_bath（洗澡）

```python
record_bath(
    start_at: str = "",  # 开始时间，空=现在
    end_at: str = "",    # 结束时间，空=默认15分钟后
    remark: str = ""     # 备注
)
```

### record_food（辅食）

```python
record_food(
    food_name: str,      # 食物名称，如 "强化铁米粉"
    quantity_g: int,     # 数量（克）
    start_at: str = "",  # 时间，空=现在
    remark: str = ""     # 备注
)
```

### record_water（喝水）

```python
record_water(
    capacity_ml: int = 30,  # 喝水量（毫升），默认30
    start_at: str = "",     # 时间，空=现在
    remark: str = ""        # 备注
)
```

### get_last_record（获取最近记录）

```python
get_last_record(
    record_type: str = ""  # 类型：formula_milk/diaper/bath/food/water，空=全部
)
```

返回：记录类型、内容、时间、距离现在多久。

### get_recent_records（获取记录列表）

```python
get_recent_records(
    size: int = 20  # 获取数量，默认20
)
```

### get_daily_change（获取每日变化建议）

```python
get_daily_change()  # 无参数
```

返回：
- `content`：每日发育建议内容
- `height_min` / `height_max`：身高参考范围（cm）
- `weight_min` / `weight_max`：体重参考范围（kg）

### get_baby_info（获取宝宝基本信息）

```python
get_baby_info()  # 无参数
```

返回：
- `birthday`：宝宝生日（YYYY-MM-DD）
- `gender`：宝宝性别（男孩/女孩）
- `age_days`：宝宝出生天数
- `age_str`：宝宝年龄描述（如"5个月"）

## 目录结构

```
baby-feeding-mcp/
├── server.py            # MCP Server 主程序（FastMCP 工具）
├── mcp_config.json      # mcp2xiaozhi 服务定义
├── Dockerfile           # 镜像构建（uv + 国内源）
├── docker-compose.yml   # 编排
├── .dockerignore
├── .env.example         # 环境变量模板
├── .env                 # 环境变量（自行创建，不提交）
├── pyproject.toml       # 项目与依赖配置（uv 管理）
├── uv.lock              # 依赖锁文件
└── README.md
```

## 注意事项

1. **不要使用 print()**：MCP Server 的 stdin/stdout 用于通信，请使用 `logger` 输出调试信息

2. **返回值限制**：工具返回值限制在约 1024 字节内

3. **自动重连**：`mcp2xiaozhi` 内置抖动指数退避重连，断线自动恢复

4. **工具命名**：工具名和参数名要清晰明了，让大模型能理解用途

## 相关链接

- [小智AI MCP接入点文档](https://xiaozhi.me)
- [MCP 协议规范](https://modelcontextprotocol.io)
- [FastMCP 文档](https://github.com/modelcontextprotocol/python-sdk)

## License

MIT

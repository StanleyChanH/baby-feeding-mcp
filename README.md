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

## 注意事项

1. **不要使用 print()**：日志已配置到 stderr，请用 `logger` 输出调试信息（保持习惯，便于容器日志聚合）

2. **返回值限制**：工具返回值限制在约 1024 字节内

3. **自动重连**：连小智的重连由 XiaozhiMCPManager 的 mcp2xiaozhi 负责；本服务只是无状态 MCP server

4. **工具命名**：工具名和参数名要清晰明了，让大模型能理解用途

## 相关链接

- [小智AI MCP接入点文档](https://xiaozhi.me)
- [MCP 协议规范](https://modelcontextprotocol.io)
- [FastMCP 文档](https://github.com/modelcontextprotocol/python-sdk)

## License

MIT

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

## 安装

```bash
cd baby-feeding-mcp
pip install -r requirements.txt
```

或使用 uv：

```bash
uv venv
uv pip install -r requirements.txt
```

## 配置

1. 复制环境变量模板：

```bash
cp .env.example .env
```

2. 编辑 `.env` 文件，填入你的配置：

```env
# 小智AI MCP接入点（从小智AI控制台获取）
MCP_ENDPOINT=wss://api.xiaozhi.me/mcp/?token=你的token

# 宝宝抚养记录API配置
BABY_TOKEN=XDS your_token_here
BABY_ID=123456789
COMMON_BABY_ID=987654321
BABY_BIRTHDAY=2025-08-20
BABY_GENDER=1
```

### 配置项说明

| 变量 | 说明 |
|------|------|
| `MCP_ENDPOINT` | 小智AI的MCP WebSocket接入点 |
| `BABY_TOKEN` | 美柚API的授权Token |
| `BABY_ID` | 宝宝ID |
| `COMMON_BABY_ID` | 通用宝宝ID |
| `BABY_BIRTHDAY` | 宝宝生日，格式 YYYY-MM-DD |
| `BABY_GENDER` | 宝宝性别，0=女孩，1=男孩（默认） |

## 运行

### 方式一：直接运行

```bash
python mcp_pipe.py server.py
```

### 方式二：systemd 服务（推荐生产环境）

```bash
# 创建服务文件
sudo nano /etc/systemd/system/baby-feeding-mcp.service
```

内容：
```ini
[Unit]
Description=Baby Feeding MCP Server for XiaoZhi AI
After=network.target

[Service]
Type=simple
User=你的用户名
WorkingDirectory=/path/to/baby-feeding-mcp
EnvironmentFile=/path/to/baby-feeding-mcp/.env
ExecStart=/path/to/baby-feeding-mcp/.venv/bin/python mcp_pipe.py server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启动：
```bash
sudo systemctl daemon-reload
sudo systemctl start baby-feeding-mcp
sudo systemctl enable baby-feeding-mcp
```

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

## 目录结构

```
baby-feeding-mcp/
├── server.py           # MCP Server 主程序
├── mcp_pipe.py         # WebSocket 管道（连接小智AI）
├── mcp_config.json     # MCP 服务配置
├── .env.example        # 环境变量模板
├── .env                # 环境变量（需自行创建）
├── requirements.txt    # Python 依赖
├── pyproject.toml      # 项目配置
├── start.sh            # 启动脚本
└── README.md           # 说明文档
```

## 注意事项

1. **不要使用 print()**：MCP Server 的 stdin/stdout 用于通信，请使用 `logger` 输出调试信息

2. **返回值限制**：工具返回值限制在约 1024 字节内

3. **自动重连**：`mcp_pipe.py` 内置自动重连机制，断线后会指数退避重试

4. **工具命名**：工具名和参数名要清晰明了，让大模型能理解用途

## 相关链接

- [小智AI MCP接入点文档](https://xiaozhi.me)
- [MCP 协议规范](https://modelcontextprotocol.io)
- [FastMCP 文档](https://github.com/modelcontextprotocol/python-sdk)

## License

MIT

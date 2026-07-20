# Docker Compose 迁移 + 代码修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 baby-feeding-mcp 从 systemd 部署迁移到 docker compose，用 `mcp2xiaozhi` 包替换手写的 `mcp_pipe.py`，并修复 server.py 中全部已验证 bug。

**Architecture:** 容器内 `mcp2xiaozhi run --all`（由 compose `init:true` 作 PID1）通过 stdio 拉起 `python /app/server.py`（FastMCP 工具），经 wss 连接小智AI。环境变量由 compose `env_file: .env` 注入，子进程继承。依赖由 `uv` 基于 `uv.lock` 锁定安装，构建时走清华 pip 源 + apt 源。

**Tech Stack:** Python 3.12-slim, uv 0.11.x, mcp2xiaozhi>=0.2.0, requests, FastMCP, Docker Compose v5.

**Spec:** [docs/superpowers/specs/2026-07-20-docker-compose-migration-design.md](../specs/2026-07-20-docker-compose-migration-design.md)

## Global Constraints

- Python `requires-python = ">=3.11,<3.13"`；Dockerfile 基础镜像固定 `python:3.12-slim`。
- pip/uv 走 `https://pypi.tuna.tsinghua.edu.cn/simple`；apt 走 `mirrors.tuna.tsinghua.edu.cn`；基础镜像靠宿主 daemon `registry-mirrors`（Dockerfile 不写死第三方 registry）。
- 容器时区固定 `Asia/Shanghai`（美柚/小智均为中国服务，记录时间戳必须本地时间）。
- stdout 专供 MCP stdio 通信，**所有日志走 stderr**。
- `.env` 永不进镜像层（`.dockerignore` 排除 + 仅 compose env_file 注入）。
- 依赖单一来源：`pyproject.toml` + `uv.lock`；删除 `requirements.txt`。
- 仓库当前无测试框架，本计划**不引入测试框架**；纯函数用 `python -c` 内联验证，集成用 docker compose 冒烟测试。

**分支:** 所有工作在 `feat/docker-compose-migration` 分支（已创建并已提交 spec）。

---

## File Structure

| 文件 | 职责 | 动作 |
|---|---|---|
| `server.py` | FastMCP 工具 + BabyRecorder API 客户端 | 修改（修 bug） |
| `pyproject.toml` | 依赖声明（uv 管理，package=false） | 重写 |
| `mcp_config.json` | mcp2xiaozhi 服务定义 | 重写 |
| `.env.example` | 环境变量模板 | 重写 |
| `Dockerfile` | 镜像构建（uv + 国内源 + tzdata） | 新建 |
| `docker-compose.yml` | 编排（init/env_file/挂载） | 新建 |
| `.dockerignore` | 排除 .env 等进镜像 | 新建 |
| `README.md` | 部署文档 | 修改 |
| `uv.lock` | 锁文件 | 重新生成 |
| `mcp_pipe.py` | 旧管道（由 mcp2xiaozhi 替代） | 删除 |
| `start.sh` | 旧启动脚本 | 删除 |
| `requirements.txt` | 旧依赖（收敛到 pyproject） | 删除 |

---

## Task 1: server.py — 安全与健壮性地基

**Files:**
- Modify: `server.py`（imports 区、`BabyRecorder.__init__`、`_post_request`、`get_records`、`get_daily_change`、`get_recorder`、`get_baby_info`、模块级 `get_daily_change` 工具）

**Interfaces:**
- Produces: `BabyRecorder.session`（`requests.Session` 实例）；`get_recorder()` 改为单例；`get_daily_change` 不再接受 `birthday_str` 参数。

- [ ] **Step 1: 在 imports 后配置 logging（输出到 stderr）**

修改 [server.py](../../../server.py) 顶部，把现有的 `logger = logging.getLogger(...)` 之前补上 basicConfig。把：

```python
from mcp.server.fastmcp import FastMCP
import logging
import requests
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os

# 加载环境变量
load_dotenv()

# 配置日志
logger = logging.getLogger('baby_feeding_mcp')
```

替换为：

```python
from mcp.server.fastmcp import FastMCP
import logging
import requests
import json
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
import os

# 加载环境变量
load_dotenv()

# 配置日志 —— stdout 留给 MCP stdio 通信，日志一律走 stderr
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr,
)
logger = logging.getLogger('baby_feeding_mcp')

# 美柚/小智均为中国服务，统一用东八区，避免容器内 UTC 导致记录时间戳偏 8 小时
CN_TZ = ZoneInfo("Asia/Shanghai")
# HTTP 请求超时（连接, 读取）秒
REQUEST_TIMEOUT = (5, 15)
```

- [ ] **Step 2: `BabyRecorder.__init__` 加 `requests.Session`，`birthday_ms` 用 CN_TZ**

把 [server.py:25-45](../../../server.py#L25-L45) 的 `__init__` 中的 birthday 解析与 headers 之后，加上 session。把：

```python
    def __init__(self, token, baby_id, common_baby_id, birthday_str, baby_gender=1):
        self.url = "https://api-bbj.meiyou.com/v3/life/record"
        self.baby_id = baby_id
        self.common_baby_id = common_baby_id
        self.baby_gender = baby_gender  # 0=女孩, 1=男孩
        self.birthday = None

        try:
            self.birthday = datetime.strptime(birthday_str, "%Y-%m-%d")
            self.birthday_ms = int(self.birthday.timestamp() * 1000)
            logger.info(f"初始化完成: 生日 {birthday_str}, 性别 {'男孩' if baby_gender == 1 else '女孩'}")
        except ValueError:
            logger.error(f"生日格式错误: {birthday_str}")
            self.birthday_ms = 0

        self.headers = {
```

替换为：

```python
    def __init__(self, token, baby_id, common_baby_id, birthday_str, baby_gender=1):
        self.url = "https://api-bbj.meiyou.com/v3/life/record"
        self.baby_id = baby_id
        self.common_baby_id = common_baby_id
        self.baby_gender = baby_gender  # 0=女孩, 1=男孩
        self.birthday_str = birthday_str
        self.birthday = None

        try:
            self.birthday = datetime.strptime(birthday_str, "%Y-%m-%d")
            # 显式东八区，确定性计算（naive .timestamp() 依赖宿主 TZ，容器间不一致）
            self.birthday_ms = int(self.birthday.replace(tzinfo=CN_TZ).timestamp() * 1000)
            logger.info(f"初始化完成: 生日 {birthday_str}, 性别 {'男孩' if baby_gender == 1 else '女孩'}")
        except ValueError:
            logger.error(f"生日格式错误: {birthday_str}")
            self.birthday_ms = 0

        self.headers = {
```

并在 `self.headers = {...}` 字典结束（`}`）之后、`__init__` 末尾，追加一行：

```python
        # 连接池复用，避免每次请求重新 TCP+TLS 握手
        self.session = requests.Session()
```

- [ ] **Step 3: `_post_request` 用 session + timeout**

把 [server.py:68-85](../../../server.py#L68-L85) 的 `_post_request` 中的：

```python
            response = requests.post(self.url, headers=self.headers, data=json.dumps(payload))
```

替换为：

```python
            response = self.session.post(
                self.url, headers=self.headers, data=json.dumps(payload), timeout=REQUEST_TIMEOUT
            )
```

- [ ] **Step 4: `get_records` 用 session + timeout**

把 [server.py:240](../../../server.py#L240) 的：

```python
            response = requests.get(list_url, headers=headers, params=params)
```

替换为：

```python
            response = self.session.get(list_url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
```

- [ ] **Step 5: `get_recorder` 改单例 + BABY_GENDER 空值保护**

把 [server.py:371-383](../../../server.py#L371-L383) 的整个 `get_recorder` 函数替换为：

```python
# 单例：避免每次工具调用都重建 headers、解析生日、新建 Session
_recorder_instance = None


def get_recorder():
    """获取 BabyRecorder 单例实例"""
    global _recorder_instance
    if _recorder_instance is None:
        token = os.getenv("BABY_TOKEN")
        baby_id = os.getenv("BABY_ID")
        common_baby_id = os.getenv("COMMON_BABY_ID")
        birthday = os.getenv("BABY_BIRTHDAY")
        # os.getenv 只在变量「未设置」时返回默认值；显式空串 BABY_GENDER= 会触发 int('')。
        # `or "1"` 同时覆盖未设置与空串两种情况。
        baby_gender = int(os.getenv("BABY_GENDER") or "1")  # 默认男孩

        if not all([token, baby_id, common_baby_id, birthday]):
            raise ValueError("请配置环境变量: BABY_TOKEN, BABY_ID, COMMON_BABY_ID, BABY_BIRTHDAY")

        _recorder_instance = BabyRecorder(token, int(baby_id), int(common_baby_id), birthday, baby_gender)
    return _recorder_instance
```

- [ ] **Step 6: `get_daily_change` 方法：token 移到 env，去掉 `birthday_str` 参数**

把 [server.py:323-368](../../../server.py#L323-L368) 的 `get_daily_change` 方法替换为：

```python
    def get_daily_change(self):
        """获取宝宝每日变化建议"""
        age_params = self._calc_age_params()
        if not age_params:
            return {"success": False, "message": "生日配置错误，无法计算年龄"}

        url = "https://gravidity.seeyouyima.com/v3/baby_grow/baby_change"

        # 转换生日格式：2025-08-21 -> 20250821（复用 __init__ 已解析的值，避免重复入参）
        bbday = self.birthday_str.replace("-", "") if self.birthday_str else ""

        # linggan 凭据从环境变量读取（历史硬编码值已迁移到 .env，并从 git 历史抹除）
        linggan_token = os.getenv("LINGGAN_ACCESS_TOKEN", "")
        linggan_info = os.getenv("LINGGAN_ACCESS_INFO", "")

        headers = {
            **self.headers,
            "bbid": str(self.common_baby_id),
            "bbday": bbday,
            "linggan_access_info": linggan_info,
            "linggan_access_token": linggan_token,
            "x-visit-mode": "1",
            "user-agent": self.headers["ua"]
        }
        if "Content-Type" in headers:
            del headers["Content-Type"]

        try:
            response = self.session.get(url, headers=headers, params=age_params, timeout=REQUEST_TIMEOUT)
            if response.status_code == 200:
                res = response.json()
                if res.get("code") == 0:
                    logger.info(f"获取每日变化建议成功")
                    data = res.get("data", {})
                    hw = data.get("hw", {})
                    return {
                        "success": True,
                        "content": data.get("content", ""),
                        "height_min": hw.get("height_min", ""),
                        "height_max": hw.get("height_max", ""),
                        "weight_min": hw.get("weight_min", ""),
                        "weight_max": hw.get("weight_max", "")
                    }
                else:
                    return {"success": False, "message": res.get('message', '未知错误')}
            else:
                return {"success": False, "message": f"HTTP错误: {response.status_code}"}
        except Exception as e:
            logger.error(f"获取每日变化建议异常: {e}")
            return {"success": False, "message": f"网络异常: {str(e)}"}
```

- [ ] **Step 7: `get_daily_change` 工具：去掉 `birthday` 传参**

把 [server.py:579-592](../../../server.py#L579-L592) 的 `get_daily_change` 工具替换为：

```python
@mcp.tool()
def get_daily_change() -> dict:
    """
    获取宝宝每日变化建议。当用户问"宝宝今天有什么变化"、"宝宝发育建议"等问题时使用此工具。

    返回宝宝每日发育建议内容，以及当前月龄对应的身高体重参考范围。
    """
    try:
        recorder = get_recorder()
        return recorder.get_daily_change()
    except Exception as e:
        return {"success": False, "message": str(e)}
```

- [ ] **Step 8: `get_baby_info` 工具：BABY_GENDER 空值保护**

把 [server.py:595-634](../../../server.py#L595-L634) 中 `get_baby_info` 内的：

```python
        baby_gender = int(os.getenv("BABY_GENDER", "1"))
```

替换为：

```python
        baby_gender = int(os.getenv("BABY_GENDER") or "1")
```

- [ ] **Step 9: 语法与导入冒烟验证**

Run:
```bash
cd /home/hajimi/Projects/baby-feeding-mcp
python -m py_compile server.py && echo "PY_COMPILE_OK"
```
Expected: 输出 `PY_COMPILE_OK`，无 SyntaxError。

- [ ] **Step 10: 提交**

```bash
git add server.py
git commit -m "$(cat <<'EOF'
refactor(server): harden plumbing — logging, session, singleton, env secrets

- Configure module-level logging to stderr (stdout reserved for MCP stdio).
- Use requests.Session with (5,15)s timeout on all 3 HTTP call sites.
- Make get_recorder() a singleton (rebuild headers/parse birthday once).
- Guard BABY_GENDER against empty-string env (int('') crash).
- Move hardcoded linggan_access_token/info to env vars.
- Drop redundant birthday_str param from get_daily_change.
- Compute birthday_ms with explicit Asia/Shanghai tz.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: server.py — 业务正确性修复

**Files:**
- Modify: `server.py`（`_calc_age_params`、`record_bath`、`get_last_record` 工具、`_get_times`、`get_recent_records` 工具、新增 `_age_components`）

**Interfaces:**
- Produces: 模块级函数 `_age_components(birthday, today) -> (years, months, days, total_days)`；`_calc_age_params` 与 `get_baby_info` 均消费它。

- [ ] **Step 1: 新增 `_age_components` 日历月龄辅助函数**

在 `BabyRecorder` 类**之前**（`mcp = FastMCP(...)` 之后、`class BabyRecorder:` 之前）插入：

```python
def _age_components(birthday, today):
    """用真实日历计算年龄，返回 (years, months, days, total_days)。

    旧的 //365 + //30 写法在边界处出错：364 天显示「12 个月」、365 天显示「1 岁 0 个月」。
    日历算法按年/月/日分量借位，与人类计数一致。
    """
    import calendar as _cal
    total_days = (today - birthday).days

    years = today.year - birthday.year
    months = today.month - birthday.month
    days = today.day - birthday.day

    if days < 0:
        months -= 1
        # 借上一个月的天数
        prev_month = today.month - 1 or 12
        prev_year = today.year if today.month != 1 else today.year - 1
        days += _cal.monthrange(prev_year, prev_month)[1]
    if months < 0:
        years -= 1
        months += 12

    return years, months, days, total_days
```

- [ ] **Step 2: `_calc_age_params` 改用日历算法**

把 [server.py:303-321](../../../server.py#L303-L321) 的 `_calc_age_params` 替换为：

```python
    def _calc_age_params(self):
        """计算宝宝年龄参数，用于每日变化API"""
        if not self.birthday:
            return None

        today = datetime.now()
        years, months, days, total_days = _age_components(self.birthday, today)

        return {
            "parenting_info": total_days,
            "parenting_year": years,
            "month_of_year": months,
            "day_of_month": days,
            "baby_gender": self.baby_gender
        }
```

- [ ] **Step 3: `get_baby_info` 工具复用 `_age_components`**

把 [server.py:609-623](../../../server.py#L609-L623) 中 `get_baby_info` 的年龄计算块：

```python
        # 计算年龄
        try:
            birthday_dt = datetime.strptime(birthday, "%Y-%m-%d")
            today = datetime.now()
            days = (today - birthday_dt).days
            months = days // 30
            years = days // 365
            remaining_months = (days % 365) // 30

            if years > 0:
                age_str = f"{years}岁{remaining_months}个月"
            else:
                age_str = f"{months}个月"
        except ValueError:
            age_str = "未知"
```

替换为：

```python
        # 计算年龄（复用日历算法，避免边界 bug）
        try:
            birthday_dt = datetime.strptime(birthday, "%Y-%m-%d")
            today = datetime.now()
            years, months, _days, total_days = _age_components(birthday_dt, today)

            if years > 0:
                age_str = f"{years}岁{months}个月"
            else:
                age_str = f"{months}个月"
        except ValueError:
            total_days = 0
            age_str = "未知"
```

并把同函数返回字典里的 `"age_days": days,` 改为 `"age_days": total_days,`。

- [ ] **Step 4: `record_bath` 补回 `baby_id` 与 `birthday`**

把 [server.py:150-164](../../../server.py#L150-L164) 中 `record_bath` 的 payload，在 `"client_rid": 17,` **之前**插入两行：

```python
        payload = {
            "baby_id": self.baby_id,
            "birthday": self.birthday_ms,
            "client_rid": 17,
            "common_baby_id": self.common_baby_id,
```

（即 payload 头部加上 `baby_id` 和 `birthday`，与其它 4 个 record_* 一致。）

- [ ] **Step 5: `get_last_record` 工具校验未知类型**

把 [server.py:516-529](../../../server.py#L516-L529) 的类型映射与调用块：

```python
        # 类型映射
        type_map = {
            "formula_milk": 1, "喝奶": 1, "喂奶": 1, "配方奶": 1,
            "food": 3, "辅食": 3, "米粉": 3,
            "diaper": 4, "换尿布": 4, "拉屎": 4, "尿尿": 4,
            "bath": 5, "洗澡": 5,
            "water": 10, "喝水": 10, "喂水": 10
        }

        record_type_code = type_map.get(record_type) if record_type else None
        result = recorder.get_last_record(record_type_code)
```

替换为：

```python
        # 类型映射
        type_map = {
            "formula_milk": 1, "喝奶": 1, "喂奶": 1, "配方奶": 1,
            "food": 3, "辅食": 3, "米粉": 3,
            "diaper": 4, "换尿布": 4, "拉屎": 4, "尿尿": 4,
            "bath": 5, "洗澡": 5,
            "water": 10, "喝水": 10, "喂水": 10
        }

        record_type_code = None
        if record_type:
            record_type_code = type_map.get(record_type)
            if record_type_code is None:
                # 未知类型不应静默退化为「返回任意类型最近一条」
                return {"success": False, "message": f"未知记录类型: {record_type}"}
        result = recorder.get_last_record(record_type_code)
```

- [ ] **Step 6: `_get_times` 格式非法报错 + 未来时间告警**

把 [server.py:47-66](../../../server.py#L47-L66) 的 `_get_times` 替换为：

```python
    def _get_times(self, start_at=None, end_at=None, duration_minutes=10):
        """智能时间计算。start_at 格式非法时抛 ValueError（由工具层转为错误返回），
        不再静默用 now() 记错时间。"""
        fmt = "%Y-%m-%d %H:%M:%S"
        now = datetime.now()

        if start_at:
            try:
                start_dt = datetime.strptime(start_at, fmt)
            except ValueError as e:
                logger.warning(f"start_at 格式无效，已拒绝记录: {start_at} ({e})")
                raise ValueError(f"start_at 格式应为 {fmt}，收到: {start_at}") from e
            if start_dt > now:
                logger.warning(f"start_at 晚于当前时间: {start_at}")
        else:
            start_dt = now

        if end_at:
            end_str = end_at
        else:
            end_dt = start_dt + timedelta(minutes=duration_minutes)
            end_str = end_dt.strftime(fmt)

        start_str = start_dt.strftime(fmt)
        return start_str, end_str
```

- [ ] **Step 7: `get_recent_records` 工具去掉 30 条静默上限**

把 [server.py:562-573](../../../server.py#L562-L573) 的聚合块：

```python
            for day_item in data.get("list", [])[:3]:  # 只取最近3天
                date = day_item.get("date", "")
                for record in day_item.get("records", [])[:10]:  # 每天最多10条
                    records_summary.append({
                        "date": date,
                        "time": record.get("start_at", ""),
                        "type": record.get("record_type_name", ""),
                        "content": record.get("record_content", ""),
                        "remark": record.get("remark", "")
                    })

            return {"success": True, "records": records_summary[:size]}
```

替换为：

```python
            for day_item in data.get("list", []):
                date = day_item.get("date", "")
                for record in day_item.get("records", []):
                    records_summary.append({
                        "date": date,
                        "time": record.get("start_at", ""),
                        "type": record.get("record_type_name", ""),
                        "content": record.get("record_content", ""),
                        "remark": record.get("remark", "")
                    })

            # API 已按 size 返回，这里再按 size 截断输出，语义一致
            return {"success": True, "records": records_summary[:size]}
```

- [ ] **Step 8: 验证年龄日历算法（内联，无需框架）**

Run:
```bash
cd /home/hajimi/Projects/baby-feeding-mcp
python -c "
from datetime import datetime
from server import _age_components
b = datetime(2024,8,20)
# 364 天：应约 11 个月 30 天，不是旧 bug 的「12 个月」
y,m,d,t = _age_components(b, datetime(2025,8,19))
assert (y,m,d) == (0,11,30), (y,m,d)
# 恰好一年
y,m,d,t = _age_components(b, datetime(2025,8,20))
assert (y,m,d) == (1,0,0), (y,m,d)
print('AGE_MATH_OK')
"
```
Expected: 输出 `AGE_MATH_OK`。若失败，检查 `_age_components` 的借位逻辑。

- [ ] **Step 9: 语法冒烟**

Run:
```bash
python -m py_compile server.py && echo "PY_COMPILE_OK"
```
Expected: `PY_COMPILE_OK`。

- [ ] **Step 10: 提交**

```bash
git add server.py
git commit -m "$(cat <<'EOF'
fix(server): correctness bugs — age math, bath baby_id, type validation

- Replace //365 //30 day-math with calendar-based _age_components
  (fixes 364d='12个月', 365d='1岁0个月' boundary bug); reuse in get_baby_info.
- Add missing baby_id + birthday to record_bath payload.
- Reject unknown record_type in get_last_record instead of silent fallback.
- _get_times raises on bad start_at format (no silent now() substitution).
- Remove 3daysx10 silent cap in get_recent_records (respect size).

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 配置收敛 + 删除旧文件

**Files:**
- Rewrite: `pyproject.toml`, `mcp_config.json`, `.env.example`
- Delete: `mcp_pipe.py`, `start.sh`, `requirements.txt`
- Regenerate: `uv.lock`

**Interfaces:**
- Produces: `pyproject.toml` 声明 `mcp2xiaozhi>=0.2.0`/`requests`/`python-dotenv`，`[tool.uv] package=false`；`uv.lock` 与之一致；`mcp_config.json` 指向容器内 `/app/server.py`。

- [ ] **Step 1: 重写 `pyproject.toml`**

把整个 [pyproject.toml](../../../pyproject.toml) 替换为：

```toml
[project]
name = "baby-feeding-mcp"
version = "1.0.0"
description = "宝宝抚养记录 MCP Server - 接入小智AI"
readme = "README.md"
requires-python = ">=3.11,<3.13"
dependencies = [
    "mcp2xiaozhi>=0.2.0",
    "requests>=2.28.0",
    "python-dotenv>=1.0.0",
]

[tool.uv]
package = false
```

（`package=false`：本仓库是应用而非可安装库，uv 只装依赖不构建 server.py；无需 `[build-system]`，也避免旧的 `packages=["."]` 产出损坏 wheel。）

- [ ] **Step 2: 重写 `mcp_config.json`**

把整个 [mcp_config.json](../../../mcp_config.json) 替换为：

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

（删除 `env` 块：`${BABY_TOKEN}` 等字面量从不会被展开，反而覆盖 env_file 注入的真值。容器内 BABY_* 由 compose env_file 提供，stdio 子进程继承 os.environ。）

- [ ] **Step 3: 重写 `.env.example`**

把整个 [.env.example](../../../.env.example) 替换为：

```env
# 小智AI MCP接入点
MCP_ENDPOINT=wss://api.xiaozhi.me/mcp/?token=YOUR_TOKEN_HERE

# 宝宝抚养记录API配置（美柚）—— 含空格的值务必加引号
BABY_TOKEN="XDS your_token_here"
BABY_ID=123456789
COMMON_BABY_ID=987654321
BABY_BIRTHDAY=2025-08-20
BABY_GENDER=1

# 每日变化建议 API（美柚 linggan）—— 历史 server.py 硬编码值已迁移至此
# 留空则 get_daily_change 的 linggan 凭据为空（不影响其它工具）
LINGGAN_ACCESS_TOKEN=
LINGGAN_ACCESS_INFO=

# 容器时区与日志级别（docker-compose.yml 已默认 Asia/Shanghai / INFO）
TZ=Asia/Shanghai
LOG_LEVEL=INFO
```

- [ ] **Step 4: 删除旧文件**

Run:
```bash
cd /home/hajimi/Projects/baby-feeding-mcp
git rm mcp_pipe.py start.sh requirements.txt
```
Expected: 三个文件标记为 deleted。

- [ ] **Step 5: 用 uv 重新生成 lock 并本地验证依赖可装**

Run:
```bash
cd /home/hajimi/Projects/baby-feeding-mcp
rm -rf .venv
uv lock
uv sync --no-dev
```
Expected: `uv lock` 更新 `uv.lock`（含 `mcp2xiaozhi`、`mcp`、`websockets`、`requests`、`python-dotenv` 等）；`uv sync` 成功创建 `.venv/` 且无报错。

- [ ] **Step 6: 验证 mcp2xiaozhi CLI 可用 + server.py 可导入**

Run:
```bash
.venv/bin/mcp2xiaozhi version
.venv/bin/python -c "import server; print('IMPORT_OK')"
```
Expected: 第一行打印 mcp2xiaozhi 版本号；第二行 `IMPORT_OK`。

- [ ] **Step 7: 提交**

```bash
git add pyproject.toml mcp_config.json .env.example uv.lock
git commit -m "$(cat <<'EOF'
chore(config): converge on pyproject+uv.lock, drop mcp_pipe/start.sh/requirements

- pyproject.toml: deps = mcp2xiaozhi/requests/python-dotenv, package=false,
  requires-python >=3.11,<3.13; remove broken hatch wheel target.
- mcp_config.json: drop unsubstituted ${VAR} env block (clobbered real env);
  point at container path /app/server.py.
- .env.example: quote BABY_TOKEN, add LINGGAN_*/TZ/LOG_LEVEL.
- Regenerate uv.lock.
- Delete mcp_pipe.py (replaced by mcp2xiaozhi), start.sh, requirements.txt.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Docker 构建产物

**Files:**
- Create: `Dockerfile`, `docker-compose.yml`, `.dockerignore`

**Interfaces:**
- Produces: `docker compose build` 产出镜像 `baby-feeding-mcp:latest`；`docker compose up` 以 mcp2xiaozhi 为入口。

- [ ] **Step 1: 创建 `.dockerignore`**

新建 [.dockerignore](../../../.dockerignore)：

```
# 密钥绝不进镜像层
.env
.env.*

# VCS 与虚拟环境
.git/
.venv/
venv/
__pycache__/
*.pyc
*.pyo

# Claude / IDE / 文档（运行时不需要）
.claude/
CLAUDE.md
docs/

# 旧文件（已删，保险）
mcp_pipe.py
start.sh
requirements.txt
```

- [ ] **Step 2: 创建 `Dockerfile`**

新建 [Dockerfile](../../../Dockerfile)：

```dockerfile
# syntax=docker/dockerfile:1
# baby-feeding-mcp —— 由 mcp2xiaozhi 桥接 server.py 到小智AI
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

# 再拷业务代码
COPY server.py mcp_config.json ./

# mcp2xiaozhi 作桥接，按 mcp_config.json 拉起所有启用的 server
CMD ["mcp2xiaozhi", "run", "--all"]
```

- [ ] **Step 3: 创建 `docker-compose.yml`**

新建 [docker-compose.yml](../../../docker-compose.yml)：

```yaml
# baby-feeding-mcp —— 持久化桥接服务
# 1. cp .env.example .env 并填入 MCP_ENDPOINT / BABY_* / LINGGAN_*
# 2. docker compose up -d --build
services:
  baby-feeding-mcp:
    build: .
    image: baby-feeding-mcp:latest
    container_name: baby-feeding-mcp
    restart: unless-stopped
    init: true                # tini 作 PID1：转发 SIGTERM、回收僵尸子进程
    env_file: .env
    environment:
      TZ: Asia/Shanghai       # 双保险（Dockerfile 已设）
    volumes:
      - ./mcp_config.json:/app/mcp_config.json:ro
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

- [ ] **Step 4: 构建镜像验证**

Run:
```bash
cd /home/hajimi/Projects/baby-feeding-mcp
docker compose build
```
Expected: 构建成功，末尾出现 `Successfully tagged baby-feeding-mcp:latest`（或 buildkit 等价的 `naming to ... baby-feeding-mcp:latest done`）。若 pip/uv 拉包失败，确认清华源可达；若 apt 失败，确认 sed 替换生效（`docker build` 中加 `--progress=plain` 排查）。

- [ ] **Step 5: 验证镜像内时区与入口**

Run:
```bash
docker compose run --rm --no-deps baby-feeding-mcp sh -c 'date && echo "---" && which mcp2xiaozhi && mcp2xiaozhi version'
```
Expected: `date` 输出 `CST`（或 `+0800`）时区；`which mcp2xiaozhi` 为 `/app/.venv/bin/mcp2xiaozhi`；版本号正常打印。

- [ ] **Step 6: 提交**

```bash
git add Dockerfile docker-compose.yml .dockerignore
git commit -m "$(cat <<'EOF'
feat(docker): add Dockerfile + compose using mcp2xiaozhi, 国内镜像源

- Dockerfile: python:3.12-slim, apt+pip 走清华源, 装 tzdata 设 Asia/Shanghai,
  uv sync --frozen from uv.lock, entrypoint mcp2xiaozhi run --all.
- docker-compose: init:true (tini PID1), env_file, mcp_config.json ro mount,
  restart unless-stopped, log rotation.
- .dockerignore: exclude .env/.git/.venv/docs to keep secrets out of layers.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: README 重写

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 替换「安装」与「运行」段（去掉 systemd / uv pip install -r）**

把 [README.md](../../../README.md) 的「## 安装」到「## 工具参数详解」之前的全部内容（即「安装」「配置」「运行」三段，约 21-107 行）替换为：

````markdown
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

````

- [ ] **Step 2: 更新「目录结构」段**

把 [README.md:204-217](../../../README.md#L204-L217) 的目录结构块替换为：

```markdown
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
```

- [ ] **Step 3: 更新「注意事项」中的过时描述**

把 [README.md:223](../../../README.md#L223) 这一行：

```markdown
3. **自动重连**：`mcp_pipe.py` 内置自动重连机制，断线后会指数退避重试
```

替换为：

```markdown
3. **自动重连**：`mcp2xiaozhi` 内置抖动指数退避重连，断线自动恢复
```

- [ ] **Step 4: 提交**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs(readme): replace systemd with docker compose, add mirror guide

- Replace install/config/run sections with docker compose quickstart.
- Add local-dev (uv) and 国内镜像加速 (daemon registry-mirrors) sections.
- Update directory structure and reconnect-note for mcp2xiaozhi.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: 集成冒烟测试（真实小智 token）

**Files:**
- 本地创建 `.env`（**不提交**，已被 .gitignore 排除）

**Interfaces:**
- 消费：用户提供的小智测试 wss token（仅放本地 .env）。

- [ ] **Step 1: 创建本地 `.env`（含测试 token）**

Run:
```bash
cd /home/hajimi/Projects/baby-feeding-mcp
cp .env.example .env
```
然后用编辑器把 `.env` 里的 `MCP_ENDPOINT` 改为用户提供的测试 token：

```env
MCP_ENDPOINT=wss://api.xiaozhi.me/mcp/?token=eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VySWQiOjQxODA5OSwiYWdlbnRJZCI6MTQ5NjM1NSwiZW5kcG9pbnRJZCI6ImFnZW50XzE0OTYzNTUiLCJwdXJwb3NlIjoibWNwLWVuZHBvaW50IiwiaWF0IjoxNzg0NTE1Njc2LCJleHAiOjE4MTYwNzMyNzZ9.YBc5_dx7FxDV2tcBhg1EsIDe5Wx4HC5ktjPk0W9ymzsRLA292imSQ6LUVSD45QwQeWbWkCWE4D7qLusqAOuwNQ
```
并填入真实 `BABY_TOKEN`/`BABY_ID`/`COMMON_BABY_ID`/`BABY_BIRTHDAY`/`LINGGAN_*`。

确认 `.env` 不在 git 暂存区：
```bash
git status --porcelain .env
```
Expected: 无输出（.env 被 .gitignore 忽略）。

- [ ] **Step 2: 启动容器**

Run:
```bash
docker compose up -d --build
docker compose logs -f --tail=50
```
Expected: 日志出现 `Successfully connected to WebSocket server` 与 `Starting servers: baby-feeding`；**无** `${BABY_TOKEN}` 字面量、**无** `int()` 或 `ValueError` 异常、**无** `配置验证通过` 之后的崩溃。

- [ ] **Step 3: 功能验证（通过小智触发）**

用绑定的的小智设备/语音触发：
1. 「记录喝奶 180 毫升」→ 美柚 App 侧出现一条配方奶记录，**时间戳为本地时间**（验证 TZ=Asia/Shanghai 生效，非 UTC）。
2. 「宝宝多大」→ 返回月龄合理（如「11 个月」而非「12 个月」，验证日历算法修复）。
3. 「最近一次喝奶是什么时候」→ 返回正确记录与「X 分钟前」。

若任一失败，看 `docker compose logs` 排查；常见：`LINGGAN_*` 未填（仅影响 get_daily_change）、`BABY_TOKEN` 引号缺失。

- [ ] **Step 4: 信号/退出验证**

Run:
```bash
docker compose stop
docker compose ps
```
Expected: `stop` 在 ~10s 内完成（SIGTERM 经 tini 转发，mcp2xiaozhi 优雅关闭子进程）；`ps` 显示容器已退出、无残留。

- [ ] **Step 5: 清理（可选）**

Run:
```bash
docker compose down
```

（本任务无 git 提交 —— `.env` 不提交。）

---

## Task 7: 抹除 git 历史中的硬编码 token

**⚠️ 破坏性操作：** 会改写所有 commit hash，需 force-push；其它克隆需重新同步。**执行前向用户再次确认。建议先把 `feat/docker-compose-migration` 合并到 `main` 再做。**

**Files:**
- 重写 git 历史（所有 commit）。

- [ ] **Step 0: 前置确认（不可跳过）**

向用户确认：
1. Task 1-6 已完成并通过冒烟测试。
2. `feat/docker-compose-migration` 已合并到 `main`（或同意在此分支重写后再合）。
3. 同意 force-push、且知晓其它克隆需 `git reset --hard origin/main`。
4. 当前 token 值已记录到本地 `.env`（重写后历史里不再有）。

- [ ] **Step 1: 安装 git-filter-repo**

Run:
```bash
pip install --no-cache-dir git-filter-repo
which git-filter-repo && git filter-repo --version
```
Expected: 打印版本号。若无，回退用 `git filter-branch`（见 Step 3 备注）。

- [ ] **Step 2: 写替换规则**

Run:
```bash
cat > /tmp/baby-token-replacements.txt <<'EOF'
***REMOVED***==>***REMOVED***
***REMOVED***==>***REMOVED***
EOF
cat /tmp/baby-token-replacements.txt
```
Expected: 文件含两行 `旧值==>***REMOVED***`。

- [ ] **Step 3: 重写历史**

Run（在仓库根、当前分支为 main 或目标分支）：
```bash
cd /home/hajimi/Projects/baby-feeding-mcp
git filter-repo --replace-text /tmp/baby-token-replacements.txt --force
```
Expected: filter-repo 报告已重写若干 commit、替换若干处。注意：filter-repo 会移除 `origin` remote。

备注（filter-repo 不可用时的回退，较慢）：
```bash
git filter-branch --force --tree-filter "
  git grep -l '***REMOVED***' 2>/dev/null | xargs -r sed -i 's/***REMOVED***/***REMOVED***/g';
  git grep -l '***REMOVED***' 2>/dev/null | xargs -r sed -i 's|***REMOVED***|***REMOVED***|g'
" --prune-empty --tag-name-filter cat -- --all
```

- [ ] **Step 4: 验证历史中已无 token**

Run:
```bash
git log --all -S '***REMOVED***' --oneline
git log --all -S '***REMOVED***' --oneline
```
Expected: 两条命令均**无输出**（历史已干净）。若有输出，回到 Step 3 检查替换串拼写。

- [ ] **Step 5: 重新挂 remote 并 force-push（用户确认后）**

Run:
```bash
git remote add origin https://github.com/StanleyChanH/baby-feeding-mcp.git
git push origin --force --all
git push origin --force --tags
```
Expected: 所有分支与标签 force-push 成功。

- [ ] **Step 6: 清理本地替换文件**

Run:
```bash
rm -f /tmp/baby-token-replacements.txt
rm -rf .git/filter-repo
```

（本任务不产生新的业务提交 —— 它改写既有历史。）

---

## Self-Review（已执行）

**1. Spec 覆盖：**
- §2 架构（mcp2xiaozhi 替换）→ Task 3（删 mcp_pipe）+ Task 4（Dockerfile CMD）✓
- §3 文件变更 新增 Dockerfile/compose/.dockerignore → Task 4 ✓；修改 server.py → Task 1-2 ✓；mcp_config → Task 3 ✓；pyproject → Task 3 ✓；.env.example → Task 3 ✓；README → Task 5 ✓；删除三文件 → Task 3 ✓
- §4 server.py bug 表：logging(Session 1)✓ timeout(Session 1)✓ age math(Session 2)✓ record_bath(Session 2)✓ get_last_record 校验(Session 2)✓ _get_times(Session 2)✓ get_recorder 单例(Session 1)✓ BABY_GENDER(Session 1)✓ get_recent_records size(Session 2)✓ get_baby_info 复用(Session 2)✓ birthday_ms(Session 1)✓ linggan→env(Session 1)✓
- §5 国内镜像源 → Task 4 Dockerfile ✓
- §6 git 历史重写 → Task 7 ✓
- §7 验证 → Task 6 ✓

**2. 占位符扫描：** 无 TBD/TODO；每步含完整代码或确切命令 + 预期输出。

**3. 类型/命名一致性：** `_age_components` 在 Task 2 Step1 定义、Step2/Step3 消费，签名一致 `(birthday, today) -> (years, months, days, total_days)`；`get_daily_change` Task 1 Step6 去掉 `birthday_str` 参数、Step7 工具不再传参；`CN_TZ`/`REQUEST_TIMEOUT` Task 1 Step1 定义、后续步骤使用一致。

**Spec 偏离修正：** spec §4 备注曾写 birthday_ms「修为 UTC」。计划改为 `Asia/Shanghai` 显式时区——美柚是中国服务，UTC 会把生日 midnight 误判；东八区才匹配 App 期望。已在 Task 1 Step2 注释说明。

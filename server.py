# Baby Feeding Record MCP Server
# 宝宝抚养记录 MCP 服务器

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

# 创建 MCP 服务器
mcp = FastMCP("BabyFeedingRecord")


class BabyRecorder:
    """宝宝抚养记录API客户端"""

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
            "authorization": token,
            "ua": "com.lingan.seeyou/9.02.1.0 MeetYouClient/2.0.0 (0130902001200000) MYAPPINFO(01-3-9.02.1.0-0012-0)",
            "source": "FamilyFullScreenHomeFragment:SeeyouActivity->HerSleepHomeActivity",
            "Content-Type": "application/json"
        }
        # 连接池复用，避免每次请求重新 TCP+TLS 握手
        self.session = requests.Session()

    def _get_times(self, start_at=None, end_at=None, duration_minutes=10):
        """智能时间计算"""
        fmt = "%Y-%m-%d %H:%M:%S"

        if start_at:
            try:
                start_dt = datetime.strptime(start_at, fmt)
            except ValueError:
                start_dt = datetime.now()
        else:
            start_dt = datetime.now()

        if end_at:
            end_str = end_at
        else:
            end_dt = start_dt + timedelta(minutes=duration_minutes)
            end_str = end_dt.strftime(fmt)

        start_str = start_dt.strftime(fmt)
        return start_str, end_str

    def _post_request(self, payload, log_msg):
        """通用发送请求"""
        try:
            response = self.session.post(
                self.url, headers=self.headers, data=json.dumps(payload), timeout=REQUEST_TIMEOUT
            )
            if response.status_code == 200:
                res = response.json()
                if res.get("code") == 0:
                    logger.info(f"成功: {log_msg}")
                    return {"success": True, "message": log_msg, "data": res}
                else:
                    logger.error(f"业务失败: {res.get('message')}")
                    return {"success": False, "message": res.get('message', '未知错误')}
            else:
                logger.error(f"HTTP错误: {response.status_code}")
                return {"success": False, "message": f"HTTP错误: {response.status_code}"}
        except Exception as e:
            logger.error(f"网络异常: {e}")
            return {"success": False, "message": f"网络异常: {str(e)}"}

    def record_formula_milk(self, capacity_ml, start_at=None, end_at=None, remark=""):
        """记录配方奶"""
        s_time, e_time = self._get_times(start_at, end_at, duration_minutes=10)

        payload = {
            "baby_id": self.baby_id,
            "client_rid": 9,
            "common_baby_id": self.common_baby_id,
            "end_at": e_time,
            "draft_id": 0,
            "from": 0,
            "record_category": 13,
            "record_detail": {
                "bottle_feed_capacity": capacity_ml,
                "photos": []
            },
            "record_type": 1,
            "remark": remark,
            "start_at": s_time,
            "time_state": 0,
            "type": 0,
            "updateTips": False
        }
        return self._post_request(payload, f"配方奶 {capacity_ml}ml | 开始: {s_time}")

    def record_diaper(self, category_type="pee", start_at=None, remark="",
                      red_buttock=False, shit_color=0, shit_shape=0):
        """记录换尿布"""
        s_time, _ = self._get_times(start_at)
        cat_map = {"pee": 41, "poo": 42, "both": 43}

        payload = {
            "baby_id": self.baby_id,
            "birthday": self.birthday_ms,
            "client_rid": 12,
            "common_baby_id": self.common_baby_id,
            "draft_id": 0,
            "from": 0,
            "record_category": cat_map.get(category_type, 41),
            "record_detail": {
                "red_buttock": red_buttock,
                "shit_color": shit_color,
                "shit_photo": [],
                "shit_shape": shit_shape
            },
            "record_type": 4,
            "remark": remark,
            "start_at": s_time,
            "time_state": 0,
            "type": 0,
            "updateTips": False
        }

        cn_map = {"pee": "尿尿", "poo": "拉屎", "both": "又尿又拉"}
        desc = cn_map.get(category_type, "未知")
        status = "红屁屁" if red_buttock else "正常"

        return self._post_request(payload, f"换尿布-{desc} ({status}) | 时间: {s_time}")

    def record_bath(self, start_at=None, end_at=None, remark=""):
        """记录洗澡"""
        s_time, e_time = self._get_times(start_at, end_at, duration_minutes=15)

        payload = {
            "client_rid": 17,
            "common_baby_id": self.common_baby_id,
            "draft_id": 0,
            "end_at": e_time,
            "from": 0,
            "record_category": 0,
            "record_detail": {"time_source": 2},
            "record_type": 5,
            "remark": remark,
            "start_at": s_time,
            "time_state": 0,
            "type": 0,
            "updateTips": False
        }
        return self._post_request(payload, f"洗澡 | 开始: {s_time}")

    def record_food(self, food_name, quantity_g, start_at=None, remark=""):
        """记录辅食"""
        s_time, _ = self._get_times(start_at)

        payload = {
            "baby_id": self.baby_id,
            "birthday": self.birthday_ms,
            "client_rid": 27,
            "common_baby_id": self.common_baby_id,
            "draft_id": 0,
            "from": 0,
            "quantity": quantity_g,
            "record_category": 0,
            "record_detail": {
                "allergic_ingredient_id": 0,
                "allergic_reaction": [],
                "food_name": food_name,
                "photos": []
            },
            "record_type": 3,
            "remark": remark,
            "start_at": s_time,
            "time_state": 0,
            "type": 0,
            "uni": "3_0",
            "updateTips": False
        }
        return self._post_request(payload, f"辅食-{food_name} {quantity_g}g | 时间: {s_time}")

    def record_water(self, capacity_ml, start_at=None, remark=""):
        """记录喝水"""
        s_time, e_time = self._get_times(start_at, None, duration_minutes=5)

        payload = {
            "baby_id": self.baby_id,
            "client_rid": 9,
            "common_baby_id": self.common_baby_id,
            "draft_id": 0,
            "from": 0,
            "record_category": 0,
            "record_detail": {
                "photos": [],
                "water_capacity": capacity_ml
            },
            "record_type": 10,
            "remark": remark,
            "start_at": s_time,
            "time_state": 0,
            "type": 0,
            "updateTips": False
        }
        return self._post_request(payload, f"喝水 {capacity_ml}ml | 时间: {s_time}")

    def get_records(self, size=50):
        """获取历史记录列表"""
        list_url = "https://api-bbj.meiyou.com/v3/life/record/list"
        now_str = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")

        headers = {
            **self.headers,
            "mode": "10",
            "user-agent": self.headers["ua"]
        }
        del headers["Content-Type"]

        params = {
            "client_rid": "2",
            "client_rtime": now_str,
            "size": size,
            "common_baby_id": self.common_baby_id
        }

        try:
            response = self.session.get(list_url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
            if response.status_code == 200:
                res = response.json()
                if res.get("code") == 0:
                    logger.info(f"获取历史记录成功")
                    return {"success": True, "data": res.get("data", {})}
                else:
                    return {"success": False, "message": res.get('message', '未知错误')}
            else:
                return {"success": False, "message": f"HTTP错误: {response.status_code}"}
        except Exception as e:
            logger.error(f"获取历史记录异常: {e}")
            return {"success": False, "message": f"网络异常: {str(e)}"}

    def get_last_record(self, record_type=None):
        """获取最近一次记录，可按类型筛选

        record_type: 1=配方奶, 3=辅食, 4=换尿布, 5=洗澡, 10=喝水
        """
        result = self.get_records(size=50)
        if not result.get("success"):
            return result

        all_records = []
        data = result.get("data", {})
        for day_item in data.get("list", []):
            all_records.extend(day_item.get("records", []))

        # 按类型筛选
        if record_type:
            all_records = [r for r in all_records if r.get("record_type") == record_type]

        if not all_records:
            return {"success": False, "message": "没有找到相关记录"}

        # 按时间排序，获取最近的
        all_records.sort(key=lambda x: x.get("start_at", ""), reverse=True)
        last_record = all_records[0]

        # 计算距离现在多久
        start_at = last_record.get("start_at", "")
        if start_at:
            try:
                record_time = datetime.strptime(start_at, "%Y-%m-%d %H:%M:%S")
                now = datetime.now()
                delta = now - record_time

                total_seconds = int(delta.total_seconds())
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60

                if hours > 0:
                    time_ago = f"{hours}小时{minutes}分钟前"
                else:
                    time_ago = f"{minutes}分钟前"

                last_record["time_ago"] = time_ago
                last_record["hours_since"] = hours + minutes / 60
            except Exception as e:
                logger.warning(f"时间计算失败: {start_at}, 错误: {e}")

        return {"success": True, "record": last_record}

    def _calc_age_params(self):
        """计算宝宝年龄参数，用于每日变化API"""
        if not self.birthday:
            return None

        today = datetime.now()
        parenting_info = (today - self.birthday).days
        parenting_year = parenting_info // 365
        remaining_days = parenting_info % 365
        month_of_year = remaining_days // 30
        day_of_month = remaining_days % 30

        return {
            "parenting_info": parenting_info,
            "parenting_year": parenting_year,
            "month_of_year": month_of_year,
            "day_of_month": day_of_month,
            "baby_gender": self.baby_gender
        }

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


# ============ MCP 工具定义 ============

@mcp.tool()
def record_formula_milk(capacity_ml: int = 180, start_at: str = "", remark: str = "") -> dict:
    """
    记录宝宝喝配方奶。当用户说要记录宝宝喝奶、喂奶、吃奶粉时使用此工具。

    参数:
        capacity_ml: 奶量，单位毫升，默认180ml
        start_at: 开始时间，格式 "YYYY-MM-DD HH:MM:SS"，为空表示现在
        remark: 备注，可选
    """
    try:
        recorder = get_recorder()
        result = recorder.record_formula_milk(
            capacity_ml=capacity_ml,
            start_at=start_at if start_at else None,
            remark=remark
        )
        return result
    except Exception as e:
        return {"success": False, "message": str(e)}


@mcp.tool()
def record_diaper(category_type: str, start_at: str = "", red_buttock: bool = False, remark: str = "") -> dict:
    """
    记录宝宝换尿布。当用户说要记录换尿布、拉屎、尿尿时使用此工具。

    参数:
        category_type: 类型，必须是 "pee"(尿尿)、"poo"(拉屎) 或 "both"(都有)
        start_at: 时间，格式 "YYYY-MM-DD HH:MM:SS"，为空表示现在
        red_buttock: 是否红屁屁，默认False
        remark: 备注，可选
    """
    try:
        recorder = get_recorder()
        result = recorder.record_diaper(
            category_type=category_type,
            start_at=start_at if start_at else None,
            red_buttock=red_buttock,
            remark=remark
        )
        return result
    except Exception as e:
        return {"success": False, "message": str(e)}


@mcp.tool()
def record_bath(start_at: str = "", end_at: str = "", remark: str = "") -> dict:
    """
    记录宝宝洗澡。当用户说要记录宝宝洗澡时使用此工具。

    参数:
        start_at: 开始时间，格式 "YYYY-MM-DD HH:MM:SS"，为空表示现在
        end_at: 结束时间，格式 "YYYY-MM-DD HH:MM:SS"，为空表示默认15分钟后
        remark: 备注，可选
    """
    try:
        recorder = get_recorder()
        result = recorder.record_bath(
            start_at=start_at if start_at else None,
            end_at=end_at if end_at else None,
            remark=remark
        )
        return result
    except Exception as e:
        return {"success": False, "message": str(e)}


@mcp.tool()
def record_food(food_name: str, quantity_g: int, start_at: str = "", remark: str = "") -> dict:
    """
    记录宝宝吃辅食。当用户说要记录宝宝吃辅食、吃米粉、吃果泥等时使用此工具。

    参数:
        food_name: 食物名称，例如 "强化铁米粉"、"西兰花泥"
        quantity_g: 数量，单位克
        start_at: 时间，格式 "YYYY-MM-DD HH:MM:SS"，为空表示现在
        remark: 备注，可选
    """
    try:
        recorder = get_recorder()
        result = recorder.record_food(
            food_name=food_name,
            quantity_g=quantity_g,
            start_at=start_at if start_at else None,
            remark=remark
        )
        return result
    except Exception as e:
        return {"success": False, "message": str(e)}


@mcp.tool()
def record_water(capacity_ml: int = 30, start_at: str = "", remark: str = "") -> dict:
    """
    记录宝宝喝水。当用户说要记录宝宝喝水、喂水时使用此工具。

    参数:
        capacity_ml: 喝水量，单位毫升，默认30ml
        start_at: 开始时间，格式 "YYYY-MM-DD HH:MM:SS"，为空表示现在
        remark: 备注，可选
    """
    try:
        recorder = get_recorder()
        result = recorder.record_water(
            capacity_ml=capacity_ml,
            start_at=start_at if start_at else None,
            remark=remark
        )
        return result
    except Exception as e:
        return {"success": False, "message": str(e)}


@mcp.tool()
def get_last_record(record_type: str = "") -> dict:
    """
    获取最近一次抚养记录。当用户问"最近一次喂奶是什么时候"、"上次换尿布多久了"等问题时使用此工具。

    参数:
        record_type: 记录类型，可选值：
            - "formula_milk" 或 "喝奶" 或 "喂奶" - 配方奶
            - "diaper" 或 "换尿布" 或 "拉屎" 或 "尿尿" - 换尿布
            - "bath" 或 "洗澡" - 洗澡
            - "food" 或 "辅食" - 辅食
            - "water" 或 "喝水" - 喝水
            - 空字符串 - 获取所有类型的最近一条记录
    """
    try:
        recorder = get_recorder()

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

        if result.get("success"):
            record = result.get("record", {})
            return {
                "success": True,
                "record_type_name": record.get("record_type_name", ""),
                "record_content": record.get("record_content", ""),
                "start_at": record.get("start_at", ""),
                "time_ago": record.get("time_ago", ""),
                "remark": record.get("remark", "")
            }
        return result
    except Exception as e:
        return {"success": False, "message": str(e)}


@mcp.tool()
def get_recent_records(size: int = 20) -> dict:
    """
    获取最近的抚养记录列表。当用户问"今天喂了几次奶"、"最近有什么记录"等问题时使用此工具。

    参数:
        size: 获取的记录数量，默认20条
    """
    try:
        recorder = get_recorder()
        result = recorder.get_records(size=size)

        if result.get("success"):
            data = result.get("data", {})
            records_summary = []

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
        return result
    except Exception as e:
        return {"success": False, "message": str(e)}


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


@mcp.tool()
def get_baby_info() -> dict:
    """
    获取宝宝基本信息。当用户问"宝宝多大"、"宝宝生日是什么时候"、"宝宝是男是女"等问题时使用此工具。

    返回宝宝生日、性别、年龄等信息。
    """
    try:
        birthday = os.getenv("BABY_BIRTHDAY")
        baby_gender = int(os.getenv("BABY_GENDER") or "1")

        if not birthday:
            return {"success": False, "message": "未配置宝宝生日"}

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

        return {
            "success": True,
            "birthday": birthday,
            "gender": "男孩" if baby_gender == 1 else "女孩",
            "gender_code": baby_gender,
            "age_days": days,
            "age_str": age_str
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


def validate_config():
    """启动时验证必要的环境变量配置"""
    required = ["BABY_TOKEN", "BABY_ID", "COMMON_BABY_ID", "BABY_BIRTHDAY"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise ValueError(f"缺少环境变量: {', '.join(missing)}")
    logger.info("配置验证通过")


# 启动服务器
if __name__ == "__main__":
    validate_config()
    mcp.run(transport="stdio")

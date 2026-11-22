"""
V2Board 自动签到脚本
基于 Burp Suite 抓包分析，模拟登录并签到
"""

import json
import logging
import re
import time
from html import unescape
from pathlib import Path

import requests

from headers import RequestContext, build_headers

# ============ 配置区 ============
CONFIG_FILE = Path(__file__).with_name("config.json")


def load_config() -> tuple[str, str, str]:
    """读取并校验脚本配置，返回 email、password、base_url。"""
    try:
        config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise RuntimeError(f"配置文件不存在: {CONFIG_FILE}") from e
    except json.JSONDecodeError as e:
        raise RuntimeError(f"配置文件 JSON 格式无效: {CONFIG_FILE}") from e
    except OSError as e:
        raise RuntimeError(f"无法读取配置文件 {CONFIG_FILE}: {e}") from e

    if not isinstance(config, dict):
        raise RuntimeError(f"配置文件必须是 JSON 对象: {CONFIG_FILE}")

    account = config.get("v2Board")
    if not isinstance(account, dict):
        raise RuntimeError(f"配置文件中的 v2Board 必须是 JSON 对象: {CONFIG_FILE}")

    email = account.get("email")
    password = account.get("password")
    base_url = account.get("BASE_URL")
    if not isinstance(email, str) or not email.strip():
        raise RuntimeError(f"配置文件中的 email 必须是非空字符串: {CONFIG_FILE}")
    if not isinstance(password, str) or not password:
        raise RuntimeError(f"配置文件中的 password 必须是非空字符串: {CONFIG_FILE}")
    if not isinstance(base_url, str) or not base_url.strip():
        raise RuntimeError(f"配置文件中的 BASE_URL 必须是非空字符串: {CONFIG_FILE}")

    base_url = base_url.rstrip("/")
    return email.strip(), password, base_url


EMAIL, PASSWORD, BASE_URL = load_config()

# 三套请求头：由 headers.build_headers 按请求类型生成
LOGIN_HEADERS = build_headers(
    "xhr_post",
    RequestContext(BASE_URL, "/auth/login"),
    body="form",
)
CHECKIN_HEADERS = build_headers(
    "xhr_post",
    RequestContext(BASE_URL, "/user"),
    body="none",
)
USER_PAGE_HEADERS = build_headers(
    "navigation",
    RequestContext(BASE_URL, "/auth/login"),
)

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_json_response(resp: requests.Response) -> dict:
    """从响应中提取 JSON（处理 Content-Type 为 text/html 或有 BOM/乱码前缀的情况）"""
    text = resp.content.decode("utf-8", errors="ignore")
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character == "{":
            try:
                result, _ = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(result, dict):
                return result
    raise ValueError(f"No JSON object found in response: {text[:200]}")


def log_remaining_traffic(result: dict) -> None:
    """记录签到响应中的剩余流量。"""
    traffic_info = result.get("trafficInfo")
    if isinstance(traffic_info, dict):
        remaining = traffic_info.get("unUsedTraffic")
        if remaining is not None:
            logger.info("剩余流量: %s", remaining)


def login(session: requests.Session) -> bool:
    """登录并获取会话 cookie。"""
    url = f"{BASE_URL}/auth/login"
    data = {
        "agree": "1",
        "email": EMAIL,
        "passwd": PASSWORD,
        "code": "",
    }

    logger.info(f"正在登录: {EMAIL}")
    try:
        resp = session.post(url, headers=LOGIN_HEADERS, data=data, timeout=15)
        resp.raise_for_status()
        result = parse_json_response(resp)

        if result.get("ret") == 1:
            logger.info(f"登录成功: {result.get('msg', '')}")
            return True
        logger.error(f"登录失败: {result.get('msg', '未知错误')}")
        return False
    except requests.RequestException as e:
        logger.error(f"登录请求异常: {e}")
        return False
    except ValueError as e:
        logger.error(f"登录响应解析失败: {resp.text[:200]}, 错误: {e}")
        return False


def get_user_page(session: requests.Session) -> str:
    """获取用户页面 HTML。"""
    response = session.get(
        f"{BASE_URL}/user", headers=USER_PAGE_HEADERS, timeout=15
    )
    response.raise_for_status()
    return response.content.decode("utf-8", errors="ignore")


def check_checkin_status(session: requests.Session) -> bool:
    """根据用户页面上的签到按钮判断今日签到状态。"""
    logger.info("正在检查签到状态...")
    try:
        text = get_user_page(session)
    except requests.RequestException as e:
        logger.warning(f"检查签到状态失败: {e}，默认执行签到")
        return False

    match = re.search(
        r'<a\s+class="([^"]*)"[^>]*href="#">[^<]*<span[^>]*>check</span>',
        text,
    )
    if not match:
        logger.warning("无法解析签到按钮状态，默认执行签到")
        return False

    return "disabled" in match.group(1)


def checkin(session: requests.Session, max_retries: int = 2) -> bool:
    """执行签到，带重试机制"""
    url = f"{BASE_URL}/user/checkin"

    for attempt in range(max_retries):
        logger.info(f"正在签到... (尝试 {attempt + 1}/{max_retries})")
        try:
            resp = session.post(url, headers=CHECKIN_HEADERS, timeout=15)
            resp.raise_for_status()
            result = parse_json_response(resp)

            logger.info(f"签到响应: {result}")
            log_remaining_traffic(result)

            ret_code = result.get("ret")
            msg = result.get("msg", "未知错误")

            if ret_code == 1:
                logger.info(f"签到成功: {msg}")
                return True
            if ret_code != 0:
                logger.error(f"签到返回未知状态码 {ret_code}: {msg}")
                return False

            lower_msg = msg.lower()
            if "已签到" in msg or "already" in lower_msg or "重复" in msg:
                logger.info(f"今日已签到: {msg}")
                return True

            if "频繁" not in msg and "稍后" not in msg and "freq" not in lower_msg:
                logger.error(f"签到失败: {msg}")
                return False

            if attempt == max_retries - 1:
                logger.error(f"多次重试后仍然频繁: {msg}")
                return False

            wait_time = 5 * (attempt + 1)
            logger.warning(f"操作过于频繁，等待 {wait_time} 秒后重试...")
            time.sleep(wait_time)
        except requests.RequestException as e:
            logger.error(f"签到请求异常: {e}")
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            return False
        except ValueError as e:
            logger.error(f"签到响应解析失败: {resp.text[:200]}, 错误: {e}")
            return False

    return False


def get_user_info(session: requests.Session) -> None:
    """从用户页面读取并记录剩余流量。"""
    try:
        text = get_user_page(session)
    except requests.RequestException as e:
        logger.error("获取剩余流量失败: %s", e)
        return

    match = re.search(
        r"<[^>]+\bid=[\"']remain[\"'][^>]*>(.*?)</[^>]+>",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        logger.warning("用户页面中未找到剩余流量信息")
        return

    remaining = unescape(re.sub(r"<[^>]*>", "", match.group(1))).strip()
    if remaining:
        logger.info("剩余流量: %s", remaining)
    else:
        logger.warning("用户页面中的剩余流量为空")


def main():
    logger.info("=" * 40)
    logger.info("V2Board 自动签到开始")
    logger.info("=" * 40)

    session = requests.Session()

    if not login(session):
        logger.error("登录失败，退出")
        return

    time.sleep(1)
    if check_checkin_status(session):
        logger.info("今日已完成签到，无需重复操作")
        success = True
    else:
        time.sleep(1)
        success = checkin(session)

    get_user_info(session)
    if success:
        logger.info("签到流程完成 ✓")
    else:
        logger.warning("签到可能未成功，请检查日志")
    logger.info("=" * 40)


if __name__ == "__main__":
    main()
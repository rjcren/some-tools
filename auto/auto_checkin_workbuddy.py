#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy 每日自动签到领积分 —— Python 脚本

原理
----
WorkBuddy 积分页上的「签到」按钮是历史残留入口（已禁用），真正的签到走接口。
本脚本加载你自己在浏览器里的登录态（storageState），在已登录页面内 fetch
调用官方公开接口完成签到。

  * 不解密本机凭证、不上传任何数据、只读取你自己的登录态
  * 幂等：先查状态，今天已签就跳过，重复运行不会多领
  * 脱敏：日志里不打印真实 token
  * 复核：领取后再查一次状态，如实汇报，绝不「假成功」

接口（唯一域名 www.codebuddy.cn，路径必须带 /v2/）
----
  查状态  POST /v2/billing/meter/checkin-activity-status
  执行签到 POST /v2/billing/meter/daily-checkin
  响应    code=0 成功；code=10001 今日已签
  注意    业务数据在 data.data（双层结构），不是 data

用法
----
  python workbuddy_checkin.py doctor     # 环境自检
  python workbuddy_checkin.py login      # 首次：打开浏览器扫码登录，保存登录态
  python workbuddy_checkin.py checkin    # 执行签到（默认命令，可省略）
  python workbuddy_checkin.py status     # 只读查询当前签到状态

零依赖备选模式（不装 playwright 也能跑）
----
  在浏览器登录 codebuddy.cn 后，按 F12 -> Network，找到任意一条
  /v2/billing/meter/... 请求，复制请求头里的 Authorization 值：
      set WORKBUDDY_TOKEN=Bearer eyJhbGci...
      python workbuddy_checkin.py checkin --direct
  X-User-Id 会自动从本机凭据文件读取（也可用 WORKBUDDY_USER_ID 覆盖）。

依赖（仅 Playwright 模式需要）
----
  pip install playwright
  playwright install chromium     # 本机已有浏览器缓存时可跳过

安全提示
----
  auth_state.json 等同于你的登录态，切勿提交 Git / 发群 / 上传网盘。
  本脚本为非官方个人自动化工具，接口可能变动，使用风险自负。
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------- 配置
BASE = "https://www.codebuddy.cn"
EP_STATUS = BASE + "/v2/billing/meter/checkin-activity-status"
EP_CHECKIN = BASE + "/v2/billing/meter/daily-checkin"
EP_RESOURCE_SUMMARY = BASE + "/billing/meter/get-user-resource-summary"
PROFILE_URL = BASE + "/profile/usage"

HERE = Path(__file__).resolve().parent
AUTH_FILE = HERE / "workBuddy_auth_state.json"          # Playwright 登录态
LOG_FILE = HERE / "checkin_workBuddy.log"

CODE_OK = 0
CODE_ALREADY = 10001

# 网络失败退避（秒）：专治「刚开机、网络还没就绪」
BACKOFF = [5, 15, 30, 60, 90]

# 在已登录页面内发请求，天然带上 cookie + localStorage
FETCH_JS = """async (u) => {
  try {
    const res = await fetch(u, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' }
    });
    const text = await res.text();
    let data = null;
    try { data = JSON.parse(text); } catch (e) {}
    return { httpStatus: res.status, data: data, raw: text.slice(0, 300) };
  } catch (e) {
    return { httpStatus: 0, data: null, raw: 'FETCH_ERROR: ' + e.message };
  }
}"""

# ---------------------------------------------------------------- 浏览器兼容
def chromium_executable():
    """
    自动探测可复用的 Chromium 可执行文件。
    Playwright 版本与已缓存内核版本不一致时，默认路径会失效；
    这里回退到本机已有的任意 chromium-* 内核，避免重新下载。
    返回 None 表示用 Playwright 默认路径。
    """
    override = os.environ.get("WB_CHROME_EXE", "").strip()
    if override:
        return override if Path(override).exists() else None
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    root = Path(local) / "ms-playwright"
    if not root.exists():
        return None
    exe = None
    for d in sorted(root.glob("chromium-*")):
        for rel in ("chrome-win/chrome.exe", "chrome-linux/chrome", "chrome-mac/Chromium.app/Contents/MacOS/Chromium"):
            cand = d / rel
            if cand.exists():
                exe = str(cand)
                break
        if exe:
            break
    return exe


def navigate_with_retry(page, url, timeout_ms=None, retries=3):
    """导航超时时重试，并允许通过环境变量放宽等待时间。"""
    if timeout_ms is None:
        try:
            timeout_ms = int(os.environ.get("WB_NAV_TIMEOUT_MS", "60000"))
        except ValueError:
            timeout_ms = 60000

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            return page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                delay = BACKOFF[attempt - 1]
                log(f"页面导航超时，第 {attempt}/{retries} 次重试（{delay}s 后）: {type(exc).__name__}")
                time.sleep(delay)
    raise last_error


# ---------------------------------------------------------------- 工具
def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def mask(s):
    """token 脱敏，只输出 eyJhbG...xxxx 形态"""
    if not s:
        return "(空)"
    s = str(s)
    if len(s) <= 12:
        return s[:2] + "***"
    return s[:6] + "..." + s[-4:]


def fmt(v, default="-"):
    # 注意：0 是有效值，不能用真值判断
    return v if isinstance(v, (int, float, str)) else default


def fmt_credits(v, default="-"):
    """格式化积分，保留最多两位小数。"""
    if isinstance(v, bool) or v is None:
        return default
    try:
        text = f"{float(v):.2f}".rstrip("0").rstrip(".")
        return text if text != "-0" else "0"
    except (TypeError, ValueError):
        return default


def get_remaining_credits(request, label):
    result = request_with_retry(request, EP_RESOURCE_SUMMARY)
    outer = result.get("data") if isinstance(result.get("data"), dict) else {}
    if result.get("httpStatus") == 200 and outer.get("code") == CODE_OK:
        data = outer.get("data")
        if isinstance(data, dict) and "TotalCredits" in data:
            return data.get("TotalCredits")
    log(f"RESOURCE_SUMMARY_FAILED [{label}]: http={result.get('httpStatus')} "
        f"code={outer.get('code')} raw={result.get('raw')}")
    return None


def read_local_uid():
    """从本机凭据文件读取 uid（该字段是明文）"""
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return ""
    p = Path(local) / "CodeBuddyExtension" / "Data" / "Public" / "auth" / "workbuddy-desktop.info"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d.get("account", {}).get("uid", "")
    except Exception:
        return ""


def warn_if_expiring(biz):
    end = biz.get("end_time")
    if not end:
        return
    try:
        end_dt = datetime.strptime(str(end), "%Y-%m-%d %H:%M:%S")
        left = (end_dt - datetime.now()).days
        if left < 0:
            log("WARNING: 本期签到活动已结束，接口可能不再发放奖励")
        elif left <= 7:
            log(f"WARNING: 本期活动将在 {left} 天后结束（{end}）")
    except Exception:
        pass


# ---------------------------------------------------------------- 请求封装
def request_with_retry(request, url):
    """有界退避重试；拿到业务 code 或认证错误就立即返回，不无脑重试"""
    result = None
    for i, delay in enumerate([0] + BACKOFF):
        if delay:
            time.sleep(delay)
        result = request(url)
        data = result.get("data")
        if isinstance(data, dict) and "code" in data:
            return result
        if result.get("httpStatus") in (401, 403):
            return result
        log(f"请求失败，第 {i + 1} 次重试（{delay}s 后）: {result.get('raw')}")
    return result


def make_direct_request(token, user_id):
    """零依赖模式：标准库 urllib 直接调接口"""
    import urllib.request
    import urllib.error

    auth = token if token.lower().startswith("bearer ") else "Bearer " + token
    headers = {
        "Authorization": auth,
        "X-User-Id": user_id,
        "Content-Type": "application/json",
    }
    log(f"认证方式: 手动 Token ({mask(auth)}) | X-User-Id: {mask(user_id)}")

    def request(url):
        req = urllib.request.Request(url, data=b"{}", headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8", "ignore")
                status = resp.status
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "ignore")
            status = e.code
        except Exception as e:
            return {"httpStatus": 0, "data": None, "raw": "FETCH_ERROR: " + str(e)}
        try:
            data = json.loads(raw)
        except Exception:
            data = None
        return {"httpStatus": status, "data": data, "raw": raw[:300]}

    return request


# ---------------------------------------------------------------- 核心流程
def run(request, label, do_sign=True):
    """查状态 -> 判断 -> 领取 -> 复核。返回退出码。"""
    # 1) 查状态
    st = request_with_retry(request, EP_STATUS)
    outer = st.get("data") if isinstance(st.get("data"), dict) else {}
    if st.get("httpStatus") == 401 or st.get("httpStatus") == 403:
        log(f"NOT_LOGGED_IN [{label}]: 登录态失效，请重新运行 login 或更新 Token")
        return 2
    if st.get("httpStatus") != 200 or outer.get("code") != CODE_OK:
        log(f"STATUS_FAILED [{label}]: http={st.get('httpStatus')} "
            f"code={outer.get('code')} raw={st.get('raw')}")
        return 1
    biz = outer.get("data")
    if not isinstance(biz, dict):
        log(f"STATUS_FAILED [{label}]: 响应缺少 data.data -> {st.get('raw')}")
        return 1

    remaining_credits = get_remaining_credits(request, label)
    log(f"当前状态: 今日已签={biz.get('today_checked_in')} | "
        f"连续 {fmt(biz.get('streak_days'))} 天 | "
        f"今日 {fmt(biz.get('today_credit'))}/{fmt(biz.get('daily_credit'))} 积分 | "
        f"剩余积分 {fmt_credits(remaining_credits)}")

    # 2) 幂等判断
    action = "ALREADY"
    if not do_sign:
        log("只读模式，跳过领取")
    elif biz.get("today_checked_in"):
        log("ACTION:ALREADY_SIGNED（今日已签，跳过领取，未发送写请求）")
    else:
        ck = request_with_retry(request, EP_CHECKIN)
        c_outer = ck.get("data") if isinstance(ck.get("data"), dict) else {}
        c_code = c_outer.get("code")
        if ck.get("httpStatus") == 200 and c_code == CODE_OK:
            action = "CLAIMED"
            log(f"ACTION:CLAIMED 成功领取积分 | {c_outer.get('msg', 'OK')}")
        elif c_code == CODE_ALREADY:
            action = "ALREADY"
            log("ACTION:ALREADY_SIGNED（接口返回今日已签）")
        else:
            action = "ERROR"
            log(f"ACTION:ERROR http={ck.get('httpStatus')} code={c_code} "
                f"msg={c_outer.get('msg')} raw={ck.get('raw')}")
            return 1

        # 3) 复核：领取后再查一次，避免「假成功」
        time.sleep(1.5)
        st2 = request_with_retry(request, EP_STATUS)
        o2 = st2.get("data") if isinstance(st2.get("data"), dict) else {}
        b2 = o2.get("data") if isinstance(o2.get("data"), dict) else None
        if b2 and b2.get("today_checked_in"):
            biz = b2
            log("复核通过: 今日已签状态已生效")
        else:
            log(f"复核异常: {st2.get('raw')}（请人工确认是否到账）")
            return 1
        remaining_credits = get_remaining_credits(request, label)

    warn_if_expiring(biz)
    log("=" * 60)
    log("REPORT: 今日 {t}/{d} 积分 | 连续 {s} 天 | 剩余积分 {r} | {act}".format(
        t=fmt(biz.get("today_credit")), d=fmt(biz.get("daily_credit")),
        s=fmt(biz.get("streak_days")), r=fmt_credits(remaining_credits),
        act={"CLAIMED": "签到成功", "ALREADY": "今日已签过", "ERROR": "签到失败"}.get(action, action)))
    log("=" * 60)
    return 0


# ---------------------------------------------------------------- 子命令
def cmd_doctor():
    log("=== 环境自检 ===")
    log(f"Python: {sys.version.split()[0]}")
    try:
        import playwright  # noqa: F401
        log("Playwright 包: 已安装")
    except ImportError:
        log("Playwright 包: 未安装 -> pip install playwright")
    local = os.environ.get("LOCALAPPDATA", "")
    browser_dir = Path(local) / "ms-playwright" if local else Path(".")
    if browser_dir.exists():
        found = [p.name for p in browser_dir.iterdir() if p.is_dir() and "chromium" in p.name]
        log(f"Chromium 内核: {found if found else '未发现（运行 playwright install chromium）'}")
    else:
        log("Chromium 内核: 未发现缓存")
    exe = chromium_executable()
    log(f"可复用内核: {exe if exe else '无（需 playwright install chromium）'}")
    log(f"登录态文件: {'存在 ' + str(AUTH_FILE) if AUTH_FILE.exists() else '不存在（先运行 login 或用 --direct）'}")
    log(f"日志文件: {LOG_FILE}")
    log(f"接口: {EP_STATUS} | {EP_CHECKIN}")
    return 0


def cmd_login():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("[FAIL] 需要先安装: pip install playwright")
        return 1

    with sync_playwright() as p:
        exe = chromium_executable()
        if exe:
            log(f"复用本机 Chromium 内核: {exe}")
        browser = p.chromium.launch(headless=False, executable_path=exe)
        ctx = browser.new_context(locale="zh-CN", timezone_id="Asia/Shanghai")
        page = ctx.new_page()
        try:
            navigate_with_retry(page, PROFILE_URL)
        except Exception as exc:
            log(f"[FAIL] 打开登录页面失败: {type(exc).__name__}: {exc}")
            ctx.close()
            browser.close()
            return 1
        print("\n>>> 请在打开的浏览器中完成登录（微信扫码 / 手机号等），最长等待 5 分钟 ...\n")

        request = lambda url: page.evaluate(FETCH_JS, url)
        deadline = time.time() + 300
        ok = False
        while time.time() < deadline:
            r = request(EP_STATUS)
            d = r.get("data") if isinstance(r.get("data"), dict) else {}
            if r.get("httpStatus") == 200 and d.get("code") == CODE_OK:
                ok = True
                break
            page.wait_for_timeout(2000)

        if not ok:
            log("[FAIL] 登录超时，未检测到有效登录态")
            browser.close()
            return 1

        page.wait_for_timeout(3000)  # 给 token 写盘留时间，实测踩出来的
        ctx.storage_state(path=str(AUTH_FILE))
        log(f"[OK] 登录态已保存: {AUTH_FILE}")
        log("提示: 该文件等同登录态，请勿提交 Git / 发群 / 上传网盘")
        browser.close()
        return 0


def with_playwright(do_sign=True):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("[FAIL] 未安装 playwright -> pip install playwright；或改用 --direct 模式")
        return 1
    if not AUTH_FILE.exists():
        log(f"[FAIL] 未找到登录态 {AUTH_FILE}，请先运行: python {Path(__file__).name} login")
        return 1

    with sync_playwright() as p:
        exe = chromium_executable()
        browser = p.chromium.launch(headless=True, executable_path=exe)
        ctx = browser.new_context(
            storage_state=str(AUTH_FILE), locale="zh-CN", timezone_id="Asia/Shanghai")
        page = ctx.new_page()
        try:
            navigate_with_retry(page, PROFILE_URL)
        except Exception as exc:
            log(f"[FAIL] 打开签到页面失败，已重试: {type(exc).__name__}: {exc}")
            ctx.close()
            browser.close()
            return 1
        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except Exception as exc:
            log(f"WARNING: 等待网络空闲超时，继续尝试接口请求: {type(exc).__name__}")
        page.wait_for_timeout(2500)

        request = lambda url: page.evaluate(FETCH_JS, url)
        code = run(request, "playwright", do_sign=do_sign)
        try:
            ctx.storage_state(path=str(AUTH_FILE))  # token 可能已刷新，回写最新登录态
        except Exception:
            pass
        browser.close()
        return code


def with_direct(token, user_id, do_sign=True):
    if not token:
        log("[FAIL] --direct 模式需要 Token：设置环境变量 WORKBUDDY_TOKEN 或用 --token 传入")
        return 1
    if not user_id:
        log("[FAIL] 未找到 X-User-Id：设置 WORKBUDDY_USER_ID 或先登录一次 WorkBuddy 桌面端")
        return 1
    return run(make_direct_request(token, user_id), "direct", do_sign=do_sign)


def main():
    ap = argparse.ArgumentParser(description="WorkBuddy 每日自动签到领积分")
    ap.add_argument("cmd", nargs="?", default="checkin",
                    choices=["checkin", "login", "status", "doctor"])
    ap.add_argument("--direct", action="store_true", help="用标准库 + 手动 Token（无需 playwright）")
    ap.add_argument("--token", default=os.environ.get("WORKBUDDY_TOKEN", ""), help="Bearer Token")
    ap.add_argument("--user-id", default=os.environ.get("WORKBUDDY_USER_ID", "") or read_local_uid(),
                    help="X-User-Id")
    args = ap.parse_args()

    if args.cmd == "doctor":
        return cmd_doctor()
    if args.cmd == "login":
        return cmd_login()

    do_sign = args.cmd == "checkin"
    if args.direct or args.token:
        return with_direct(args.token, args.user_id, do_sign)
    return with_playwright(do_sign)


if __name__ == "__main__":
    sys.exit(main())

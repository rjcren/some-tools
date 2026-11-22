"""
可复用的 HTTP 请求头构造模块。

设计原则：
- browser_base() 只放跨站点通用的浏览器指纹字段；
- 站点特定字段（Origin / Referer / Sec-Fetch-Site / Accept / Content-Type）
  由调用方通过 RequestContext 和 body 参数传入；
- 不依赖任何全局变量，便于其他脚本直接 import。
"""

from dataclasses import dataclass
from typing import Literal, Optional

BodyKind = Literal["none", "form", "json"]
RequestKind = Literal["navigation", "xhr", "xhr_post"]


def browser_base() -> dict[str, str]:
    """跨站点通用的浏览器指纹基线（不含站点特定字段）。"""
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/158.0.0.0 Safari/537.36 Edg/158.0.0.0"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "Accept-Encoding": "gzip, deflate",
        "Sec-Ch-Ua": (
            '"Chromium";v="158", "Not.A/Brand";v="24", '
            '"Microsoft Edge";v="158"'
        ),
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Gpc": "1",
    }


@dataclass(frozen=True)
class RequestContext:
    """单个请求的语境参数。"""

    base_url: str
    referer_path: Optional[str] = None
    site: Literal["same-origin", "same-site", "cross-site"] = "same-origin"
    ajax: bool = True            # 是否带 X-Requested-With
    accept: Optional[str] = None  # 不传则按 kind 使用默认值


def build_headers(
    kind: RequestKind,
    ctx: RequestContext,
    body: BodyKind = "none",
) -> dict[str, str]:
    """
    按请求类型构造请求头。

    kind:
        - "navigation": 导航式 GET（HTML 页面）
        - "xhr":        XHR/fetch GET（JSON 接口）
        - "xhr_post":   XHR/fetch POST（JSON 或表单接口）
    body:
        仅对 xhr_post 生效："none" 不带 Content-Type，
        "form" 用 application/x-www-form-urlencoded，
        "json" 用 application/json。
    """
    headers = browser_base()

    if kind == "navigation":
        headers.update({
            "Accept": ctx.accept or (
                "text/html,application/xhtml+xml,application/xml;"
                "q=0.9,*/*;q=0.8"
            ),
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": ctx.site,
        })
    else:
        headers.update({
            "Accept": ctx.accept or (
                "application/json, text/javascript, */*; q=0.01"
            ),
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": ctx.site,
            "Origin": ctx.base_url,
        })
        if ctx.ajax:
            headers["X-Requested-With"] = "XMLHttpRequest"
        if kind == "xhr_post":
            if body == "form":
                headers["Content-Type"] = (
                    "application/x-www-form-urlencoded; charset=UTF-8"
                )
            elif body == "json":
                headers["Content-Type"] = "application/json"

    if ctx.referer_path:
        headers["Referer"] = f"{ctx.base_url}{ctx.referer_path}"

    return headers
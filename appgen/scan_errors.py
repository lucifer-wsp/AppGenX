"""扫描与 App Store 请求相关异常格式化。"""

from __future__ import annotations

import httpx


def format_scan_error(exc: BaseException) -> str:
    """将异常转为用户可读的错误说明。"""
    msg = str(exc).strip()
    if isinstance(exc, httpx.ConnectError):
        base = "无法连接 App Store API（itunes.apple.com / rss.marketingtools.apple.com）"
        hint = "请检查网络，或在 .env 中设置 APPGEN_HTTP_PROXY=http://127.0.0.1:7890"
        return f"{base}。{hint}" if not msg else f"{base}: {msg}"
    if isinstance(exc, httpx.TimeoutException):
        return "连接 App Store API 超时，请稍后重试或缩小扫描范围（少选品类/区域）"
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 429:
            return "App Store API 限流 (HTTP 429)，已自动退避重试；若持续失败请降低「榜单拉取并发」"
        if code == 403:
            return (
                "App Store API 拒绝访问 (HTTP 403)，多为并发过高或 IP 被限流；"
                "请降低「榜单拉取并发」、配置 HTTP 代理，或稍后重试"
            )
        return f"App Store API 返回 HTTP {code}"
    if msg:
        return f"{type(exc).__name__}: {msg}"
    return f"{type(exc).__name__}（无详细消息，多为网络不可达）"


def is_requeueable_fetch_error(exc: BaseException) -> bool:
    """单任务失败后是否应加入队尾、先继续其他 item（非立即重试）。"""
    if is_legacy_rss_blocked_error(exc):
        return False
    if is_rate_limited_fetch_error(exc):
        return True
    if isinstance(exc, (httpx.ConnectError, httpx.TimeoutException)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (408, 500, 502, 503, 504)
    return False


def is_rate_limited_fetch_error(exc: BaseException) -> bool:
    """单任务在 HTTP 客户端重试耗尽后，是否仍属可队尾重试的限流/拒绝。"""
    if is_legacy_rss_blocked_error(exc):
        return False
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (403, 429)
    msg = str(exc)
    return any(
        token in msg
        for token in ("HTTP 429", "限流")
    ) or (
        any(token in msg for token in ("HTTP 403", "拒绝访问"))
        and "itunes.apple.com" not in msg
    )


def is_legacy_rss_blocked_error(exc: BaseException) -> bool:
    """itunes.apple.com/rss 公开源已被 Apple 关闭，403 为永久性失败，不应重试或降并发。"""
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code != 403:
            return False
        try:
            url = str(exc.request.url)
        except Exception:
            url = ""
        return "itunes.apple.com" in url and "/rss/" in url
    msg = str(exc)
    return (
        "itunes.apple.com" in msg
        and "/rss/" in msg
        and any(token in msg for token in ("HTTP 403", "拒绝访问", "403"))
    )

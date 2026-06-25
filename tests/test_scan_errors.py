import httpx

from appgen.scan_errors import is_legacy_rss_blocked_error, is_rate_limited_fetch_error


def test_legacy_rss_403_is_not_rate_limited():
    request = httpx.Request(
        "GET",
        "https://itunes.apple.com/us/rss/topfreeapplications/limit=5/genre=6013/json",
    )
    response = httpx.Response(403, request=request)
    exc = httpx.HTTPStatusError("403", request=request, response=response)
    assert is_legacy_rss_blocked_error(exc)
    assert not is_rate_limited_fetch_error(exc)


def test_marketing_429_is_rate_limited():
    request = httpx.Request(
        "GET",
        "https://rss.marketingtools.apple.com/api/v2/us/apps/top-free/5/apps.json",
    )
    response = httpx.Response(429, request=request)
    exc = httpx.HTTPStatusError("429", request=request, response=response)
    assert is_rate_limited_fetch_error(exc)
    assert not is_legacy_rss_blocked_error(exc)

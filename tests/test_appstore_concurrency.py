import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from appgen.tools.appstore import (
    AppStoreClient,
    _clamp_concurrency,
    _default_headers,
    _http_client_kwargs,
    app_store_scan_pool,
)


def test_clamp_concurrency(monkeypatch):
    from appgen.config import settings

    settings.appgen_scan_concurrency = 10
    settings.appgen_scan_max_concurrency = 20
    assert _clamp_concurrency(None) == 10
    assert _clamp_concurrency(50) == 20
    assert _clamp_concurrency(1) == 1


def test_http_client_uses_browser_user_agent():
    headers = _default_headers()
    assert "Mozilla" in headers["User-Agent"]
    assert "python-httpx" not in headers["User-Agent"]
    kwargs = _http_client_kwargs()
    assert kwargs["headers"]["User-Agent"] == headers["User-Agent"]
    assert kwargs["headers"]["Referer"] == "https://apps.apple.com/"


@pytest.mark.asyncio
async def test_403_is_retried(monkeypatch):
    import httpx

    attempts = 0

    async def fake_get(url, params=None):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            request = httpx.Request("GET", url)
            response = httpx.Response(403, request=request)
            raise httpx.HTTPStatusError("403", request=request, response=response)
        return _mock_json_response(url)

    monkeypatch.setattr("appgen.tools.appstore.HTTP_REQUEST_JITTER_SEC", (0.0, 0.0))
    monkeypatch.setattr("appgen.tools.appstore.HTTP_403_EXTRA_DELAY_SEC", (0.0, 0.0))
    monkeypatch.setattr("appgen.tools.appstore._retry_delay", lambda *a, **k: 0.0)

    client = AppStoreClient(country="us")
    client._owned_client = httpx.AsyncClient(headers=_default_headers())
    client._http_client = client._owned_client
    client._owned_client.get = fake_get  # type: ignore[method-assign]

    apps = await client.fetch_top_charts("top-free", limit=1)
    assert attempts == 3
    assert apps[0].name == "App"
    await client.aclose()


@pytest.mark.asyncio
async def test_shared_pool_reuses_client():
    calls = 0

    async def fake_get(url, params=None):
        nonlocal calls
        calls += 1
        return _mock_json_response(url)

    async with app_store_scan_pool(4) as (http_client, sem):
        http_client.get = fake_get  # type: ignore[method-assign]
        c1 = AppStoreClient(country="us", http_client=http_client, semaphore=sem)
        c2 = AppStoreClient(country="gb", http_client=http_client, semaphore=sem)
        await asyncio.gather(
            c1.fetch_top_charts("top-free", limit=1),
            c2.fetch_top_charts("top-free", limit=1),
        )

    assert calls == 2


@pytest.mark.asyncio
async def test_genre_chart_uses_marketing_rss():
    seen: list[tuple[str, dict | None]] = []

    async def fake_get_json(url, *, params=None):
        seen.append((url, params))
        return {"feed": {"results": [{"id": "1", "name": "Health App", "artistName": "Dev"}]}}

    client = AppStoreClient(country="us")
    client._get_json = fake_get_json  # type: ignore[method-assign]
    genre = next(g for g in __import__("appgen.tools.genres", fromlist=["APP_GENRES"]).APP_GENRES if g.id == 6013)

    apps = await client.fetch_genre_chart(genre, chart_type="top-free", limit=5)

    assert seen[0][0] == (
        "https://rss.marketingtools.apple.com/api/v2/us/apps/top-free/5/apps.json"
    )
    assert seen[0][1] == {"genreId": 6013}
    assert apps[0].name == "Health App"
    assert apps[0].chart_category == "top-free:6013"


@pytest.mark.asyncio
async def test_top_grossing_uses_legacy_rss():
    seen_urls: list[str] = []

    async def fake_get_json(url, *, params=None):
        seen_urls.append(url)
        return _legacy_feed_json()

    client = AppStoreClient(country="us")
    client._get_json = fake_get_json  # type: ignore[method-assign]

    apps = await client.fetch_top_charts("top-grossing", limit=10)

    assert len(seen_urls) == 1
    assert seen_urls[0] == "https://itunes.apple.com/us/rss/topgrossingapplications/limit=10/json"
    assert len(apps) == 1
    assert apps[0].name == "Legacy App"
    assert apps[0].chart_category == "top-grossing"


@pytest.mark.asyncio
async def test_top_free_uses_marketing_rss():
    seen_urls: list[str] = []

    async def fake_get_json(url, *, params=None):
        seen_urls.append(url)
        return {"feed": {"results": [{"id": "1", "name": "App", "artistName": "Dev"}]}}

    client = AppStoreClient(country="us")
    client._get_json = fake_get_json  # type: ignore[method-assign]

    apps = await client.fetch_top_charts("top-free", limit=5)

    assert seen_urls[0] == (
        "https://rss.marketingtools.apple.com/api/v2/us/apps/top-free/5/apps.json"
    )
    assert apps[0].name == "App"


def _legacy_feed_json():
    return {
        "feed": {
            "entry": [
                {
                    "id": {"label": "https://apps.apple.com/us/app/id42"},
                    "im:name": {"label": "Legacy App"},
                    "im:artist": {"label": "Dev"},
                }
            ]
        }
    }


def _mock_json_response(url: str):
    class Resp:
        status_code = 200

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            if "apps.json" in url:
                return {"feed": {"results": [{"id": "1", "name": "App", "artistName": "Dev"}]}}
            return _legacy_feed_json()

    return Resp()

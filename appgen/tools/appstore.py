from __future__ import annotations

import asyncio
import os
import random
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx

from appgen.config import settings
from appgen.constants import (
    CHART_RSS_SLUGS,
    DEFAULT_APPSTORE_USER_AGENT,
    HTTP_403_EXTRA_DELAY_SEC,
    HTTP_MAX_RETRIES,
    HTTP_REQUEST_JITTER_SEC,
    HTTP_RETRYABLE_STATUS,
    ITUNES_LOOKUP_URL,
    ITUNES_SEARCH_URL,
)
from appgen.models import AppStoreApp
from appgen.runtime_settings import runtime_settings
from appgen.scan_errors import format_scan_error
from appgen.tools.genres import CHART_TYPES


def _default_headers() -> dict[str, str]:
    return {
        "User-Agent": DEFAULT_APPSTORE_USER_AGENT,
        "Accept": "application/json, text/javascript, application/xml, */*; q=0.01",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://apps.apple.com/",
    }


def _http_client_kwargs() -> dict[str, Any]:
    rc = runtime_settings.get()
    proxy = (
        rc.http_proxy
        or settings.appgen_http_proxy
        or os.environ.get("APPGEN_HTTP_PROXY")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("HTTP_PROXY")
    )
    kwargs: dict[str, Any] = {
        "timeout": httpx.Timeout(30.0, connect=12.0),
        "follow_redirects": True,
        "headers": _default_headers(),
    }
    if proxy:
        kwargs["proxy"] = proxy
    return kwargs


def _clamp_concurrency(value: int | None) -> int:
    rc = runtime_settings.get()
    raw = value if value is not None else rc.scan_concurrency
    return max(1, min(int(raw), rc.scan_max_concurrency))


def _retry_delay(attempt: int, *, retry_after: float | None = None, status: int | None = None) -> float:
    if retry_after is not None and retry_after > 0:
        return min(retry_after, 30.0)
    base = 0.6 * (2**attempt)
    delay = min(base + random.uniform(0, 0.25), 12.0)
    if status == 403:
        delay += random.uniform(*HTTP_403_EXTRA_DELAY_SEC)
    return delay


@asynccontextmanager
async def app_store_scan_pool(
    concurrency: int | None = None,
) -> AsyncIterator[tuple[httpx.AsyncClient, asyncio.Semaphore]]:
    """共享连接池 + 并发信号量，用于批量榜单拉取。"""
    limit = _clamp_concurrency(concurrency)
    sem = asyncio.Semaphore(limit)
    client_limits = httpx.Limits(
        max_connections=limit + 4,
        max_keepalive_connections=limit,
    )
    async with httpx.AsyncClient(**_http_client_kwargs(), limits=client_limits) as client:
        yield client, sem


class AppStoreClient:
    """App Store 公开 API 客户端（支持连接池复用与受控并发）。"""

    def __init__(
        self,
        country: str = "us",
        timeout: float = 30.0,
        *,
        http_client: httpx.AsyncClient | None = None,
        semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        self.country = country
        self.timeout = timeout
        self._http_client = http_client
        self._semaphore = semaphore
        self._owned_client: httpx.AsyncClient | None = None

    async def aclose(self) -> None:
        if self._owned_client is not None:
            await self._owned_client.aclose()
            self._owned_client = None

    async def _client(self) -> httpx.AsyncClient:
        if self._http_client is not None:
            return self._http_client
        if self._owned_client is None:
            kwargs = _http_client_kwargs()
            kwargs["timeout"] = httpx.Timeout(self.timeout, connect=12.0)
            self._owned_client = httpx.AsyncClient(**kwargs)
        return self._owned_client

    async def _get_json(self, url: str, *, params: dict | None = None) -> dict:
        last_exc: BaseException | None = None

        for attempt in range(HTTP_MAX_RETRIES):
            try:
                if self._semaphore is not None:
                    async with self._semaphore:
                        payload = await self._request_once(url, params=params)
                else:
                    payload = await self._request_once(url, params=params)
                return payload
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                status = exc.response.status_code
                if status in HTTP_RETRYABLE_STATUS and attempt < HTTP_MAX_RETRIES - 1:
                    retry_after: float | None = None
                    if status == 429:
                        raw = exc.response.headers.get("retry-after")
                        if raw:
                            try:
                                retry_after = float(raw)
                            except ValueError:
                                retry_after = None
                    await asyncio.sleep(
                        _retry_delay(attempt, retry_after=retry_after, status=status)
                    )
                    continue
                break
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt < HTTP_MAX_RETRIES - 1:
                    await asyncio.sleep(_retry_delay(attempt))
                    continue
                break

        assert last_exc is not None
        detail = format_scan_error(last_exc)
        raise RuntimeError(f"{detail} [GET {url}]") from last_exc

    async def _request_once(self, url: str, *, params: dict | None = None) -> dict:
        await asyncio.sleep(random.uniform(*HTTP_REQUEST_JITTER_SEC))
        client = await self._client()
        resp = await client.get(url, params=params)
        if resp.status_code in HTTP_RETRYABLE_STATUS:
            resp.raise_for_status()
        resp.raise_for_status()
        return resp.json()

    async def fetch_top_charts(
        self,
        chart_type: str = "top-free",
        limit: int = 25,
    ) -> list[AppStoreApp]:
        rc = runtime_settings.get()
        if chart_type in rc.legacy_top_chart_types:
            chart = CHART_TYPES.get(chart_type, CHART_RSS_SLUGS["top-free"])
            url = rc.rss_legacy_top_url.format(
                country=self.country,
                chart=chart,
                limit=limit,
            )
            payload = await self._get_json(url)
            return self._parse_legacy_feed(payload, chart_type)

        url = rc.rss_marketing_url.format(
            country=self.country,
            chart_type=chart_type,
            limit=limit,
        )
        payload = await self._get_json(url)
        return self._parse_marketing_results(payload, chart_type)

    def _parse_marketing_results(
        self,
        payload: dict,
        chart_type: str,
        *,
        genre: Any | None = None,
    ) -> list[AppStoreApp]:
        apps: list[AppStoreApp] = []
        chart_category = f"{chart_type}:{genre.id}" if genre is not None else chart_type
        for idx, item in enumerate(payload.get("feed", {}).get("results", []), start=1):
            apps.append(
                AppStoreApp(
                    app_id=str(item.get("id", "")),
                    name=item.get("name", ""),
                    bundle_id=None,
                    seller=item.get("artistName"),
                    genre=genre.name if genre is not None else (item.get("genres") or [None])[0],
                    description=None,
                    chart_rank=idx,
                    chart_category=chart_category,
                    source_url=item.get("url"),
                )
            )
        return apps

    def _parse_legacy_feed(
        self,
        payload: dict,
        chart_type: str,
        *,
        genre: Any | None = None,
    ) -> list[AppStoreApp]:
        entries = payload.get("feed", {}).get("entry", [])
        if isinstance(entries, dict):
            entries = [entries]

        apps: list[AppStoreApp] = []
        for idx, entry in enumerate(entries, start=1):
            app_id = self._entry_id(entry)
            name = entry.get("im:name", {}).get("label", "")
            seller = entry.get("im:artist", {}).get("label")
            category = entry.get("category", {}).get("attributes", {}).get("label")
            source_url = entry.get("id", {}).get("label")
            chart_category = (
                f"{chart_type}:{genre.id}" if genre is not None else chart_type
            )
            apps.append(
                AppStoreApp(
                    app_id=app_id,
                    name=name,
                    seller=seller,
                    genre=category or (genre.name if genre else None),
                    chart_rank=idx,
                    chart_category=chart_category,
                    source_url=source_url,
                )
            )
        return apps

    async def fetch_genre_chart(
        self,
        genre: Any,
        chart_type: str = "top-free",
        limit: int = 15,
    ) -> list[AppStoreApp]:
        if chart_type == "top-grossing":
            raise RuntimeError(
                "App Store 品类畅销榜公开 RSS 不可用（Apple 已关闭 itunes RSS）。"
                "请取消 top-grossing 或仅扫描免费/付费榜。"
            )

        rc = runtime_settings.get()
        url = rc.rss_marketing_url.format(
            country=self.country,
            chart_type=chart_type,
            limit=limit,
        )
        payload = await self._get_json(url, params={"genreId": genre.id})
        return self._parse_marketing_results(payload, chart_type, genre=genre)

    async def search_apps(
        self,
        term: str,
        limit: int = 10,
        *,
        genre_id: int | None = None,
    ) -> list[AppStoreApp]:
        params: dict[str, str | int] = {
            "term": term,
            "country": self.country,
            "entity": "software",
            "limit": limit,
        }
        if genre_id is not None:
            params["genreId"] = genre_id

        payload = await self._get_json(ITUNES_SEARCH_URL, params=params)
        return [self._map_lookup_item(item) for item in payload.get("results", [])]

    async def lookup_app(self, app_id: str) -> AppStoreApp | None:
        params = {"id": app_id, "country": self.country}
        payload = await self._get_json(ITUNES_LOOKUP_URL, params=params)
        results = payload.get("results", [])
        if not results:
            return None
        return self._map_lookup_item(results[0])

    async def lookup_apps(self, app_ids: list[str]) -> list[AppStoreApp]:
        if not app_ids:
            return []
        params = {"id": ",".join(app_ids[:50]), "country": self.country}
        payload = await self._get_json(ITUNES_LOOKUP_URL, params=params)
        return [self._map_lookup_item(item) for item in payload.get("results", [])]

    @staticmethod
    def _entry_id(entry: dict) -> str:
        raw = entry.get("id", {}).get("label", "")
        if "/id" in raw:
            return raw.rsplit("/id", 1)[-1].split("?", 1)[0]
        return raw

    def _map_lookup_item(self, item: dict) -> AppStoreApp:
        screenshots = item.get("screenshotUrls") or item.get("ipadScreenshotUrls") or []
        return AppStoreApp(
            app_id=str(item.get("trackId", item.get("collectionId", ""))),
            name=item.get("trackName", item.get("collectionName", "")),
            bundle_id=item.get("bundleId"),
            seller=item.get("sellerName") or item.get("artistName"),
            genre=(item.get("genres") or [None])[0],
            price=item.get("price"),
            rating=item.get("averageUserRating"),
            rating_count=item.get("userRatingCount"),
            description=item.get("description"),
            release_notes=item.get("releaseNotes"),
            screenshot_urls=screenshots[:5],
            source_url=item.get("trackViewUrl"),
        )

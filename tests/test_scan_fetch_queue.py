import asyncio
from unittest.mock import AsyncMock

import pytest

from appgen.discovery import CategorySnapshot, MarketScanner, _ChartFetchJob
from appgen.models import AppStoreApp
from appgen.scan_errors import is_rate_limited_fetch_error
from appgen.tools.genres import APP_GENRES


def test_is_rate_limited_fetch_error_from_runtime_message():
    exc = RuntimeError("App Store API 拒绝访问 (HTTP 403)，多为并发过高")
    assert is_rate_limited_fetch_error(exc)


@pytest.mark.asyncio
async def test_fetch_queue_requeues_rate_limited_jobs(monkeypatch):
    from appgen.config import settings

    settings.appgen_scan_concurrency = 1
    settings.appgen_scan_max_concurrency = 2

    scanner = MarketScanner()
    genre = next(g for g in APP_GENRES if g.id == 6013)
    jobs = [
        _ChartFetchJob(country="us", chart_type="top-free", kind="genre", genre=genre),
    ]

    attempts = {"n": 0}

    async def fake_try_fetch(scan, job, client):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("App Store API 拒绝访问 (HTTP 403)")
        return CategorySnapshot(
            country=job.country,
            country_label="美国",
            genre_id=genre.id,
            genre_name=genre.name,
            genre_name_zh=genre.name_zh,
            chart_type=job.chart_type,
            chart_label="免费榜",
            apps=[
                AppStoreApp(
                    app_id="1",
                    name="Test",
                    chart_rank=1,
                    chart_category=job.chart_type,
                )
            ],
        )

    monkeypatch.setattr(scanner, "_try_fetch_snapshot", fake_try_fetch)
    monkeypatch.setattr("appgen.discovery.asyncio.sleep", AsyncMock())

    scan = scanner.create_scan(
        countries=["us"],
        region_preset="us",
        chart_types=["top-free"],
        per_genre_limit=5,
        enrich_top_n=0,
    )

    snapshots = await scanner._fetch_snapshots_concurrent(scan, jobs)
    assert len(snapshots) == 1
    assert attempts["n"] == 2
    assert any("队尾重试" in line for line in scan.logs)


@pytest.mark.asyncio
async def test_fetch_queue_defers_retry_until_other_jobs_done(monkeypatch):
    """失败品类加入 retry 队列，先完成其他 item 再重试。"""
    from appgen.config import settings

    settings.appgen_scan_concurrency = 2

    scanner = MarketScanner()
    genres = [g for g in APP_GENRES if g.id in (6013, 6007)]
    jobs = [
        _ChartFetchJob(country="us", chart_type="top-free", kind="genre", genre=genres[0]),
        _ChartFetchJob(country="us", chart_type="top-free", kind="genre", genre=genres[1]),
    ]

    order: list[int] = []
    fail_first = {genres[0].id: True}

    async def fake_try_fetch(scan, job, client):
        assert job.genre is not None
        gid = job.genre.id
        order.append(gid)
        if fail_first.get(gid):
            fail_first[gid] = False
            raise RuntimeError("App Store API 拒绝访问 (HTTP 403)")
        return CategorySnapshot(
            country=job.country,
            country_label="美国",
            genre_id=gid,
            genre_name=job.genre.name,
            genre_name_zh=job.genre.name_zh,
            chart_type=job.chart_type,
            chart_label="免费榜",
            apps=[
                AppStoreApp(
                    app_id=str(gid),
                    name="Test",
                    chart_rank=1,
                    chart_category=job.chart_type,
                )
            ],
        )

    monkeypatch.setattr(scanner, "_try_fetch_snapshot", fake_try_fetch)
    monkeypatch.setattr("appgen.discovery.asyncio.sleep", AsyncMock())

    scan = scanner.create_scan(
        countries=["us"],
        region_preset="us",
        chart_types=["top-free"],
        per_genre_limit=5,
        enrich_top_n=0,
    )

    snapshots = await scanner._fetch_snapshots_concurrent(scan, jobs)
    assert len(snapshots) == 2
    # 第一次尝试：6013 失败；6017 成功；6013 在 retry 队列中第二轮才重试
    assert order.index(genres[1].id) < order.index(genres[0].id, 1)

from __future__ import annotations

import asyncio
from typing import Any

from appgen.config import settings
from appgen.discovery import MarketScanner
from appgen.pipeline import PipelineOrchestrator
from appgen.runtime_settings import runtime_settings
from appgen.constants import CHART_RSS_SLUGS
from appgen.tools.genres import (
    CHART_TYPES,
    estimate_scan_requests,
    get_app_genres,
    get_popular_genre_ids,
    resolve_genres,
)
from appgen.tools.regions import get_default_region_preset, resolve_region_codes


def normalize_scan_limit(limit: int) -> int:
    rc = runtime_settings.get()
    min_v, max_v = rc.scan_limit_min, rc.scan_limit_max
    if limit < min_v or limit > max_v:
        raise ValueError(f"每类条数须在 {min_v}–{max_v} 之间")
    return limit


def plan_scan(
    *,
    keyword: str | None,
    genre_ids: list[int] | None,
    regions: str,
    charts: list[str],
) -> dict[str, Any]:
    """计算扫描模式与预估工作量。"""
    kw = (keyword or "").strip()
    ids = genre_ids or []

    if kw and not ids:
        mode = "keyword"
        genre_count = 0
        desc = f"关键词「{kw}」+ 榜单 Top N（快速，并发拉取）"
        est_min, est_max = 0, 1
    elif not ids:
        mode = "full"
        genre_count = len(get_app_genres())
        desc = f"全品类 {genre_count} 个分类（数据最全，并发拉取）"
        total_req = estimate_scan_requests(
            country_count=len(resolve_region_codes(preset=regions)),
            genre_count=genre_count,
            chart_count=len(charts),
        )
        est_sec = max(5, total_req // max(runtime_settings.get().scan_concurrency, 1))
        est_min = max(1, est_sec // 60)
        est_max = max(3, (est_sec + 59) // 60)
    else:
        mode = "categories"
        genre_count = len(ids)
        names = [g.name_zh for g in resolve_genres(ids) or []]
        desc = f"已选 {genre_count} 个品类: {', '.join(names[:4])}{'…' if len(names) > 4 else ''}"
        total_req = estimate_scan_requests(
            country_count=len(resolve_region_codes(preset=regions)),
            genre_count=genre_count,
            chart_count=len(charts),
        )
        est_sec = max(3, total_req // max(runtime_settings.get().scan_concurrency, 1))
        est_min = 0 if est_sec < 60 else 1
        est_max = max(1, (est_sec + 30) // 60)

    countries = resolve_region_codes(preset=regions)
    if mode == "keyword":
        requests = len(countries) * (1 + len(charts))  # search + charts per country
    else:
        requests = estimate_scan_requests(
            country_count=len(countries),
            genre_count=genre_count,
            chart_count=len(charts),
        )

    return {
        "mode": mode,
        "description": desc,
        "requests": requests,
        "countries": len(countries),
        "genres": genre_count,
        "charts": len(charts),
        "estimate_minutes": f"{est_min}–{est_max}",
    }


async def start_market_scan(
    *,
    keyword: str | None = None,
    genre_ids: list[int] | None = None,
    regions: str = "us",
    charts: list[str] | None = None,
    limit: int = 10,
    enrich: int = 5,
) -> dict[str, Any]:
    """启动市场扫描，返回 scan_id 与计划信息。"""
    limit = normalize_scan_limit(limit)
    rc = runtime_settings.get()
    chart_types = charts or list(rc.default_charts)
    for chart in chart_types:
        if chart not in CHART_RSS_SLUGS:
            raise ValueError(f"不支持的榜单: {chart}")

    plan = plan_scan(
        keyword=keyword,
        genre_ids=genre_ids,
        regions=regions,
        charts=chart_types,
    )
    kw = (keyword or "").strip()
    ids = list(genre_ids or [])
    countries = resolve_region_codes(preset=regions)

    scanner = MarketScanner()
    scan = scanner.create_scan(
        countries=countries,
        region_preset=regions,
        chart_types=chart_types,
        per_genre_limit=limit,
        enrich_top_n=enrich,
    )
    scan.focus_keyword = kw or None
    scan.scan_mode = plan["mode"]
    scan.selected_genre_ids = ids
    scanner._flush(scan, full=True)

    genres_resolved = resolve_genres(ids) if plan["mode"] != "keyword" else None

    async def _bg() -> None:
        if plan["mode"] == "keyword":
            await scanner.run_keyword_scan_by_id(scan.id, kw)
        else:
            await scanner.run_scan_by_id(
                scan.id,
                genres=genres_resolved,
                focus_keyword=kw or None,
            )

    asyncio.create_task(_bg())
    return {"id": scan.id, "status": "started", "plan": plan}


async def pick_opportunity_and_run(
    scan_id: str,
    rank: int,
    orchestrator: PipelineOrchestrator,
    *,
    auto_review: bool = False,
) -> dict[str, Any]:
    """从扫描结果选定机会并启动完整流水线。"""
    settings.appgen_review_mode = "web"
    scanner = MarketScanner()
    scan = scanner.get_scan(scan_id)

    if scan.status != "completed":
        raise ValueError(f"扫描尚未完成，当前状态: {scan.status}")
    if not scan.opportunities:
        raise ValueError("该扫描未产出机会列表")

    opp = next((o for o in scan.opportunities if o.rank == rank), None)
    if opp is None:
        raise ValueError(f"未找到序号 {rank} 的机会")

    keyword = opp.suggested_keyword or scan.focus_keyword or opp.title
    chart = opp.chart_type if opp.chart_type in CHART_TYPES else (scan.chart_types[0] if scan.chart_types else "top-free")
    run = orchestrator.create_run(
        keyword=keyword,
        category=chart,
        country=opp.country,
        auto_review=auto_review,
    )
    run.metadata["picked_from_scan"] = scan_id
    run.metadata["picked_opportunity"] = opp.model_dump()
    orchestrator.store.save_run(run)

    async def _run_pipeline() -> None:
        try:
            await orchestrator.run_until_pause(run)
        except Exception as exc:
            current = orchestrator.get_run(run.id)
            current.status = "failed"
            current.log(f"Pipeline: 未捕获异常 — {exc}")
            orchestrator.store.save_run(current)

    asyncio.create_task(_run_pipeline())
    return {
        "run_id": run.id,
        "status": "started",
        "opportunity_title": opp.title,
    }

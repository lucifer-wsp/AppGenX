from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from appgen.config import settings
from appgen.llm import LLMClient
from appgen.models import AppStoreApp
from appgen.scan_cancel import ScanCancelledError, is_requested as scan_cancel_requested, register as register_scan_cancel, unregister as unregister_scan_cancel
from appgen.scan_errors import format_scan_error, is_legacy_rss_blocked_error, is_rate_limited_fetch_error, is_requeueable_fetch_error
from appgen.scan_fetch_concurrency import ScanFetchConcurrencyGovernor
from appgen.llm_cursor import cursor_launch_wave
from appgen.scan_preferences import ScanPreferencesStore
from appgen.tools.appstore import AppStoreClient, app_store_scan_pool
from appgen.tools.genres import CHART_LABELS, CHART_TYPES, AppGenre, get_app_genres
from appgen.constants import (
    BLOCKED_REGION_CODES,
    CHART_TOP_GROSSING,
    SCAN_FETCH_JOB_BACKOFF_CAP_SEC,
    SCAN_FETCH_MAX_JOB_RETRIES,
)
from appgen.analyze_limits import normalize_analyze_max_snapshots
from appgen.runtime_settings import runtime_settings
from appgen.tools.regions import get_default_region_preset, format_regions, region_label


@dataclass(frozen=True)
class _ChartFetchJob:
    country: str
    chart_type: str
    kind: Literal["genre", "top", "search"] = "genre"
    genre: AppGenre | None = None
    keyword: str = ""


@dataclass
class _PendingFetchJob:
    job: _ChartFetchJob
    attempts: int = 0
    rate_limited: bool = False


class CategorySnapshot(BaseModel):
    country: str
    country_label: str = ""
    genre_id: int
    genre_name: str
    genre_name_zh: str
    chart_type: str
    chart_label: str
    apps: list[AppStoreApp] = Field(default_factory=list)
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def fill_country_label(self) -> "CategorySnapshot":
        if not self.country_label:
            self.country_label = region_label(self.country)
        return self


class DemandOpportunity(BaseModel):
    rank: int
    title: str
    country: str = "us"
    country_label: str = ""
    genre: str
    genre_zh: str
    chart_type: str
    one_liner: str
    pain_points: list[str] = Field(default_factory=list)
    reference_apps: list[str] = Field(default_factory=list)
    differentiation: str = ""
    confidence_score: int = Field(ge=0, le=100, default=50)
    suggested_keyword: str = ""
    why_now: str = ""

    @model_validator(mode="after")
    def fill_country_label(self) -> "DemandOpportunity":
        if not self.country_label:
            self.country_label = region_label(self.country)
        return self


_BLOCKED_REGIONS = BLOCKED_REGION_CODES


def keyword_tokens(keyword: str) -> list[str]:
    """解析关注关键词：支持 relax & life & happy、逗号、空格分隔。"""
    normalized = re.sub(r"\s*&\s*", " ", keyword.strip().lower())
    return [t for t in re.split(r"[\s,+/|]+", normalized) if len(t) > 2]


def normalize_search_keyword(keyword: str) -> str:
    """App Store 搜索用：去掉 & 等符号。"""
    return re.sub(r"\s*&\s*", " ", keyword.strip())


def _brief_keyword_score(brief: dict[str, Any], tokens: list[str]) -> int:
    if not tokens:
        return 0
    blob = json.dumps(brief, ensure_ascii=False).lower()
    score = sum(3 for t in tokens if t in blob)
    genre = str(brief.get("genre") or "").lower()
    if genre.startswith("search"):
        score += 15
    return score


class MarketScan(BaseModel):
    id: str
    countries: list[str] = Field(default_factory=lambda: ["us"])
    region_preset: str = Field(default_factory=get_default_region_preset)
    chart_types: list[str] = Field(default_factory=lambda: ["top-free"])
    per_genre_limit: int = Field(default=15, ge=1, le=100)
    enrich_top_n: int = 5
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: str = "running"  # running | completed | failed | cancelled
    phase: str = "fetch"  # fetch | analyze | done
    cancel_requested: bool = False
    analysis_batches_done: int = 0
    analysis_batches_total: int = 0
    focus_keyword: str | None = None
    scan_mode: str = "categories"  # keyword | categories | full
    selected_genre_ids: list[int] = Field(default_factory=list)
    categories: list[CategorySnapshot] = Field(default_factory=list)
    opportunities: list[DemandOpportunity] = Field(default_factory=list)
    logs: list[str] = Field(default_factory=list)
    error: str | None = None
    live_category_count: int | None = Field(default=None, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_data(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        if "country" in data and "countries" not in data:
            legacy = data.pop("country")
            data["countries"] = [legacy] if isinstance(legacy, str) else list(legacy)

        countries = data.get("countries") or ["us"]
        if not isinstance(countries, list):
            countries = [countries]

        has_blocked = any(str(code).lower() in _BLOCKED_REGIONS for code in countries)
        clean = [str(code).lower() for code in countries if str(code).lower() not in _BLOCKED_REGIONS]

        if has_blocked and not clean:
            data["countries"] = ["us"]
            data.setdefault("error", "历史扫描（中国区/港澳台），已不再支持")
            if data.get("status") not in ("failed",):
                data["status"] = "legacy_unsupported"
        elif has_blocked:
            data["countries"] = clean
        else:
            data["countries"] = [str(code).lower() for code in countries]

        default_country = data["countries"][0] if data.get("countries") else "us"
        for cat in data.get("categories") or []:
            if isinstance(cat, dict) and not cat.get("country"):
                cat["country"] = default_country

        return data

    @field_validator("countries")
    @classmethod
    def block_china(cls, codes: list[str]) -> list[str]:
        blocked = {"cn", "hk", "mo", "tw"}
        for code in codes:
            if code.lower() in blocked:
                raise ValueError("不支持中国大陆/港澳台区域，请使用美区或欧洲")
        return [c.lower() for c in codes]

    def log(self, message: str) -> None:
        ts = datetime.now(UTC).isoformat()
        self.logs.append(f"[{ts}] {message}")
        self.updated_at = datetime.now(UTC)


class ScanStore:
    def __init__(self, workspace: Path | None = None) -> None:
        root = workspace or settings.ensure_workspace()
        self.root = root / "scans"
        self.root.mkdir(parents=True, exist_ok=True)

    def scan_dir(self, scan_id: str) -> Path:
        path = self.root / scan_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def live_path(self, scan_id: str) -> Path:
        return self.scan_dir(scan_id) / "scan_live.json"

    def save_live(self, scan: MarketScan) -> Path:
        """轻量实时状态（不含榜单快照），供轮询快速读取。"""
        path = self.live_path(scan.id)
        payload = {
            "status": scan.status,
            "phase": scan.phase,
            "analysis_batches_done": scan.analysis_batches_done,
            "analysis_batches_total": scan.analysis_batches_total,
            "category_count": len(scan.categories),
            "opportunities": [o.model_dump() for o in scan.opportunities],
            "logs": scan.logs,
            "updated_at": scan.updated_at.isoformat(),
            "error": scan.error,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def clear_live(self, scan_id: str) -> None:
        self.live_path(scan_id).unlink(missing_ok=True)

    def _merge_live(self, scan: MarketScan) -> MarketScan:
        path = self.live_path(scan.id)
        if not path.exists():
            return scan
        try:
            live = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return scan

        for field in (
            "status",
            "phase",
            "analysis_batches_done",
            "analysis_batches_total",
            "error",
        ):
            if field in live and live[field] is not None:
                setattr(scan, field, live[field])
        if live.get("logs"):
            scan.logs = live["logs"]
        if live.get("category_count") is not None:
            scan.live_category_count = int(live["category_count"])
        if "opportunities" in live:
            scan.opportunities = [
                DemandOpportunity.model_validate(o) for o in live["opportunities"]
            ]
        if live.get("updated_at"):
            scan.updated_at = datetime.fromisoformat(live["updated_at"])
        return scan

    def save(self, scan: MarketScan) -> Path:
        path = self.scan_dir(scan.id) / "scan.json"
        path.write_text(scan.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load(self, scan_id: str) -> MarketScan:
        path = self.scan_dir(scan_id) / "scan.json"
        if not path.exists():
            raise FileNotFoundError(f"Scan not found: {scan_id}")
        scan = MarketScan.model_validate_json(path.read_text(encoding="utf-8"))
        return self._merge_live(scan)

    def list_scans(self) -> list[MarketScan]:
        results: list[MarketScan] = []
        if not self.root.exists():
            return results
        for child in sorted(self.root.iterdir(), reverse=True):
            scan_file = child / "scan.json"
            if not scan_file.exists():
                continue
            try:
                results.append(self.load(child.name))
            except Exception:
                continue
        return results


class MarketScanner:
    """全分类 App Store 市场扫描（美区 + 欧洲）。"""

    def __init__(self) -> None:
        self.store = ScanStore()
        self.llm = LLMClient()
        self.preferences = ScanPreferencesStore()
        self._last_live_flush_at = 0.0

    def _flush(self, scan: MarketScan, *, full: bool = False) -> None:
        """写入轻量实时状态；full=True 时同时落盘完整 scan 并清除 live 缓存。"""
        self.store.save_live(scan)
        if full:
            self.store.save(scan)
            self.store.clear_live(scan.id)

    def _flush_live(self, scan: MarketScan, *, force: bool = False) -> None:
        """节流写入 scan_live.json，供 Web 轮询实时日志与进度。"""
        now = time.monotonic()
        if not force and now - self._last_live_flush_at < 1.0:
            return
        self._last_live_flush_at = now
        self._flush(scan)

    def _append_snapshot_live(self, scan: MarketScan, snapshot: CategorySnapshot) -> None:
        scan.categories.append(snapshot)
        self._save_category_file(scan, snapshot)
        self._flush_live(scan)

    @staticmethod
    def _inject_keyword_search_jobs(
        jobs: list[_ChartFetchJob],
        scan: MarketScan,
        keyword: str,
    ) -> None:
        search_kw = normalize_search_keyword(keyword)
        if not search_kw:
            return
        for country in scan.countries:
            jobs.append(
                _ChartFetchJob(
                    country=country,
                    chart_type="search",
                    kind="search",
                    keyword=search_kw,
                )
            )

    def create_scan(
        self,
        *,
        countries: list[str],
        region_preset: str | None = None,
        chart_types: list[str] | None = None,
        per_genre_limit: int = 15,
        enrich_top_n: int = 5,
    ) -> MarketScan:
        charts = chart_types or ["top-free"]
        for chart in charts:
            if chart not in CHART_TYPES:
                raise ValueError(f"不支持的榜单类型: {chart}，可选: {', '.join(CHART_TYPES)}")

        scan = MarketScan(
            id=uuid.uuid4().hex[:12],
            countries=countries,
            region_preset=region_preset or get_default_region_preset(),
            chart_types=charts,
            per_genre_limit=per_genre_limit,
            enrich_top_n=enrich_top_n,
        )
        scan.log(f"创建扫描，区域={format_regions(countries)}，榜单={charts}")
        self._flush(scan, full=True)
        return scan

    async def _enrich_apps(self, client: AppStoreClient, apps: list[AppStoreApp], enrich_top_n: int) -> list[AppStoreApp]:
        if not apps or enrich_top_n <= 0:
            return apps
        ids = [app.app_id for app in apps[:enrich_top_n] if app.app_id]
        details = await client.lookup_apps(ids)
        detail_map = {d.app_id: d for d in details}
        enriched: list[AppStoreApp] = []
        for app in apps:
            detail = detail_map.get(app.app_id)
            if detail:
                enriched.append(
                    app.model_copy(
                        update={
                            "bundle_id": detail.bundle_id,
                            "rating": detail.rating,
                            "rating_count": detail.rating_count,
                            "description": detail.description,
                            "price": detail.price,
                            "screenshot_urls": detail.screenshot_urls,
                        }
                    )
                )
            else:
                enriched.append(app)
        return enriched

    async def _try_fetch_snapshot(
        self,
        scan: MarketScan,
        job: _ChartFetchJob,
        client: AppStoreClient,
    ) -> CategorySnapshot | None:
        label = CHART_LABELS.get(job.chart_type, job.chart_type)
        region = region_label(job.country)

        if job.kind == "search":
            apps = await client.search_apps(job.keyword, limit=scan.per_genre_limit)
            if not apps:
                return None
            apps = await self._enrich_apps(client, apps, scan.enrich_top_n)
            return CategorySnapshot(
                country=job.country,
                country_label=region,
                genre_id=0,
                genre_name=f"Search: {job.keyword}",
                genre_name_zh=f"搜索: {job.keyword}",
                chart_type="search",
                chart_label="关键词搜索",
                apps=apps,
            )

        if job.kind == "top":
            apps = await client.fetch_top_charts(job.chart_type, limit=scan.per_genre_limit)
            if not apps:
                return None
            if scan.enrich_top_n > 0:
                apps = await self._enrich_apps(client, apps, scan.enrich_top_n)
            return CategorySnapshot(
                country=job.country,
                country_label=region,
                genre_id=0,
                genre_name="All Apps",
                genre_name_zh="应用总榜",
                chart_type=job.chart_type,
                chart_label=label,
                apps=apps,
            )

        assert job.genre is not None
        apps = await client.fetch_genre_chart(
            job.genre,
            chart_type=job.chart_type,
            limit=scan.per_genre_limit,
        )
        if not apps:
            return None
        if scan.enrich_top_n > 0:
            apps = await self._enrich_apps(client, apps, scan.enrich_top_n)
        return CategorySnapshot(
            country=job.country,
            country_label=region,
            genre_id=job.genre.id,
            genre_name=job.genre.name,
            genre_name_zh=job.genre.name_zh,
            chart_type=job.chart_type,
            chart_label=label,
            apps=apps,
        )

    async def _fetch_snapshots_concurrent(
        self,
        scan: MarketScan,
        jobs: list[_ChartFetchJob],
    ) -> list[CategorySnapshot]:
        if not jobs:
            return []

        started = time.perf_counter()
        initial_concurrency = max(1, settings.appgen_scan_concurrency)
        governor = ScanFetchConcurrencyGovernor.create(initial_concurrency)
        active_limit = governor.active_limit
        requeue_count = 0
        permanent_failures = 0

        primary: deque[_PendingFetchJob] = deque(_PendingFetchJob(job) for job in jobs)
        retry: deque[_PendingFetchJob] = deque()
        snapshots: list[CategorySnapshot] = []

        ladder_text = "→".join(str(v) for v in governor.ladder)
        scan.log(
            f"并发拉取 {len(jobs)} 个榜单（阶梯 {ladder_text}，"
            f"初始={active_limit}；品类免费/付费榜走 marketing API；"
            f"限流阈值=当前并发的一半，连续 3 轮同并发全部成功可升档）…"
        )
        self._flush(scan)

        async with app_store_scan_pool(active_limit) as (http_client, sem):

            async def run_one(pending: _PendingFetchJob) -> tuple[_PendingFetchJob, CategorySnapshot | None, BaseException | None]:
                client = AppStoreClient(
                    country=pending.job.country,
                    http_client=http_client,
                    semaphore=sem,
                )
                try:
                    snap = await self._try_fetch_snapshot(scan, pending.job, client)
                    return pending, snap, None
                except Exception as exc:
                    return pending, None, exc

            in_flight: set[asyncio.Task] = set()
            wave_dispatched = 0
            wave_successes = 0
            wave_had_rate_limit = False

            while primary or retry or in_flight:
                if scan_cancel_requested(scan.id):
                    scan.log("拉取已停止（用户取消）")
                    self._flush(scan)
                    break

                if not primary and not in_flight and retry:
                    max_attempt = max(p.attempts for p in retry)
                    base = 2.0 if any(p.rate_limited for p in retry) else 0.5
                    delay = min(base * (2 ** (max_attempt - 1)), SCAN_FETCH_JOB_BACKOFF_CAP_SEC)
                    await asyncio.sleep(delay)
                    while retry:
                        primary.append(retry.popleft())

                if not in_flight and primary:
                    wave_dispatched = 0
                    wave_successes = 0
                    wave_had_rate_limit = False

                while primary and len(in_flight) < active_limit:
                    pending = primary.popleft()
                    in_flight.add(asyncio.create_task(run_one(pending)))
                    wave_dispatched += 1

                if not in_flight:
                    break

                done, in_flight = await asyncio.wait(
                    in_flight, return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    pending, snap, exc = task.result()
                    if snap is not None:
                        snapshots.append(snap)
                        self._append_snapshot_live(scan, snap)
                        wave_successes += 1
                        continue

                    if exc is not None and is_requeueable_fetch_error(exc):
                        if pending.attempts < SCAN_FETCH_MAX_JOB_RETRIES:
                            pending.attempts += 1
                            pending.rate_limited = is_rate_limited_fetch_error(exc)
                            retry.append(pending)
                            requeue_count += 1
                            wave_had_rate_limit = pending.rate_limited
                            if pending.rate_limited:
                                adj = governor.on_rate_limited()
                                if adj.delay_sec > 0:
                                    await asyncio.sleep(adj.delay_sec)
                                if adj.message:
                                    scan.log(adj.message)
                                    self._flush(scan)
                                active_limit = governor.active_limit
                            continue

                    permanent_failures += 1
                    job = pending.job
                    name = job.genre.name_zh if job.genre else job.kind
                    region = region_label(job.country)
                    label = CHART_LABELS.get(job.chart_type, job.chart_type)
                    if exc is not None and is_legacy_rss_blocked_error(exc):
                        err_text = "Apple 已关闭 itunes RSS（永久性失败，非并发问题）"
                    else:
                        err_text = format_scan_error(exc) if exc else "空结果"
                    scan.log(f"拉取失败 {region} / {name} / {label}: {err_text}")
                    self._flush_live(scan, force=True)

                if not in_flight and wave_dispatched > 0:
                    adj = governor.on_wave_complete(
                        dispatched=wave_dispatched,
                        successes=wave_successes,
                        had_rate_limit=wave_had_rate_limit,
                    )
                    if adj.message:
                        scan.log(adj.message)
                        self._flush(scan)
                    active_limit = governor.active_limit

        elapsed = time.perf_counter() - started
        failed = len(jobs) - len(snapshots)
        extra = []
        if failed:
            extra.append(f"{failed} 个失败")
        if requeue_count:
            extra.append(f"队尾重试 {requeue_count} 次")
        if active_limit != governor.initial_limit:
            extra.append(f"最终并发 {active_limit}（封顶 {governor.max_allowed}）")
        scan.log(
            f"榜单拉取完成：{len(snapshots)}/{len(jobs)} 成功，耗时 {elapsed:.1f}s"
            + (f"，{' · '.join(extra)}" if extra else "")
        )
        if not snapshots and scan_cancel_requested(scan.id):
            scan.log("拉取已取消，未获得任何榜单快照")
            self._flush(scan)
            raise ScanCancelledError()
        if not snapshots:
            raise RuntimeError("所有榜单请求均失败，请检查网络、代理或降低 APPGEN_SCAN_CONCURRENCY")
        self._flush(scan)
        return snapshots

    def _persist_snapshots(self, scan: MarketScan, snapshots: list[CategorySnapshot]) -> None:
        known = {(s.country, s.genre_id, s.chart_type) for s in scan.categories}
        for snapshot in snapshots:
            key = (snapshot.country, snapshot.genre_id, snapshot.chart_type)
            if key in known:
                continue
            scan.categories.append(snapshot)
            self._save_category_file(scan, snapshot)
            known.add(key)
        self._flush(scan, full=True)

    async def run_keyword_scan(self, scan: MarketScan, keyword: str) -> MarketScan:
        """关键词 + 免费/付费榜 Top N 的快速扫描（适合 Web 端）。"""
        keyword = keyword.strip()
        scan.focus_keyword = keyword
        scan.scan_mode = "keyword"

        try:
            register_scan_cancel(scan.id)
            jobs: list[_ChartFetchJob] = []
            for country in scan.countries:
                jobs.append(
                    _ChartFetchJob(
                        country=country,
                        chart_type="search",
                        kind="search",
                        keyword=keyword,
                    )
                )
                for chart_type in scan.chart_types:
                    jobs.append(
                        _ChartFetchJob(country=country, chart_type=chart_type, kind="top")
                    )

            snapshots = await self._fetch_snapshots_concurrent(scan, jobs)
            if scan_cancel_requested(scan.id):
                raise ScanCancelledError()
            self._persist_snapshots(scan, snapshots)

            scan.phase = "analyze"
            scan.log("榜单数据已就绪，准备机会分析…")
            self._flush(scan)

            scan.opportunities = await self._analyze_opportunities_incremental(
                scan, focus_keyword=keyword
            )
            if scan_cancel_requested(scan.id):
                raise ScanCancelledError()
            self._save_report(scan)
            scan.phase = "done"
            scan.status = "completed"
            scan.log(
                f"关键词扫描完成，{len(scan.countries)} 区域，"
                f"{len(scan.opportunities)} 条机会"
            )
        except ScanCancelledError:
            scan.cancel_requested = True
            scan.status = "cancelled"
            scan.phase = "done"
            if scan.categories and scan.opportunities:
                self._save_report(scan)
            scan.log(
                f"扫描已停止 · {len(scan.categories)} 个快照"
                + (f" · {len(scan.opportunities)} 条机会" if scan.opportunities else "")
            )
        except Exception as exc:
            scan.status = "failed"
            scan.error = format_scan_error(exc)
            scan.log(f"扫描失败: {scan.error}")
        finally:
            unregister_scan_cancel(scan.id)

        self._flush(scan, full=True)
        return scan

    async def run_keyword_scan_by_id(self, scan_id: str, keyword: str) -> MarketScan:
        scan = self.store.load(scan_id)
        return await self.run_keyword_scan(scan, keyword)

    async def run_scan(
        self,
        scan: MarketScan,
        *,
        genres: list[AppGenre] | None = None,
        skip_analyze: bool = False,
        focus_keyword: str | None = None,
    ) -> MarketScan:
        target_genres = genres or get_app_genres()
        keyword = focus_keyword or scan.focus_keyword

        try:
            register_scan_cancel(scan.id)
            jobs: list[_ChartFetchJob] = []
            skipped_grossing = 0
            for country in scan.countries:
                for genre in target_genres:
                    for chart_type in scan.chart_types:
                        if chart_type == CHART_TOP_GROSSING:
                            skipped_grossing += 1
                            continue
                        jobs.append(
                            _ChartFetchJob(
                                country=country,
                                chart_type=chart_type,
                                kind="genre",
                                genre=genre,
                            )
                        )
            if keyword:
                before = len(jobs)
                self._inject_keyword_search_jobs(jobs, scan, keyword)
                added = len(jobs) - before
                scan.log(
                    f"关注关键词「{keyword}」：已加入 {added} 个 App Store 搜索任务"
                    f"（搜索词: {normalize_search_keyword(keyword)}）"
                )
                self._flush(scan)
            if skipped_grossing:
                scan.log(
                    f"跳过 {skipped_grossing} 个品类畅销榜任务"
                    f"（Apple 已关闭 itunes RSS；免费/付费榜使用 marketing API）"
                )
                self._flush(scan)
            snapshots = await self._fetch_snapshots_concurrent(scan, jobs)
            if scan_cancel_requested(scan.id):
                raise ScanCancelledError()
            self._persist_snapshots(scan, snapshots)

            if not skip_analyze:
                scan.phase = "analyze"
                scan.log("榜单数据已就绪，准备机会分析…")
                self._flush(scan)

                scan.opportunities = await self._analyze_opportunities_incremental(
                    scan, focus_keyword=keyword
                )
                if scan_cancel_requested(scan.id):
                    raise ScanCancelledError()
                self._save_report(scan)
            scan.phase = "done"
            scan.status = "completed"
            scan.log(
                f"扫描完成，{len(scan.countries)} 个区域，"
                f"{len(scan.categories)} 个快照，{len(scan.opportunities)} 条机会"
            )
        except ScanCancelledError:
            scan.cancel_requested = True
            scan.status = "cancelled"
            scan.phase = "done"
            if scan.categories and scan.opportunities:
                self._save_report(scan)
            scan.log(
                f"扫描已停止 · {len(scan.categories)} 个快照"
                + (f" · {len(scan.opportunities)} 条机会" if scan.opportunities else "")
            )
        except Exception as exc:
            scan.status = "failed"
            scan.error = format_scan_error(exc)
            scan.log(f"扫描失败: {scan.error}")
        finally:
            unregister_scan_cancel(scan.id)

        self._flush(scan, full=True)
        return scan

    async def run_scan_by_id(
        self,
        scan_id: str,
        *,
        genres: list[AppGenre] | None = None,
        skip_analyze: bool = False,
        focus_keyword: str | None = None,
    ) -> MarketScan:
        scan = self.store.load(scan_id)
        return await self.run_scan(
            scan,
            genres=genres,
            skip_analyze=skip_analyze,
            focus_keyword=focus_keyword,
        )

    def _save_category_file(self, scan: MarketScan, snapshot: CategorySnapshot) -> None:
        name = f"{snapshot.country}_{snapshot.genre_id}_{snapshot.chart_type}.json"
        path = self.store.scan_dir(scan.id) / "categories" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")

    def _build_briefs(self, scan: MarketScan, *, focus_keyword: str | None = None) -> list[dict[str, Any]]:
        briefs: list[dict[str, Any]] = []
        for snap in scan.categories:
            if not snap.apps:
                continue
            top_apps = []
            for app in snap.apps[:5]:
                top_apps.append(
                    {
                        "name": app.name,
                        "rank": app.chart_rank,
                        "rating": app.rating,
                        "rating_count": app.rating_count,
                        "description": (app.description or "")[:280],
                    }
                )
            briefs.append(
                {
                    "country": snap.country,
                    "country_label": snap.country_label,
                    "genre": snap.genre_name,
                    "genre_zh": snap.genre_name_zh,
                    "chart": snap.chart_label,
                    "chart_type": snap.chart_type,
                    "top_apps": top_apps,
                }
            )

        total = len(briefs)
        max_briefs = normalize_analyze_max_snapshots(
            runtime_settings.get().analyze_max_snapshots,
            clamp=True,
        )
        stored_total = len(scan.categories)
        kw = (focus_keyword or scan.focus_keyword or "").strip()
        tokens = keyword_tokens(kw) if kw else []
        if total > max_briefs:
            if tokens:
                briefs.sort(key=lambda b: _brief_keyword_score(b, tokens), reverse=True)
                briefs = briefs[:max_briefs]
                scan.log(
                    f"分析采样 {len(briefs)}/{total} 个快照（优先匹配关键词 {tokens}）"
                    f"（全量 {stored_total} 个已保存，上限 {max_briefs}）"
                )
            else:
                step = max(1, total // max_briefs)
                briefs = briefs[::step][:max_briefs]
                scan.log(
                    f"分析采样 {len(briefs)}/{total} 个分类快照"
                    f"（全量 {stored_total} 个已保存，上限 {max_briefs}，控制 LLM 成本）"
                )
        elif stored_total > len(briefs):
            scan.log(f"将分析全部 {len(briefs)} 个有效快照（全量 {stored_total} 个已保存）")
        return briefs

    def _llm_analyze_batch_sync(
        self,
        briefs: list[dict[str, Any]],
        *,
        countries: list[str],
        focus_keyword: str | None,
        batch_no: int,
        batch_total: int,
    ) -> list[dict]:
        if not briefs:
            return []

        system = (
            "你是 App Store 市场分析专家，专注美国与欧洲市场。"
            "根据本批分类榜单数据，识别 3-8 个值得独立开发者切入的 Micro-App 机会。"
            "优先：评论/描述中暴露的痛点、巨头未覆盖的细分、可快速 MVP 的方向。"
            "避免：需要重运营/重内容/强网络效应的领域。"
            "每个机会必须在 pain_points 或 why_now 中引用本批 top_apps 的具体证据"
            "（应用名、评分、描述片段）；缺乏榜单证据的泛泛方向不要输出。"
            "你必须只输出一个 JSON 数组（以 [ 开头、以 ] 结尾），不要 markdown。"
            "数组每项字段：title, country, country_label, genre, genre_zh, chart_type, "
            "one_liner, pain_points(数组), reference_apps(数组), differentiation, "
            "confidence_score(0-100), suggested_keyword(英文), why_now。"
        )
        user = (
            f"批次 {batch_no}/{batch_total}\n"
            f"覆盖区域: {format_regions(countries)}\n"
            f"本批分类数据:\n{json.dumps(briefs, ensure_ascii=False, indent=2)}\n\n"
            "country/genre/chart_type 必须与输入一致；suggested_keyword 使用英文。"
        )
        if focus_keyword:
            tokens = keyword_tokens(focus_keyword)
            user += (
                f"\n用户关注方向: 「{focus_keyword}」（语义: {', '.join(tokens) or focus_keyword}）。"
                "\n硬性要求：仅输出与该方向直接相关的机会（如 relax/cozy/wellbeing/life/happy/mindful 等主题）。"
                "与关注方向无关的方向一律不要输出。"
            )
            system += (
                " 当用户指定关注方向时，禁止输出与该方向无关的机会；"
                "每条机会须能在本批 top_apps 中找到主题相关的应用证据。"
            )

        feedback_ctx = self.preferences.build_llm_context()
        if feedback_ctx:
            user += f"\n\n=== 用户历史偏好反馈 ===\n{feedback_ctx}\n"
            user += (
                "请严格参考上述反馈：bad 类方向默认排除；"
                "输出需引用本批榜单中的具体应用名/评分/描述作为 evidence。"
            )

        if not self.llm.enabled:
            return self._mock_opportunities(briefs)

        raw = self.llm.chat(system, user, temperature=0.35, json_mode=True)
        items = self._parse_opportunity_items(self.llm.extract_json_list(raw))
        items = self._filter_by_user_feedback(items)
        if not items:
            items = self._mock_opportunities(briefs)
        return items

    def _filter_by_user_feedback(self, items: list[dict]) -> list[dict]:
        kept: list[dict] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", ""))
            country = str(item.get("country", "us"))
            genre_zh = str(item.get("genre_zh", ""))
            chart_type = str(item.get("chart_type", "top-free"))
            if self.preferences.is_blocked(
                title=title,
                country=country,
                genre_zh=genre_zh,
                chart_type=chart_type,
            ):
                continue
            kept.append(item)
        return kept

    @staticmethod
    def _coerce_str_list(value: Any, *, dict_keys: tuple[str, ...] = ("name", "title", "text", "summary")) -> list[str]:
        """LLM 有时返回字符串数组，有时返回 {name: ...} 对象数组。"""
        if value is None:
            return []
        if isinstance(value, str):
            text = value.strip()
            return [text] if text else []
        if not isinstance(value, list):
            return [str(value).strip()] if str(value).strip() else []

        out: list[str] = []
        for entry in value:
            if isinstance(entry, str):
                text = entry.strip()
                if text:
                    out.append(text)
                continue
            if isinstance(entry, dict):
                parts: list[str] = []
                for key in dict_keys:
                    val = entry.get(key)
                    if isinstance(val, str) and val.strip():
                        parts.append(val.strip())
                        break
                if not parts:
                    for val in entry.values():
                        if isinstance(val, str) and val.strip():
                            parts.append(val.strip())
                            break
                if parts:
                    out.append(parts[0])
                continue
            text = str(entry).strip()
            if text:
                out.append(text)
        return out

    @staticmethod
    def _coerce_confidence(value: Any, default: int = 50) -> int:
        try:
            score = int(value)
        except (TypeError, ValueError):
            return default
        return max(0, min(100, score))

    def _items_to_opportunities(self, items: list[dict]) -> list[DemandOpportunity]:
        opportunities: list[DemandOpportunity] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            country = str(item.get("country") or "us")
            try:
                opportunities.append(
                    DemandOpportunity(
                        rank=0,
                        title=str(item.get("title") or "机会"),
                        country=country,
                        country_label=str(item.get("country_label") or region_label(country)),
                        genre=str(item.get("genre") or ""),
                        genre_zh=str(item.get("genre_zh") or ""),
                        chart_type=str(item.get("chart_type") or "top-free"),
                        one_liner=str(item.get("one_liner") or ""),
                        pain_points=self._coerce_str_list(item.get("pain_points")),
                        reference_apps=self._coerce_str_list(item.get("reference_apps")),
                        differentiation=str(item.get("differentiation") or ""),
                        confidence_score=self._coerce_confidence(item.get("confidence_score")),
                        suggested_keyword=str(item.get("suggested_keyword") or ""),
                        why_now=str(item.get("why_now") or ""),
                    )
                )
            except Exception:
                continue
        return opportunities

    @staticmethod
    def _opp_dedupe_key(opp: DemandOpportunity) -> str:
        return "|".join(
            [
                opp.title.strip().lower(),
                opp.country.lower(),
                opp.genre_zh.strip().lower(),
                opp.chart_type,
            ]
        )

    def _merge_opportunities(
        self,
        existing: list[DemandOpportunity],
        new_items: list[DemandOpportunity],
    ) -> list[DemandOpportunity]:
        merged = {self._opp_dedupe_key(o): o for o in existing}
        for opp in new_items:
            key = self._opp_dedupe_key(opp)
            prev = merged.get(key)
            if prev is None or opp.confidence_score > prev.confidence_score:
                merged[key] = opp
        return list(merged.values())

    def _rerank_opportunities(
        self,
        opportunities: list[DemandOpportunity],
        focus_keyword: str | None = None,
    ) -> list[DemandOpportunity]:
        ranked = list(opportunities)
        ranked.sort(key=lambda o: o.confidence_score, reverse=True)
        if focus_keyword:
            ranked = self._filter_by_keyword(ranked, focus_keyword, strict=True)
        for idx, opp in enumerate(ranked, start=1):
            opp.rank = idx
        return ranked

    async def _analyze_opportunities_incremental(
        self,
        scan: MarketScan,
        *,
        focus_keyword: str | None = None,
    ) -> list[DemandOpportunity]:
        briefs = self._build_briefs(scan, focus_keyword=focus_keyword)
        if not briefs:
            scan.log("分析跳过：无有效榜单快照（可能 App Store 请求失败）")
            scan.phase = "done"
            return []

        stored_snapshots = len(scan.categories)
        analyzed_snapshots = len(briefs)

        batch_size = max(1, settings.appgen_analyze_batch_size)
        batches = [briefs[i : i + batch_size] for i in range(0, len(briefs), batch_size)]
        concurrency = max(1, settings.appgen_analyze_concurrency)
        if self.llm.provider == "cursor":
            scan.log(
                f"Cursor CLI 错峰并发：{concurrency} 路，"
                f"启动间隔 {settings.appgen_cursor_launch_stagger_ms}ms + "
                f"随机 {settings.appgen_cursor_launch_jitter_ms}ms（不等 agent 结束）"
            )

        self._flush(scan)

        scan.phase = "analyze"
        scan.analysis_batches_total = len(batches)
        scan.analysis_batches_done = 0
        scan.opportunities = []
        scan.log(
            f"开始 LLM 分析（{len(batches)} 批，并发 {concurrency}）…"
        )
        self._flush(scan)

        sem = asyncio.Semaphore(concurrency)
        accumulator: list[DemandOpportunity] = []

        async def run_batch(batch_idx: int, batch_briefs: list[dict]) -> tuple[int, list[dict], str | None]:
            async with sem:
                try:
                    items = await asyncio.to_thread(
                        self._llm_analyze_batch_sync,
                        batch_briefs,
                        countries=scan.countries,
                        focus_keyword=focus_keyword,
                        batch_no=batch_idx + 1,
                        batch_total=len(batches),
                    )
                    return batch_idx, items, None
                except Exception as exc:
                    err = format_scan_error(exc)
                    if "password not found" in err.lower() or "access-token" in err.lower():
                        err += "；可增大 APPGEN_CURSOR_LAUNCH_STAGGER_MS 或改用 LLM_PROVIDER=openai"
                    return batch_idx, [], err

        batch_errors: list[str] = []
        cancelled = False
        with cursor_launch_wave():
            tasks = [asyncio.create_task(run_batch(i, b)) for i, b in enumerate(batches)]

            for finished in asyncio.as_completed(tasks):
                if scan_cancel_requested(scan.id):
                    cancelled = True
                    for t in tasks:
                        if not t.done():
                            t.cancel()
                    scan.log("LLM 分析已停止（用户取消）")
                    break
                _idx, items, err = await finished
                if err:
                    batch_errors.append(f"批次 {_idx + 1}: {err}")
                    scan.log(f"批次 {_idx + 1}/{len(batches)} 分析失败: {err}")
                    scan.analysis_batches_done += 1
                    self._flush(scan)
                    continue
                new_opps = self._items_to_opportunities(items)
                accumulator = self._merge_opportunities(accumulator, new_opps)
                accumulator = self._rerank_opportunities(accumulator, focus_keyword)
                scan.opportunities = accumulator
                scan.analysis_batches_done += 1
                scan.log(
                    f"分析进度 {scan.analysis_batches_done}/{scan.analysis_batches_total}，"
                    f"已发现 {len(accumulator)} 条机会"
                )
                self._flush(scan)

        if cancelled:
            if accumulator:
                final = self._rerank_opportunities(accumulator, focus_keyword)
                scan.opportunities = final
                scan.log(f"分析已停止，保留 {len(final)} 条已发现机会")
            else:
                scan.log("分析已停止，尚无机会结果")
            self._flush(scan)
            raise ScanCancelledError()

        if batch_errors and not accumulator:
            raise RuntimeError(batch_errors[0])
        if batch_errors:
            scan.log(f"部分批次失败（{len(batch_errors)}/{len(batches)}），已保留成功结果")

        final = self._rerank_opportunities(accumulator, focus_keyword)
        scan.opportunities = final
        scan.analysis_batches_done = scan.analysis_batches_total
        scan.log(
            f"LLM 分析完成，共 {len(final)} 条机会（已按分数重排）；"
            f"基于 {analyzed_snapshots}/{stored_snapshots} 个快照、{len(batches)} 批分析"
            f"（每批 LLM 输出约 3–8 条，非「一条快照一条机会」）"
        )
        self._flush(scan)
        return final

    async def _analyze_opportunities(
        self, scan: MarketScan, *, focus_keyword: str | None = None
    ) -> list[DemandOpportunity]:
        """兼容入口：走增量并发分析。"""
        return await self._analyze_opportunities_incremental(scan, focus_keyword=focus_keyword)

    @staticmethod
    def _parse_opportunity_items(data: Any) -> list[dict]:
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            for key in ("opportunities", "items", "results", "data"):
                val = data.get(key)
                if isinstance(val, list):
                    return [x for x in val if isinstance(x, dict)]
            if "title" in data or "one_liner" in data:
                return [data]
        return []

    def _filter_by_keyword(
        self,
        opportunities: list[DemandOpportunity],
        keyword: str,
        *,
        strict: bool = False,
    ) -> list[DemandOpportunity]:
        """关键词相关机会优先；strict=True 时剔除完全无关项。"""
        tokens = keyword_tokens(keyword)
        if not tokens:
            return opportunities

        def score(opp: DemandOpportunity) -> int:
            blob = " ".join(
                [
                    opp.title,
                    opp.one_liner,
                    opp.suggested_keyword,
                    opp.genre,
                    opp.genre_zh,
                    " ".join(opp.pain_points),
                    " ".join(opp.reference_apps),
                    opp.why_now,
                    opp.differentiation,
                ]
            ).lower()
            s = sum(3 for t in tokens if t in blob)
            norm_kw = normalize_search_keyword(keyword).lower()
            if norm_kw and norm_kw in blob:
                s += 5
            if opp.genre.lower().startswith("search"):
                s += 8
            return s

        if strict:
            matched = [o for o in opportunities if score(o) > 0]
            if matched:
                opportunities = matched

        opportunities.sort(key=lambda o: (score(o), o.confidence_score), reverse=True)
        return opportunities

    def _mock_opportunities(self, briefs: list[dict]) -> list[dict]:
        results = []
        for brief in briefs[:12]:
            apps = brief.get("top_apps", [])
            ref = [a["name"] for a in apps[:2] if a.get("name")]
            genre = brief.get("genre", "Productivity")
            results.append(
                {
                    "title": f"Focused {genre} tool",
                    "country": brief.get("country", "us"),
                    "country_label": brief.get("country_label", "美国 (us)"),
                    "genre": genre,
                    "genre_zh": brief.get("genre_zh", genre),
                    "chart_type": brief.get("chart_type", "top-free"),
                    "one_liner": f"Lean MVP experience in {genre} for {brief.get('country_label', 'US')}",
                    "pain_points": ["Bloated incumbents", "Ad-heavy UX", "Steep onboarding"],
                    "reference_apps": ref,
                    "differentiation": "No account, offline-first, single-purpose",
                    "confidence_score": 68 - len(results) * 2,
                    "suggested_keyword": genre.lower().split()[0],
                    "why_now": "Top charts show rating dispersion; room for a cleaner alternative",
                }
            )
        return results

    def _save_report(self, scan: MarketScan) -> None:
        lines = [
            "# App Store 市场扫描报告",
            "",
            f"- 扫描 ID: `{scan.id}`",
            f"- 区域: {format_regions(scan.countries)}",
            f"- 区域预设: {scan.region_preset}",
            f"- 榜单: {', '.join(scan.chart_types)}",
            f"- 快照数: {len(scan.categories)}",
            f"- 生成时间: {scan.updated_at.isoformat()}",
            "",
            "## 推荐机会（按置信度排序）",
            "",
        ]
        for opp in scan.opportunities:
            lines.extend(
                [
                    f"### {opp.rank}. {opp.title}（{opp.confidence_score} 分）",
                    "",
                    f"- **区域**: {opp.country_label}",
                    f"- **分类**: {opp.genre_zh} / {CHART_LABELS.get(opp.chart_type, opp.chart_type)}",
                    f"- **一句话**: {opp.one_liner}",
                    f"- **差异化**: {opp.differentiation}",
                    f"- **建议关键词**: `{opp.suggested_keyword}`",
                    f"- **为什么现在**: {opp.why_now}",
                    f"- **参考应用**: {', '.join(opp.reference_apps) or '-'}",
                    "",
                    "**痛点**:",
                ]
            )
            for pain in opp.pain_points:
                lines.append(f"- {pain}")
            lines.append("")

        lines.extend(
            [
                "## 下一步",
                "",
                "```bash",
                f"appgen scan pick {scan.id} <序号>",
                "```",
                "",
            ]
        )

        report_path = self.store.scan_dir(scan.id) / "scan_report.md"
        report_path.write_text("\n".join(lines), encoding="utf-8")

        opp_path = self.store.scan_dir(scan.id) / "opportunities.json"
        opp_path.write_text(
            json.dumps([o.model_dump() for o in scan.opportunities], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_scan(self, scan_id: str) -> MarketScan:
        return self.store.load(scan_id)

    def list_scans(self) -> list[MarketScan]:
        return self.store.list_scans()

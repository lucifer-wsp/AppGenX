from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from appgen.config import settings
from appgen.constants import (
    ANALYZE_MAX_SNAPSHOTS_MAX,
    ANALYZE_MAX_SNAPSHOTS_MIN,
    CHART_LABELS,
    CURSOR_CHAT_IDLE_TIMEOUT_SEC_MAX,
    CURSOR_CHAT_IDLE_TIMEOUT_SEC_MIN,
    CURSOR_CHAT_TIMEOUT_SEC_MAX,
    CURSOR_CHAT_TIMEOUT_SEC_MIN,
    PIPELINE_RESUME_STALE_MINUTES_MAX,
    PIPELINE_RESUME_STALE_MINUTES_MIN,
)
from appgen.discovery import MarketScanner
from appgen.llm import apply_runtime_settings
from appgen.models import PipelineStage
from appgen.pipeline import PipelineOrchestrator
from appgen.pipeline_tasks import is_pipeline_active, mark_pipeline_active, mark_pipeline_inactive
from appgen.runtime_settings import LLMProviderConfig, runtime_settings
from appgen.run_state import is_run_resumable, resume_block_reason
from appgen.scan_flow import pick_opportunity_and_run, plan_scan, start_market_scan
from appgen.scan_preferences import ScanPreferencesStore, opportunity_dedupe_key
from appgen.tools.genres import get_app_genres, get_popular_genre_ids
from appgen.run_views import (
    VIEW_SECTIONS,
    build_stage_progress,
    is_code_artifact,
    list_stage_documents,
    load_document,
    pending_review_stage,
    resolve_section_content,
    run_summary,
)

app = FastAPI(title="AppGen Agent", version="0.3.0")
orchestrator = PipelineOrchestrator()


async def _run_pipeline_background(run_id: str, runner) -> None:
    """同进程内登记活跃 run，避免重复 resume；结束时释放。"""
    if is_pipeline_active(run_id):
        return
    mark_pipeline_active(run_id)
    try:
        await runner()
    except Exception as exc:
        try:
            current = orchestrator.get_run(run_id)
            if current.status == "running":
                current.status = "failed"
                current.log(f"Pipeline: 后台任务异常 — {exc}")
                orchestrator.store.save_run(current)
        except Exception:
            pass
        raise
    finally:
        mark_pipeline_inactive(run_id)


def _resume_guard(run_id: str) -> None:
    run = orchestrator.get_run(run_id)
    stale = int(runtime_settings.get().pipeline_resume_stale_minutes)
    active = is_pipeline_active(run_id)
    if not is_run_resumable(run, stale_minutes=stale, pipeline_active=active):
        reason = resume_block_reason(run, stale_minutes=stale, pipeline_active=active) or "不可恢复"
        raise HTTPException(status_code=409, detail=reason)


_WEB_DIR = Path(__file__).parent
_STATIC = _WEB_DIR / "static"
_DIST = _STATIC / "dist"
_INDEX = _DIST / "index.html"
_ASSETS = _DIST / "assets"

if _ASSETS.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_ASSETS)), name="assets")
elif _STATIC.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


def _fallback_html() -> str:
    return """<!DOCTYPE html><html lang="zh-Hans"><head><meta charset="UTF-8"/>
<title>AppGen Agent</title></head><body style="font-family:system-ui;padding:2rem">
<h1>前端未构建</h1>
<p>请执行：<code>cd appgen/web/frontend && npm install && npm run build</code></p>
</body></html>"""


class CreateRunRequest(BaseModel):
    keyword: str | None = None
    category: str | None = None
    country: str = "us"
    auto_review: bool = False


class AutoReviewRequest(BaseModel):
    enabled: bool


class CreateScanRequest(BaseModel):
    keyword: str | None = None
    genre_ids: list[int] = []
    regions: str = "us"
    charts: list[str] = ["top-free", "top-paid"]
    limit: int = Field(default=10, ge=1, le=100)
    enrich: int = 5


class ScanEstimateRequest(BaseModel):
    keyword: str | None = None
    genre_ids: list[int] = []
    regions: str = "us"
    charts: list[str] = ["top-free", "top-paid"]


class PickScanRequest(BaseModel):
    rank: int
    auto_review: bool = False


class OpportunityFeedbackRequest(BaseModel):
    rank: int = Field(ge=1)
    verdict: str = Field(pattern="^(bad|good)$")
    reason: str = Field(default="", max_length=500)


class SettingsUpdateRequest(BaseModel):
    auto_review_default: bool | None = None
    llm_providers: list[LLMProviderConfig] | None = None
    llm_provider_mode: str | None = None
    rss_marketing_url: str | None = None
    rss_legacy_top_url: str | None = None
    rss_legacy_genre_url: str | None = None
    legacy_top_chart_types: list[str] | None = None
    genres: list[dict[str, Any]] | None = None
    popular_genre_ids: list[int] | None = None
    store_regions: list[dict[str, Any]] | None = None
    region_presets: dict[str, list[str]] | None = None
    default_region_preset: str | None = None
    scan_limit_min: int | None = None
    scan_limit_max: int | None = None
    default_scan_limit: int | None = None
    default_scan_enrich: int | None = None
    default_charts: list[str] | None = None
    scan_concurrency: int | None = None
    scan_max_concurrency: int | None = None
    analyze_batch_size: int | None = None
    analyze_concurrency: int | None = None
    analyze_max_snapshots: int | None = Field(
        None,
        ge=ANALYZE_MAX_SNAPSHOTS_MIN,
        le=ANALYZE_MAX_SNAPSHOTS_MAX,
    )
    cursor_launch_stagger_ms: int | None = None
    cursor_launch_jitter_ms: int | None = None
    cursor_chat_timeout_sec: int | None = Field(
        None,
        ge=CURSOR_CHAT_TIMEOUT_SEC_MIN,
        le=CURSOR_CHAT_TIMEOUT_SEC_MAX,
    )
    cursor_chat_idle_timeout_sec: int | None = Field(
        None,
        ge=CURSOR_CHAT_IDLE_TIMEOUT_SEC_MIN,
        le=CURSOR_CHAT_IDLE_TIMEOUT_SEC_MAX,
    )
    pipeline_resume_stale_minutes: int | None = Field(
        None,
        ge=PIPELINE_RESUME_STALE_MINUTES_MIN,
        le=PIPELINE_RESUME_STALE_MINUTES_MAX,
    )
    review_mode: str | None = None
    http_proxy: str | None = None
    serper_api_key: str | None = None
    workspace: str | None = None
    host: str | None = None
    port: int | None = None
    cursor_cwd: str | None = None


class ReviewRequest(BaseModel):
    notes: str = ""


@app.get("/")
async def dashboard():
    if _INDEX.is_file():
        return FileResponse(_INDEX)
    return HTMLResponse(_fallback_html())


@app.get("/api/runs")
async def list_runs() -> list[dict[str, Any]]:
    runs = orchestrator.list_runs()
    return [{**run_summary(run), "summary": {
        "keyword": run.seed_keyword,
        "opportunity": run.opportunity.title if run.opportunity else None,
        "product": run.prd.product_name if run.prd else None,
    }} for run in runs]


@app.post("/api/runs")
async def create_run(req: CreateRunRequest) -> dict[str, str]:
    settings.appgen_review_mode = "web"
    run = orchestrator.create_run(
        keyword=req.keyword,
        category=req.category,
        country=req.country,
        auto_review=req.auto_review,
    )

    async def _bg() -> None:
        async def _run() -> None:
            try:
                await orchestrator.run_until_pause(run)
            except Exception as exc:
                current = orchestrator.get_run(run.id)
                current.status = "failed"
                current.log(f"Pipeline: 未捕获异常 — {exc}")
                orchestrator.store.save_run(current)

        await _run_pipeline_background(run.id, _run)

    asyncio.create_task(_bg())
    return {"id": run.id, "status": "started"}


@app.get("/api/settings")
async def get_app_settings() -> dict[str, Any]:
    return runtime_settings.to_public_dict()


@app.put("/api/settings")
async def update_app_settings(req: SettingsUpdateRequest) -> dict[str, Any]:
    patch = req.model_dump(exclude_none=True)
    runtime_settings.update(patch, settings)
    apply_runtime_settings()
    return runtime_settings.to_public_dict()


@app.post("/api/settings/reload")
async def reload_app_settings() -> dict[str, Any]:
    runtime_settings.reload(settings)
    apply_runtime_settings()
    return runtime_settings.to_public_dict()


@app.get("/api/genres")
async def list_genres() -> dict[str, Any]:
    return {
        "genres": [
            {"id": g.id, "name": g.name, "name_zh": g.name_zh}
            for g in get_app_genres()
        ],
        "popular_ids": get_popular_genre_ids(),
    }


@app.post("/api/scans/estimate")
async def estimate_scan(req: ScanEstimateRequest) -> dict[str, Any]:
    try:
        return plan_scan(
            keyword=req.keyword,
            genre_ids=req.genre_ids,
            regions=req.regions,
            charts=req.charts or ["top-free", "top-paid"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/scans")
async def list_scans() -> list[dict[str, Any]]:
    scans = MarketScanner().list_scans()
    return [
        {
            "id": s.id,
            "status": s.status,
            "phase": s.phase,
            "focus_keyword": s.focus_keyword,
            "scan_mode": s.scan_mode,
            "genre_ids": s.selected_genre_ids,
            "regions": s.region_preset,
            "charts": s.chart_types,
            "category_count": len(s.categories),
            "opportunity_count": len(s.opportunities),
            "updated_at": s.updated_at.isoformat(),
            "error": s.error,
        }
        for s in scans
    ]


@app.post("/api/scans")
async def create_scan(req: CreateScanRequest) -> dict[str, Any]:
    try:
        return await start_market_scan(
            keyword=req.keyword,
            genre_ids=req.genre_ids,
            regions=req.regions,
            charts=req.charts,
            limit=req.limit,
            enrich=req.enrich,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/scans/{scan_id}")
async def get_scan(scan_id: str) -> dict[str, Any]:
    try:
        scan = MarketScanner().get_scan(scan_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    prefs = ScanPreferencesStore()
    fb_map = prefs.feedback_map_for_scan(scan_id)
    opportunities: list[dict[str, Any]] = []
    for opp in scan.opportunities:
        data = opp.model_dump()
        key = opportunity_dedupe_key(
            title=opp.title,
            country=opp.country,
            genre_zh=opp.genre_zh,
            chart_type=opp.chart_type,
        )
        fb = fb_map.get(key)
        if fb:
            data["feedback"] = {
                "id": fb.id,
                "verdict": fb.verdict,
                "reason": fb.reason,
            }
        opportunities.append(data)

    pref_summary = prefs.load()
    bad_count = sum(1 for f in pref_summary.feedbacks if f.verdict == "bad")
    good_count = sum(1 for f in pref_summary.feedbacks if f.verdict == "good")

    return {
        "id": scan.id,
        "status": scan.status,
        "phase": scan.phase,
        "analysis_batches_done": scan.analysis_batches_done,
        "analysis_batches_total": scan.analysis_batches_total,
        "focus_keyword": scan.focus_keyword,
        "scan_mode": scan.scan_mode,
        "genre_ids": scan.selected_genre_ids,
        "regions": scan.region_preset,
        "countries": scan.countries,
        "charts": scan.chart_types,
        "limit": scan.per_genre_limit,
        "error": scan.error,
        "logs": scan.logs[-80:],
        "category_count": scan.live_category_count or len(scan.categories),
        "opportunities": opportunities,
        "preference_stats": {"bad": bad_count, "good": good_count},
    }


@app.post("/api/scans/{scan_id}/cancel")
async def cancel_scan(scan_id: str) -> dict[str, Any]:
    """请求停止正在进行的扫描或 LLM 分析。"""
    from appgen.scan_cancel import request as cancel_request

    scanner = MarketScanner()
    try:
        scan = scanner.get_scan(scan_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if scan.status != "running":
        raise HTTPException(status_code=400, detail=f"扫描未在进行中，当前状态: {scan.status}")

    cancel_request(scan_id)
    scan.cancel_requested = True
    scan.log("收到停止请求，正在终止…")
    scanner._flush(scan)

    return {"id": scan_id, "status": "cancelling", "cancel_requested": True}


@app.post("/api/scans/{scan_id}/reanalyze")
async def reanalyze_scan(scan_id: str) -> dict[str, Any]:
    """对已采集榜单数据的扫描重新运行机会分析（无需重新拉榜）。"""
    from appgen.scan_errors import format_scan_error

    scanner = MarketScanner()
    try:
        scan = scanner.get_scan(scan_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if not scan.categories:
        raise HTTPException(status_code=400, detail="该扫描无榜单数据，请重新扫描")

    scan.status = "running"
    scan.phase = "analyze"
    scan.error = None
    scan.analysis_batches_done = 0
    scan.analysis_batches_total = 0
    scan.opportunities = []
    scan.log("开始重新分析（复用已采集榜单，无需重新拉取）…")
    scanner._flush(scan)

    async def _bg() -> None:
        from appgen.scan_cancel import ScanCancelledError, register as register_scan_cancel, unregister as unregister_scan_cancel

        bg = MarketScanner()
        register_scan_cancel(scan_id)
        try:
            current = bg.get_scan(scan_id)
            current.opportunities = await bg._analyze_opportunities_incremental(
                current, focus_keyword=current.focus_keyword
            )
            bg._save_report(current)
            current.phase = "done"
            current.status = "completed"
            current.log(f"重新分析完成，{len(current.opportunities)} 条机会")
        except ScanCancelledError:
            current = bg.get_scan(scan_id)
            current.cancel_requested = True
            current.status = "cancelled"
            current.phase = "done"
            if current.opportunities:
                bg._save_report(current)
            current.log(
                f"分析已停止 · 保留 {len(current.opportunities)} 条机会"
                if current.opportunities
                else "分析已停止"
            )
        except Exception as exc:
            current = bg.get_scan(scan_id)
            current.status = "failed"
            current.error = format_scan_error(exc)
            current.log(f"重新分析失败: {current.error}")
        finally:
            unregister_scan_cancel(scan_id)
        bg._flush(current, full=True)

    asyncio.create_task(_bg())
    return {"id": scan.id, "status": "started", "category_count": len(scan.categories)}


@app.get("/api/scan-preferences")
async def get_scan_preferences() -> dict[str, Any]:
    prefs = ScanPreferencesStore().load()
    return {
        "feedbacks": [f.model_dump() for f in prefs.feedbacks],
        "bad_count": sum(1 for f in prefs.feedbacks if f.verdict == "bad"),
        "good_count": sum(1 for f in prefs.feedbacks if f.verdict == "good"),
        "updated_at": prefs.updated_at.isoformat(),
    }


@app.post("/api/scans/{scan_id}/opportunities/feedback")
async def submit_opportunity_feedback(
    scan_id: str, req: OpportunityFeedbackRequest
) -> dict[str, Any]:
    scanner = MarketScanner()
    store = ScanPreferencesStore()
    try:
        scan = scanner.get_scan(scan_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    opp = next((o for o in scan.opportunities if o.rank == req.rank), None)
    if opp is None:
        raise HTTPException(status_code=404, detail=f"未找到序号 {req.rank} 的机会")

    from appgen.scan_preferences import OpportunityFeedback

    feedback = OpportunityFeedback(
        verdict=req.verdict,  # type: ignore[arg-type]
        reason=req.reason.strip(),
        scan_id=scan_id,
        dedupe_key=opportunity_dedupe_key(
            title=opp.title,
            country=opp.country,
            genre_zh=opp.genre_zh,
            chart_type=opp.chart_type,
        ),
        title=opp.title,
        genre_zh=opp.genre_zh,
        chart_type=opp.chart_type,
        one_liner=opp.one_liner,
        suggested_keyword=opp.suggested_keyword,
    )
    store.add_feedback(feedback)
    return {
        "id": feedback.id,
        "verdict": feedback.verdict,
        "dedupe_key": feedback.dedupe_key,
        "preference_stats": {
            "bad": sum(1 for f in store.load().feedbacks if f.verdict == "bad"),
            "good": sum(1 for f in store.load().feedbacks if f.verdict == "good"),
        },
    }


@app.delete("/api/scan-preferences/{feedback_id}")
async def delete_scan_preference(feedback_id: str) -> dict[str, str]:
    store = ScanPreferencesStore()
    prefs = store.load()
    if not any(f.id == feedback_id for f in prefs.feedbacks):
        raise HTTPException(status_code=404, detail="反馈不存在")
    store.remove_feedback(feedback_id)
    return {"status": "deleted"}


@app.post("/api/scans/{scan_id}/pick")
async def pick_scan_opportunity(scan_id: str, req: PickScanRequest) -> dict[str, Any]:
    try:
        return await pick_opportunity_and_run(
            scan_id, req.rank, orchestrator, auto_review=req.auto_review
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    try:
        run = orchestrator.get_run(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return run.model_dump(mode="json")


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str) -> StreamingResponse:
    """SSE：推送 run 日志与状态增量，DevCode 流式生成时替代纯轮询。"""

    async def event_stream():
        last_log_count = -1
        last_updated_at: str | None = None
        idle_ticks = 0
        while True:
            try:
                run = orchestrator.get_run(run_id)
            except FileNotFoundError:
                yield f"event: error\ndata: {json.dumps({'error': 'run not found'})}\n\n"
                break

            summary = run_summary(run)
            changed = (
                len(run.logs) != last_log_count
                or run.updated_at != last_updated_at
            )
            if changed:
                payload = {
                    "logs": run.logs[-80:],
                    "status": run.status,
                    "updated_at": run.updated_at,
                    "pipeline_active": summary.get("pipeline_active", False),
                    "active_stage": summary.get("active_stage"),
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                last_log_count = len(run.logs)
                last_updated_at = run.updated_at
                idle_ticks = 0
            else:
                idle_ticks += 1
                if idle_ticks % 15 == 0:
                    yield ": keepalive\n\n"

            terminal = run.status in {"completed", "failed", "paused"}
            if terminal and not summary.get("pipeline_active"):
                yield f"event: done\ndata: {json.dumps({'status': run.status})}\n\n"
                break

            await asyncio.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/runs/{run_id}/progress")
async def get_progress(run_id: str) -> list[dict[str, Any]]:
    try:
        run = orchestrator.get_run(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return build_stage_progress(run, orchestrator.store)


@app.get("/api/runs/{run_id}/stages/{stage}/documents")
async def get_stage_documents(run_id: str, stage: str) -> dict[str, Any]:
    try:
        run = orchestrator.get_run(run_id)
        ps = PipelineStage(stage)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    docs = list_stage_documents(run, orchestrator.store, ps)
    summary = orchestrator.review.stage_summary(run, ps)
    review = None
    for gate in reversed(run.reviews):
        if gate.stage == ps:
            review = {
                "status": gate.status.value,
                "notes": gate.reviewer_notes,
                "reviewed_at": gate.reviewed_at.isoformat() if gate.reviewed_at else None,
            }
            break

    return {
        "stage": stage,
        "summary": summary,
        "review": review,
        "documents": docs,
    }


@app.get("/api/runs/{run_id}/documents/{doc_name:path}")
async def get_document(run_id: str, doc_name: str) -> dict[str, Any]:
    try:
        return load_document(orchestrator.store, run_id, doc_name)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/sections/{section}")
async def get_section(run_id: str, section: str) -> dict[str, Any]:
    if section not in VIEW_SECTIONS:
        raise HTTPException(status_code=400, detail=f"未知板块: {section}")
    try:
        run = orchestrator.get_run(run_id)
        return resolve_section_content(orchestrator.store, run, section)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/artifacts/{artifact_name:path}")
async def get_artifact(run_id: str, artifact_name: str) -> dict[str, Any]:
    if is_code_artifact(artifact_name):
        raise HTTPException(status_code=403, detail="代码产物请在本机 IDE 中查看")
    try:
        return load_document(orchestrator.store, run_id, artifact_name)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/review/{stage}/summary")
async def review_summary(run_id: str, stage: str) -> dict[str, str]:
    try:
        run = orchestrator.get_run(run_id)
        summary = orchestrator.review.stage_summary(run, PipelineStage(stage))
        return {"stage": stage, "summary": summary}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


async def _submit_review_action(run_id: str, stage: str, action: str, notes: str) -> dict[str, str]:
    try:
        final = await orchestrator.submit_review(run_id, PipelineStage(stage), action, notes)
        return {"status": final.status, "current_stage": final.current_stage.value}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/runs/{run_id}/review/{stage}/approve")
async def approve_review(run_id: str, stage: str, req: ReviewRequest) -> dict[str, str]:
    return await _submit_review_action(run_id, stage, "approve", req.notes)


@app.post("/api/runs/{run_id}/review/{stage}/revise")
async def revise_review(run_id: str, stage: str, req: ReviewRequest) -> dict[str, str]:
    return await _submit_review_action(run_id, stage, "revise", req.notes)


@app.post("/api/runs/{run_id}/review/{stage}/reject")
async def reject_review(run_id: str, stage: str, req: ReviewRequest) -> dict[str, str]:
    return await _submit_review_action(run_id, stage, "reject", req.notes)


@app.patch("/api/runs/{run_id}/auto-review")
async def set_run_auto_review(run_id: str, req: AutoReviewRequest) -> dict[str, Any]:
    """开启/关闭当前运行的一键通过；开启时自动批准待审节点并继续。"""
    try:
        final = await orchestrator.set_auto_review(run_id, req.enabled)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "auto_review": bool(final.metadata.get("auto_review")),
        "status": final.status,
        "current_stage": final.current_stage.value,
        "pending_review": (
            pending_review_stage(final).value if pending_review_stage(final) else None
        ),
    }


@app.post("/api/runs/{run_id}/resume")
async def resume_run(run_id: str) -> dict[str, str]:
    try:
        run = orchestrator.get_run(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if run.status == "completed":
        return {"status": "completed"}

    _resume_guard(run_id)

    async def _bg() -> None:
        async def _run() -> None:
            try:
                await orchestrator.resume(run_id)
            except Exception as exc:
                current = orchestrator.get_run(run_id)
                current.status = "failed"
                current.log(f"Pipeline: 恢复执行异常 — {exc}")
                orchestrator.store.save_run(current)

        await _run_pipeline_background(run_id, _run)

    asyncio.create_task(_bg())
    return {"status": "resuming"}

"""流水线运行状态推断（进度展示、恢复执行共用）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from appgen.constants import DEFAULT_PIPELINE_RESUME_STALE_MINUTES
from appgen.models import PipelineRun, PipelineStage, ReviewStatus
from appgen.pipeline_tasks import is_pipeline_active

PIPELINE_STAGE_ORDER: list[PipelineStage] = [
    PipelineStage.SCOUT,
    PipelineStage.ANALYST,
    PipelineStage.PM,
    PipelineStage.DESIGNER,
    PipelineStage.DEV_INIT,
    PipelineStage.DEV_SCAFFOLD,
    PipelineStage.DEV_CODE,
    PipelineStage.DEV_VERIFY,
    PipelineStage.QA,
    PipelineStage.STORE,
]

META_ACTIVE_STAGE = "active_stage"
META_STAGE_STARTED_AT = "active_stage_started_at"
META_STAGE_HEARTBEAT_AT = "active_stage_heartbeat_at"


def stage_approved(run: PipelineRun, stage: PipelineStage) -> bool:
    return any(g.stage == stage and g.status == ReviewStatus.APPROVED for g in run.reviews)


def next_pipeline_stage(stage: PipelineStage) -> PipelineStage | None:
    try:
        idx = PIPELINE_STAGE_ORDER.index(stage)
    except ValueError:
        return None
    nxt = idx + 1
    if nxt >= len(PIPELINE_STAGE_ORDER):
        return None
    return PIPELINE_STAGE_ORDER[nxt]


def mark_stage_started(run: PipelineRun, stage: PipelineStage) -> None:
    """记录当前阶段开始执行时间（用于 stale 判定）。"""
    now = datetime.now(UTC).isoformat()
    run.metadata[META_ACTIVE_STAGE] = stage.value
    run.metadata[META_STAGE_STARTED_AT] = now
    run.metadata[META_STAGE_HEARTBEAT_AT] = now


def touch_stage_heartbeat(run: PipelineRun) -> None:
    """阶段执行中产生日志时刷新心跳，避免长任务误显示恢复按钮。"""
    if run.metadata.get(META_ACTIVE_STAGE) != run.current_stage.value:
        return
    run.metadata[META_STAGE_HEARTBEAT_AT] = datetime.now(UTC).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        text = value.replace("Z", "+00:00")
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def stage_activity_at(run: PipelineRun) -> datetime:
    """当前阶段最近一次活动时刻（心跳 > 开始时间 > run.updated_at）。"""
    same_stage = run.metadata.get(META_ACTIVE_STAGE) == run.current_stage.value
    candidates: list[datetime] = [run.updated_at]
    if same_stage:
        for key in (META_STAGE_HEARTBEAT_AT, META_STAGE_STARTED_AT):
            parsed = _parse_iso(run.metadata.get(key))
            if parsed is not None:
                candidates.append(parsed)
    return max(candidates)


def is_stage_stale(run: PipelineRun, stale_minutes: int) -> bool:
    if stale_minutes <= 0:
        return True
    threshold = timedelta(minutes=stale_minutes)
    return datetime.now(UTC) - stage_activity_at(run) >= threshold


def resolve_active_stage(run: PipelineRun) -> PipelineStage | None:
    """实际应处于的执行阶段（含 orphaned running；Review 刚通过但未切 stage 时不超前标记）。"""
    if run.status != "running":
        return None
    if stage_approved(run, run.current_stage):
        nxt = next_pipeline_stage(run.current_stage)
        if nxt is None:
            return None
        from appgen.runtime_settings import runtime_settings

        stale = int(runtime_settings.get().pipeline_resume_stale_minutes)
        if is_pipeline_active(run.id) or is_stage_stale(run, stale):
            return nxt
        return None
    return run.current_stage


def _running_resume_allowed(run: PipelineRun, *, stale_minutes: int, pipeline_active: bool) -> bool:
    """running 状态下是否满足恢复条件（case 2/3 共用 stale + 非本进程活跃）。"""
    if pipeline_active:
        return False
    if not is_stage_stale(run, stale_minutes):
        return False
    if stage_approved(run, run.current_stage):
        return next_pipeline_stage(run.current_stage) is not None
    return True


def is_run_resumable(
    run: PipelineRun,
    *,
    stale_minutes: int = DEFAULT_PIPELINE_RESUME_STALE_MINUTES,
    pipeline_active: bool | None = None,
) -> bool:
    """是否应展示「恢复执行」并允许 resume API。"""
    if run.status in {"paused", "failed"}:
        return True
    if run.status != "running":
        return False

    active = is_pipeline_active(run.id) if pipeline_active is None else pipeline_active
    return _running_resume_allowed(run, stale_minutes=stale_minutes, pipeline_active=active)


def resume_block_reason(
    run: PipelineRun,
    *,
    stale_minutes: int = DEFAULT_PIPELINE_RESUME_STALE_MINUTES,
    pipeline_active: bool | None = None,
) -> str | None:
    """不可恢复时的说明；可恢复则返回 None。"""
    if is_run_resumable(run, stale_minutes=stale_minutes, pipeline_active=pipeline_active):
        return None
    if run.status == "completed":
        return "流水线已完成"
    active = is_pipeline_active(run.id) if pipeline_active is None else pipeline_active
    if run.status == "running" and active:
        return "流水线正在本机后台执行中"
    if run.status == "running" and not is_stage_stale(run, stale_minutes):
        activity = stage_activity_at(run)
        elapsed = datetime.now(UTC) - activity
        remain = max(0, int(stale_minutes * 60 - elapsed.total_seconds()))
        mins = (remain + 59) // 60
        hint = "（含 Review 通过后等待切 stage 的窗口）" if stage_approved(run, run.current_stage) else ""
        return (
            f"当前阶段仍在等待超时窗口{hint}（约 {mins} 分钟后可恢复，"
            f"阈值 {stale_minutes} 分钟）"
        )
    return "当前状态不可恢复"

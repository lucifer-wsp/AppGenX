from datetime import UTC, datetime, timedelta

import pytest

from appgen.models import PipelineRun, PipelineStage, ReviewGate, ReviewStatus
from appgen.pipeline import PipelineOrchestrator
from appgen.pipeline_tasks import mark_pipeline_active, mark_pipeline_inactive
from appgen.run_state import (
    is_run_resumable,
    is_stage_stale,
    mark_stage_started,
    resolve_active_stage,
)
from appgen.run_views import build_stage_progress


@pytest.fixture
def mock_settings(tmp_path, monkeypatch):
    from appgen.config import settings
    from appgen.llm import apply_runtime_settings
    from appgen.runtime_settings import runtime_settings

    monkeypatch.setenv("APPGEN_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("APPGEN_REVIEW_MODE", "auto")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    settings.appgen_workspace = tmp_path
    settings.appgen_review_mode = "auto"
    settings.llm_provider = "mock"
    runtime_settings.apply_env_settings(settings)
    apply_runtime_settings()


def _approved_gate(stage: PipelineStage) -> ReviewGate:
    return ReviewGate(stage=stage, status=ReviewStatus.APPROVED, reviewer_notes="auto")


def _apply_stale(run: PipelineRun, *, minutes_ago: float) -> None:
    old = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    iso = old.isoformat()
    run.metadata["active_stage_started_at"] = iso
    run.metadata["active_stage_heartbeat_at"] = iso
    run.updated_at = old


def _stage_run(stage: PipelineStage, *, minutes_ago: float = 0) -> PipelineRun:
    run = PipelineRun(id="stale-test", status="running", current_stage=stage)
    mark_stage_started(run, stage)
    if minutes_ago > 0:
        _apply_stale(run, minutes_ago=minutes_ago)
    return run


def _orphan_after_scaffold(*, minutes_ago: float = 9) -> PipelineRun:
    run = PipelineRun(id="orphan-scaffold", status="running", current_stage=PipelineStage.DEV_SCAFFOLD)
    mark_stage_started(run, PipelineStage.DEV_SCAFFOLD)
    run.reviews = [_approved_gate(PipelineStage.DEV_SCAFFOLD)]
    if minutes_ago > 0:
        _apply_stale(run, minutes_ago=minutes_ago)
    return run


@pytest.mark.asyncio
async def test_resume_orphaned_running_after_scaffold(mock_settings, tmp_path):
    """dev_scaffold 已通过且超过 stale 窗口时，resume 应从 dev_code 继续。"""
    from appgen.config import settings
    from appgen.models import DesignSpec, DevInitPlan, PRDDocument

    settings.appgen_workspace = tmp_path
    orch = PipelineOrchestrator()
    run = orch.create_run(keyword="mixer", country="us", auto_review=True)
    run.status = "running"
    run.current_stage = PipelineStage.DEV_SCAFFOLD
    run.prd = PRDDocument(product_name="MixApp", tagline="mix", background="test", mvp_features=["a"])
    run.design = DesignSpec(screens=[])
    run.dev_plan = DevInitPlan(bundle_id="com.test.mix", scheme_name="MixApp")
    run.reviews = [
        _approved_gate(PipelineStage.SCOUT),
        _approved_gate(PipelineStage.ANALYST),
        _approved_gate(PipelineStage.PM),
        _approved_gate(PipelineStage.DESIGNER),
        _approved_gate(PipelineStage.DEV_INIT),
        _approved_gate(PipelineStage.DEV_SCAFFOLD),
    ]
    _apply_stale(run, minutes_ago=9)
    orch.store.save_run(run)
    project = tmp_path / "runs" / run.id / "project"
    project.mkdir(parents=True)
    (project / "project.yml").write_text("name: Test\n", encoding="utf-8")

    final = await orch.resume(run.id)

    assert final.status == "completed"
    assert final.dev_code_manifest is not None
    assert any("恢复执行（从 dev_code）" in line for line in final.logs)


def test_case2_fresh_after_approval_not_resumable():
    run = _orphan_after_scaffold(minutes_ago=0)
    assert is_run_resumable(run, stale_minutes=8, pipeline_active=False) is False
    assert resolve_active_stage(run) is None


def test_case2_stale_orphan_resumable():
    run = _orphan_after_scaffold(minutes_ago=9)
    assert is_run_resumable(run, stale_minutes=8, pipeline_active=False) is True
    assert resolve_active_stage(run) == PipelineStage.DEV_CODE

    progress = build_stage_progress(run)
    code_row = next(r for r in progress if r["stage"] == "dev_code")
    assert code_row["status"] == "running"


def test_case3_fresh_running_not_resumable():
    run = _stage_run(PipelineStage.DEV_CODE, minutes_ago=0)
    assert is_stage_stale(run, 8) is False
    assert is_run_resumable(run, stale_minutes=8, pipeline_active=False) is False


def test_case3_stale_running_resumable():
    run = _stage_run(PipelineStage.DEV_CODE, minutes_ago=9)
    assert is_stage_stale(run, 8) is True
    assert is_run_resumable(run, stale_minutes=8, pipeline_active=False) is True


def test_case3_active_task_blocks_resume():
    run = _stage_run(PipelineStage.DEV_CODE, minutes_ago=9)
    mark_pipeline_active(run.id)
    try:
        assert is_run_resumable(run, stale_minutes=8, pipeline_active=True) is False
    finally:
        mark_pipeline_inactive(run.id)


def test_case2_active_task_blocks_resume_even_if_stale():
    run = _orphan_after_scaffold(minutes_ago=9)
    assert is_run_resumable(run, stale_minutes=8, pipeline_active=True) is False

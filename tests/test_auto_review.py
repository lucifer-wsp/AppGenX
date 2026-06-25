import pytest

from appgen.models import PipelineRun, PipelineStage, ReviewGate, ReviewStatus
from appgen.pipeline import PipelineOrchestrator
from appgen.review import ReviewManager, is_auto_review


@pytest.fixture
def mock_settings(tmp_path, monkeypatch):
    from appgen.config import settings
    from appgen.llm import apply_runtime_settings
    from appgen.runtime_settings import runtime_settings

    monkeypatch.setenv("APPGEN_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("APPGEN_REVIEW_MODE", "web")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("CURSOR_API_KEY", "")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    settings.llm_provider = "mock"
    settings.cursor_api_key = ""
    settings.llm_api_key = ""
    settings.appgen_workspace = tmp_path
    settings.appgen_review_mode = "web"
    runtime_settings.apply_env_settings(settings)
    apply_runtime_settings()


def test_is_auto_review_from_metadata():
    run = PipelineRun(id="x", metadata={"auto_review": True})
    assert is_auto_review(run) is True


@pytest.mark.asyncio
async def test_auto_review_skips_web_pause(mock_settings, tmp_path):
    from appgen.config import settings

    settings.appgen_workspace = tmp_path
    settings.appgen_review_mode = "web"

    orch = PipelineOrchestrator()
    run = orch.create_run(keyword="pomodoro", country="us", auto_review=True)
    final = await orch.run_until_pause(run)

    assert final.status == "completed"
    assert all(g.status == ReviewStatus.APPROVED for g in final.reviews)


@pytest.mark.asyncio
async def test_set_auto_review_approves_pending(mock_settings, tmp_path):
    from appgen.config import settings

    settings.appgen_workspace = tmp_path
    settings.appgen_review_mode = "web"

    orch = PipelineOrchestrator()
    run = orch.create_run(keyword="test")
    run.opportunity = __import__("appgen.llm", fromlist=["LLMClient"]).LLMClient().chat_json(
        "x", "x", __import__("appgen.models", fromlist=["OpportunityBrief"]).OpportunityBrief
    )
    run.reviews.append(ReviewGate(stage=PipelineStage.SCOUT, status=ReviewStatus.PENDING))
    run.status = "paused"
    orch.store.save_run(run)

    final = await orch.set_auto_review(run.id, True)
    assert final.metadata.get("auto_review") is True
    assert any(
        g.stage == PipelineStage.SCOUT and g.status == ReviewStatus.APPROVED for g in final.reviews
    )

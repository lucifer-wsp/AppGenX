import pytest

from appgen.llm import LLMClient
from appgen.models import OpportunityBrief, PipelineRun, RequirementSpec
from appgen.pipeline import PipelineOrchestrator
from appgen.storage import ArtifactStore


@pytest.fixture
def mock_settings(tmp_path, monkeypatch):
    from appgen.config import settings
    from appgen.llm import apply_runtime_settings
    from appgen.runtime_settings import runtime_settings

    monkeypatch.setenv("APPGEN_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("APPGEN_REVIEW_MODE", "auto")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("CURSOR_API_KEY", "")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    settings.llm_provider = "mock"
    settings.cursor_api_key = ""
    settings.llm_api_key = ""
    settings.appgen_workspace = tmp_path
    settings.appgen_review_mode = "auto"
    runtime_settings.apply_env_settings(settings)
    apply_runtime_settings()


def test_llm_mock_opportunity(monkeypatch):
    from appgen.config import settings
    from appgen.llm import apply_runtime_settings
    from appgen.runtime_settings import runtime_settings

    monkeypatch.setenv("CURSOR_API_KEY", "")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    settings.llm_provider = "mock"
    settings.cursor_api_key = ""
    settings.llm_api_key = ""
    runtime_settings.apply_env_settings(settings)
    apply_runtime_settings()
    client = LLMClient()
    client.reset()
    result = client.chat_json(
        "你是 Scout",
        "输出 OpportunityBrief",
        OpportunityBrief,
    )
    assert result.title
    assert result.confidence_score >= 0


@pytest.mark.asyncio
async def test_pipeline_mock_run(mock_settings, tmp_path):
    from appgen.config import settings

    settings.appgen_workspace = tmp_path
    settings.appgen_review_mode = "auto"

    orch = PipelineOrchestrator()
    run = orch.create_run(keyword="pomodoro", country="us")
    final = await orch.run_until_pause(run)

    assert final.status == "completed"
    assert final.opportunity is not None
    assert final.prd is not None
    assert final.dev_plan is not None
    assert final.dev_code_manifest is not None
    assert final.build_report is not None
    assert final.build_report.success
    assert final.test_plan is not None
    assert final.store_listing is not None
    assert (tmp_path / "runs" / final.id / "03_prd.md").exists()
    assert (tmp_path / "runs" / final.id / "project" / "project.yml").exists()


def test_artifact_store_roundtrip(tmp_path):
    store = ArtifactStore(tmp_path)
    run = PipelineRun(id="test123", seed_keyword="focus")
    store.save_run(run)
    loaded = store.load_run("test123")
    assert loaded.id == "test123"
    assert loaded.seed_keyword == "focus"

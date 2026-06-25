import pytest

from appgen.agents.scout import ScoutAgent
from appgen.llm import LLMClient
from appgen.models import PipelineRun
from appgen.storage import ArtifactStore


@pytest.mark.asyncio
async def test_scout_skips_llm_when_picked(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    store = ArtifactStore(tmp_path)
    agent = ScoutAgent(LLMClient(), store)
    run = PipelineRun(
        id="picktest",
        seed_keyword="period tracker offline",
        metadata={
            "country": "us",
            "picked_from_scan": "scan123",
            "picked_opportunity": {
                "rank": 1,
                "title": "Privacy Period Tracker",
                "country": "us",
                "genre": "Health & Fitness",
                "genre_zh": "健康健美",
                "chart_type": "top-free",
                "one_liner": "Local-first",
                "pain_points": ["Privacy"],
                "reference_apps": ["Flo"],
                "differentiation": "Offline",
                "confidence_score": 86,
                "suggested_keyword": "period tracker offline",
                "why_now": "Trend",
            },
        },
    )
    result = await agent.run(run)
    assert result.opportunity is not None
    assert result.opportunity.title == "Privacy Period Tracker"
    assert "复用扫描机会" in result.logs[-1]

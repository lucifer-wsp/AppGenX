import pytest

from appgen.llm import LLMCallError, LLMClient
from appgen.models import PRDDocument, RequirementSpec


def test_contextual_mock_follows_opportunity(monkeypatch):
    from appgen.config import settings
    from appgen.llm import apply_runtime_settings
    from appgen.runtime_settings import runtime_settings

    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("CURSOR_API_KEY", "")
    settings.llm_provider = "mock"
    settings.llm_api_key = ""
    settings.cursor_api_key = ""
    runtime_settings.apply_env_settings(settings)
    apply_runtime_settings()

    client = LLMClient()
    client.reset()
    client.set_pipeline_context(
        seed_keyword="cozy plant idle game",
        opportunity={
            "title": "植物微养护放置",
            "one_liner": "一盆虚拟绿植、每日浇水一分钟",
            "category": "Games",
            "differentiation_angle": "单盆植物成长循环",
            "pain_points": ["现有放置游戏过于复杂"],
        },
    )

    req = client.chat_json("x", "x", RequirementSpec)
    assert "植物" in req.problem_statement or "绿植" in req.problem_statement

    client.set_pipeline_context(requirements=req.model_dump())
    prd = client.chat_json("x", "x", PRDDocument)
    assert prd.product_name == "CozyPlantIdleGame"
    assert prd.product_name != "FocusCalm"
    assert "FocusCalm" not in prd.tagline


def test_configured_provider_failure_raises(monkeypatch):
    from appgen.config import settings
    from appgen.llm import apply_runtime_settings
    from appgen.runtime_settings import LLMProviderConfig, runtime_settings

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "sk-proj-simulation-configured-key-abc1234567890")
    settings.llm_provider = "openai"
    settings.llm_api_key = "sk-proj-simulation-configured-key-abc1234567890"
    runtime_settings.apply_env_settings(settings)
    runtime_settings.update(
        {
            "llm_providers": [
                LLMProviderConfig(
                    provider="openai",
                    api_key="sk-proj-simulation-configured-key-abc1234567890",
                    model="gpt-4o-mini",
                )
            ]
        },
        settings,
    )
    apply_runtime_settings()

    client = LLMClient()
    client.reset()

    def fake_chat(*args, **kwargs):
        return '{"message": "mock"}'

    monkeypatch.setattr(client, "chat", fake_chat)

    with pytest.raises(LLMCallError):
        client.chat_json("x", "x", RequirementSpec)

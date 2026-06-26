from types import SimpleNamespace

from appgen.constants import LLM_PROFILE_ANALYZE, LLM_PROFILE_CODE, LLM_PROFILE_DEFAULT
from appgen.llm import build_provider_chain, resolve_provider
from appgen.runtime_settings import (
    LLMProviderConfig,
    RuntimeSettingsManager,
    merge_stage_providers_with_fallback,
    stage_llm_providers_from_env,
)


def test_stage_llm_providers_from_env_overrides_models_only():
    base = [
        LLMProviderConfig(provider="cursor", api_key="cursor_real_key_123456", model="composer-2.5"),
        LLMProviderConfig(
            provider="openai",
            api_key="sk-proj-real-openai-key-not-test-value",
            base_url="https://api.openai.com/v1",
            model="gpt-4o-mini",
        ),
    ]
    analyze = stage_llm_providers_from_env(base, cursor_model="", openai_model="gpt-4o-mini-analyze")
    assert len(analyze) == 2
    assert analyze[0].model == "composer-2.5"
    assert analyze[1].model == "gpt-4o-mini-analyze"
    assert analyze[1].api_key == base[1].api_key


def test_merge_stage_providers_inherits_api_keys():
    stage = [LLMProviderConfig(provider="openai", model="gpt-4o-analyze")]
    fallback = [
        LLMProviderConfig(
            provider="openai",
            api_key="sk-proj-real-openai-key-not-test-value",
            base_url="https://api.openai.com/v1",
            model="gpt-4o-mini",
        )
    ]
    merged = merge_stage_providers_with_fallback(stage, fallback)
    assert merged[0].api_key == fallback[0].api_key
    assert merged[0].model == "gpt-4o-analyze"


def test_build_provider_chain_uses_analyze_profile(tmp_path, monkeypatch):
    ws = tmp_path / "workspace"
    ws.mkdir()
    mgr = RuntimeSettingsManager()
    env = SimpleNamespace(
        appgen_workspace=ws,
        cursor_api_key="",
        cursor_model="composer-2.5",
        cursor_analyze_model="",
        cursor_code_model="",
        llm_api_key="sk-proj-real-openai-key-not-test-value",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o-mini",
        llm_analyze_model="gpt-4o-analyze",
        llm_code_model="gpt-4o-code",
        llm_provider="openai",
        appgen_scan_concurrency=10,
        appgen_scan_max_concurrency=20,
        appgen_analyze_batch_size=6,
        appgen_analyze_concurrency=3,
        appgen_cursor_launch_stagger_ms=2500,
        appgen_cursor_launch_jitter_ms=400,
        appgen_cursor_chat_timeout_sec=600,
        appgen_cursor_chat_idle_timeout_sec=120,
        appgen_default_regions="us-eu",
        appgen_review_mode="web",
        appgen_http_proxy="",
        serper_api_key="",
        appgen_host="127.0.0.1",
        appgen_port=8787,
        cursor_cwd=None,
    )
    mgr.bootstrap_from_env(env)
    monkeypatch.setattr("appgen.llm.runtime_settings", mgr)

    default_chain = build_provider_chain(LLM_PROFILE_DEFAULT)
    analyze_chain = build_provider_chain(LLM_PROFILE_ANALYZE)
    code_chain = build_provider_chain(LLM_PROFILE_CODE)

    assert default_chain[0].model == "gpt-4o-mini"
    assert analyze_chain[0].model == "gpt-4o-analyze"
    assert code_chain[0].model == "gpt-4o-code"
    assert resolve_provider(LLM_PROFILE_ANALYZE) == "openai"

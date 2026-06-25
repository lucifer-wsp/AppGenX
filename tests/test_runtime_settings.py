import json
from types import SimpleNamespace

from appgen.constants import LLM_PROVIDER_CURSOR, LLM_PROVIDER_OPENAI
from appgen.runtime_settings import (
    RuntimeSettings,
    RuntimeSettingsManager,
    _chain_has_usable_providers,
    _is_suspicious_llm_key,
)


def test_suspicious_llm_key_detects_test_placeholders():
    assert _is_suspicious_llm_key("sk-test-real-looking")
    assert _is_suspicious_llm_key("cursor_test_key")
    assert _is_suspicious_llm_key("sk-proj-openai-invalid-key-abcdef1234567890")
    assert not _is_suspicious_llm_key("sk-proj-real-key-example")


def test_imports_llm_from_env_when_settings_has_only_test_key(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "settings.json").write_text(
        json.dumps(
            {
                "llm_provider_mode": "openai",
                "llm_providers": [
                    {"provider": "openai", "api_key": "sk-test-real-looking", "model": "gpt-4o-mini"}
                ],
                "workspace": str(ws),
            }
        ),
        encoding="utf-8",
    )
    env = SimpleNamespace(
        appgen_workspace=ws,
        cursor_api_key="crsr_valid_migration_key_1234567890",
        cursor_model="composer-2.5",
        llm_api_key="",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o-mini",
        llm_provider="auto",
        appgen_scan_concurrency=10,
        appgen_scan_max_concurrency=20,
        appgen_analyze_batch_size=6,
        appgen_analyze_concurrency=3,
        appgen_cursor_launch_stagger_ms=2500,
        appgen_cursor_launch_jitter_ms=400,
        appgen_default_regions="us-eu",
        appgen_review_mode="web",
        appgen_http_proxy="",
        serper_api_key="",
        appgen_host="127.0.0.1",
        appgen_port=8787,
        cursor_cwd=None,
    )

    mgr = RuntimeSettingsManager()
    mgr.bootstrap_from_env(env)

    assert mgr.get().llm_provider_mode == "auto"
    assert len(mgr.get().llm_providers) == 1
    assert mgr.get().llm_providers[0].provider == LLM_PROVIDER_CURSOR
    assert mgr.get().llm_providers[0].api_key.startswith("crsr_")

    saved = json.loads((ws / "settings.json").read_text(encoding="utf-8"))
    assert saved["llm_providers"][0]["provider"] == LLM_PROVIDER_CURSOR


def test_keeps_real_openai_key_in_settings_over_env(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    real_key = "sk-proj-real-openai-key-not-test-value"
    (ws / "settings.json").write_text(
        json.dumps(
            {
                "llm_provider_mode": "openai",
                "llm_providers": [{"provider": "openai", "api_key": real_key, "model": "gpt-4o-mini"}],
                "workspace": str(ws),
            }
        ),
        encoding="utf-8",
    )
    env = SimpleNamespace(
        appgen_workspace=ws,
        cursor_api_key="crsr_other_key_1234567890",
        cursor_model="composer-2.5",
        llm_api_key="",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o-mini",
        llm_provider="auto",
        appgen_scan_concurrency=10,
        appgen_scan_max_concurrency=20,
        appgen_analyze_batch_size=6,
        appgen_analyze_concurrency=3,
        appgen_cursor_launch_stagger_ms=2500,
        appgen_cursor_jitter_ms=400,
        appgen_default_regions="us-eu",
        appgen_review_mode="web",
        appgen_http_proxy="",
        serper_api_key="",
        appgen_host="127.0.0.1",
        appgen_port=8787,
        cursor_cwd=None,
    )
    env.appgen_cursor_launch_jitter_ms = 400

    mgr = RuntimeSettingsManager()
    mgr.bootstrap_from_env(env)

    assert mgr.get().llm_providers[0].api_key == real_key
    assert _chain_has_usable_providers(mgr.get().llm_providers)


def test_creates_settings_json_from_env_when_missing(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    env = SimpleNamespace(
        appgen_workspace=ws,
        cursor_api_key="crsr_bootstrap_key_1234567890",
        cursor_model="composer-2.5",
        llm_api_key="",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o-mini",
        llm_provider="auto",
        appgen_scan_concurrency=10,
        appgen_scan_max_concurrency=20,
        appgen_analyze_batch_size=6,
        appgen_analyze_concurrency=3,
        appgen_cursor_launch_stagger_ms=2500,
        appgen_cursor_launch_jitter_ms=400,
        appgen_default_regions="us-eu",
        appgen_review_mode="web",
        appgen_http_proxy="",
        serper_api_key="",
        appgen_host="127.0.0.1",
        appgen_port=8787,
        cursor_cwd=None,
    )

    mgr = RuntimeSettingsManager()
    mgr.bootstrap_from_env(env)

    assert (ws / "settings.json").is_file()
    saved = json.loads((ws / "settings.json").read_text(encoding="utf-8"))
    assert saved["llm_providers"][0]["provider"] == LLM_PROVIDER_CURSOR

from unittest.mock import patch

import pytest

from appgen.llm import LLMClient
from appgen.constants import LLM_PROVIDER_OPENAI


def test_cursor_chat_passes_api_key_flag(monkeypatch):
    monkeypatch.setenv("CURSOR_API_KEY", "cursor_test_key")
    from appgen.config import settings

    settings.cursor_api_key = "cursor_test_key"
    settings.cursor_model = "composer-2.5"

    with patch("appgen.llm_cursor._resolve_agent_bin", return_value="/usr/bin/agent"), patch(
        "appgen.llm_cursor._run_agent_stream", return_value='[{"title":"Test"}]'
    ) as stream_mock:
        from appgen.llm_cursor import cursor_chat

        out = cursor_chat("sys", "user", json_mode=True)

    assert out == '[{"title":"Test"}]'
    cmd = stream_mock.call_args[0][0]
    assert "--api-key" in cmd
    assert "cursor_test_key" in cmd
    assert "--trust" in cmd
    assert "stream-json" in cmd


def test_llm_falls_back_to_openai_on_cursor_auth_error(monkeypatch):
    cursor_key = "crsr_prod_cursor_key_abcdefghij"
    openai_key = "sk-proj-simulation-fallback-key-abc1234567890"
    monkeypatch.setenv("LLM_PROVIDER", "cursor")
    monkeypatch.setenv("CURSOR_API_KEY", cursor_key)
    monkeypatch.setenv("LLM_API_KEY", openai_key)

    from appgen.config import settings
    from appgen.llm import apply_runtime_settings
    from appgen.runtime_settings import LLMProviderConfig, runtime_settings

    settings.llm_provider = "cursor"
    settings.cursor_api_key = cursor_key
    settings.llm_api_key = openai_key
    runtime_settings.apply_env_settings(settings)
    runtime_settings.update(
        {
            "llm_provider_mode": "cursor",
            "llm_providers": [
                LLMProviderConfig(
                    provider="cursor",
                    api_key=cursor_key,
                    model="composer-2.5",
                ),
                LLMProviderConfig(
                    provider="openai",
                    api_key=openai_key,
                    base_url="https://api.openai.com/v1",
                    model="gpt-4o-mini",
                ),
            ],
        },
        settings,
    )
    apply_runtime_settings()

    client = LLMClient()
    client.reset()

    with patch(
        "appgen.llm_cursor.cursor_available_with",
        return_value=True,
    ), patch(
        "appgen.llm_cursor.cursor_chat_with",
        side_effect=RuntimeError(
            "Cursor CLI 失败 (exit 1): Password not found for account 'cursor-user'"
        ),
    ), patch.object(client, "_openai_chat_with", return_value='{"ok": true}') as openai_mock:
        out = client.chat("sys", "user")

    assert out == '{"ok": true}'
    assert client.provider == LLM_PROVIDER_OPENAI
    openai_mock.assert_called_once()


def test_launch_stagger_assigns_increasing_slots(monkeypatch):
    from appgen.config import settings
    from appgen.runtime_settings import runtime_settings
    from appgen.llm_cursor import cursor_launch_wave, reset_cursor_launch_stagger

    settings.appgen_cursor_launch_stagger_ms = 1000
    settings.appgen_cursor_launch_jitter_ms = 0
    runtime_settings.apply_env_settings(settings)
    sleeps: list[float] = []

    def fake_sleep(sec: float) -> None:
        sleeps.append(sec)

    monkeypatch.setattr("appgen.llm_cursor.time.sleep", fake_sleep)

    with cursor_launch_wave():
        from appgen.llm_cursor import _wait_launch_stagger

        _wait_launch_stagger()
        _wait_launch_stagger()
        _wait_launch_stagger()

    assert sleeps == [1.0, 2.0]

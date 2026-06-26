from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from appgen.constants import (
    DEFAULT_ANALYZE_BATCH_SIZE,
    DEFAULT_ANALYZE_CONCURRENCY,
    DEFAULT_CURSOR_CHAT_IDLE_TIMEOUT_SEC,
    DEFAULT_CURSOR_CHAT_TIMEOUT_SEC,
    DEFAULT_CURSOR_LAUNCH_JITTER_MS,
    DEFAULT_CURSOR_LAUNCH_STAGGER_MS,
    DEFAULT_CURSOR_MODEL,
    DEFAULT_DEFAULT_REGIONS,
    DEFAULT_HOST,
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_PROVIDER_MODE,
    DEFAULT_PORT,
    DEFAULT_REVIEW_MODE,
    DEFAULT_SCAN_CONCURRENCY,
    DEFAULT_SCAN_MAX_CONCURRENCY,
    DEFAULT_WORKSPACE,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_api_key: str = ""
    llm_base_url: str = DEFAULT_LLM_BASE_URL
    llm_model: str = DEFAULT_LLM_MODEL
    llm_provider: str = DEFAULT_LLM_PROVIDER_MODE

    cursor_api_key: str = ""
    cursor_model: str = DEFAULT_CURSOR_MODEL
    cursor_analyze_model: str = ""
    cursor_code_model: str = ""
    cursor_cwd: Path | None = None

    llm_analyze_model: str = ""
    llm_code_model: str = ""

    serper_api_key: str = ""

    appgen_workspace: Path = Path(DEFAULT_WORKSPACE)
    appgen_host: str = DEFAULT_HOST
    appgen_port: int = DEFAULT_PORT
    appgen_review_mode: str = DEFAULT_REVIEW_MODE
    appgen_default_regions: str = DEFAULT_DEFAULT_REGIONS
    appgen_http_proxy: str = ""
    appgen_scan_concurrency: int = DEFAULT_SCAN_CONCURRENCY
    appgen_scan_max_concurrency: int = DEFAULT_SCAN_MAX_CONCURRENCY
    appgen_analyze_batch_size: int = DEFAULT_ANALYZE_BATCH_SIZE
    appgen_analyze_concurrency: int = DEFAULT_ANALYZE_CONCURRENCY
    appgen_cursor_launch_stagger_ms: int = DEFAULT_CURSOR_LAUNCH_STAGGER_MS
    appgen_cursor_launch_jitter_ms: int = DEFAULT_CURSOR_LAUNCH_JITTER_MS
    appgen_cursor_chat_timeout_sec: int = DEFAULT_CURSOR_CHAT_TIMEOUT_SEC
    appgen_cursor_chat_idle_timeout_sec: int = DEFAULT_CURSOR_CHAT_IDLE_TIMEOUT_SEC

    @property
    def templates_dir(self) -> Path:
        return Path(__file__).parent / "templates"

    def ensure_workspace(self) -> Path:
        self.appgen_workspace.mkdir(parents=True, exist_ok=True)
        return self.appgen_workspace


settings = Settings()


def bootstrap_runtime_settings() -> None:
    from appgen.runtime_settings import runtime_settings

    runtime_settings.bootstrap_from_env(settings)


bootstrap_runtime_settings()

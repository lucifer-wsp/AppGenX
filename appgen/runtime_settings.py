"""运行时配置：合并 .env 默认值与 workspace/settings.json，支持热更新。"""

from __future__ import annotations

import json
import re
import threading
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from appgen.constants import (
    ANALYZE_MAX_SNAPSHOTS_MAX,
    ANALYZE_MAX_SNAPSHOTS_MIN,
    CHART_RSS_SLUGS,
    DEFAULT_ANALYZE_BATCH_SIZE,
    DEFAULT_ANALYZE_CONCURRENCY,
    DEFAULT_ANALYZE_MAX_SNAPSHOTS,
    DEFAULT_APP_GENRES,
    DEFAULT_CHART_TYPES,
    CURSOR_CHAT_IDLE_TIMEOUT_SEC_MAX,
    CURSOR_CHAT_IDLE_TIMEOUT_SEC_MIN,
    CURSOR_CHAT_TIMEOUT_SEC_MAX,
    CURSOR_CHAT_TIMEOUT_SEC_MIN,
    DEFAULT_CURSOR_CHAT_IDLE_TIMEOUT_SEC,
    DEFAULT_CURSOR_CHAT_TIMEOUT_SEC,
    DEFAULT_CURSOR_LAUNCH_JITTER_MS,
    DEFAULT_CURSOR_LAUNCH_STAGGER_MS,
    DEFAULT_CURSOR_MODEL,
    DEFAULT_DEFAULT_REGIONS,
    DEFAULT_HOST,
    DEFAULT_LEGACY_TOP_CHART_TYPES,
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_PROVIDER_MODE,
    DEFAULT_PIPELINE_RESUME_STALE_MINUTES,
    DEFAULT_POPULAR_GENRE_IDS,
    DEFAULT_PORT,
    DEFAULT_REGION_PRESET,
    DEFAULT_REGION_PRESETS,
    DEFAULT_REVIEW_MODE,
    DEFAULT_RSS_LEGACY_GENRE_URL,
    DEFAULT_RSS_LEGACY_TOP_URL,
    DEFAULT_RSS_MARKETING_URL,
    DEFAULT_SCAN_CONCURRENCY,
    DEFAULT_SCAN_ENRICH_TOP_N,
    DEFAULT_SCAN_LIMIT,
    DEFAULT_SCAN_MAX_CONCURRENCY,
    DEFAULT_STORE_REGIONS,
    DEFAULT_WORKSPACE,
    LLM_PROVIDER_CURSOR,
    LLM_PROVIDER_MOCK,
    LLM_PROVIDER_OPENAI,
    PIPELINE_RESUME_STALE_MINUTES_MAX,
    PIPELINE_RESUME_STALE_MINUTES_MIN,
    PLACEHOLDER_CURSOR_KEY,
    PLACEHOLDER_OPENAI_KEY,
    SCAN_LIMIT_MAX,
    SCAN_LIMIT_MIN,
    SETTINGS_FILENAME,
    SUSPICIOUS_LLM_KEY_PREFIXES,
    SUSPICIOUS_LLM_KEYS,
)


class GenreConfig(BaseModel):
    id: int
    name: str
    name_zh: str
    search_term: str


class StoreRegionConfig(BaseModel):
    code: str
    name: str
    name_zh: str


class LLMProviderConfig(BaseModel):
    provider: str
    api_key: str = ""
    base_url: str = ""
    model: str = ""


def _default_genres() -> list[GenreConfig]:
    return [GenreConfig.model_validate(g) for g in DEFAULT_APP_GENRES]


def _default_regions() -> list[StoreRegionConfig]:
    return [StoreRegionConfig.model_validate(r) for r in DEFAULT_STORE_REGIONS]


def _default_region_presets() -> dict[str, list[str]]:
    return deepcopy(DEFAULT_REGION_PRESETS)


class RuntimeSettings(BaseModel):
    auto_review_default: bool = False
    llm_providers: list[LLMProviderConfig] = Field(default_factory=list)

    rss_marketing_url: str = DEFAULT_RSS_MARKETING_URL
    rss_legacy_top_url: str = DEFAULT_RSS_LEGACY_TOP_URL
    rss_legacy_genre_url: str = DEFAULT_RSS_LEGACY_GENRE_URL
    legacy_top_chart_types: list[str] = Field(
        default_factory=lambda: list(DEFAULT_LEGACY_TOP_CHART_TYPES)
    )

    genres: list[GenreConfig] = Field(default_factory=_default_genres)
    popular_genre_ids: list[int] = Field(default_factory=lambda: list(DEFAULT_POPULAR_GENRE_IDS))
    store_regions: list[StoreRegionConfig] = Field(default_factory=_default_regions)
    region_presets: dict[str, list[str]] = Field(default_factory=_default_region_presets)
    default_region_preset: str = DEFAULT_REGION_PRESET

    scan_limit_min: int = SCAN_LIMIT_MIN
    scan_limit_max: int = SCAN_LIMIT_MAX
    default_scan_limit: int = DEFAULT_SCAN_LIMIT
    default_scan_enrich: int = DEFAULT_SCAN_ENRICH_TOP_N
    default_charts: list[str] = Field(default_factory=lambda: list(DEFAULT_CHART_TYPES))

    scan_concurrency: int = DEFAULT_SCAN_CONCURRENCY
    scan_max_concurrency: int = DEFAULT_SCAN_MAX_CONCURRENCY
    analyze_batch_size: int = DEFAULT_ANALYZE_BATCH_SIZE
    analyze_concurrency: int = DEFAULT_ANALYZE_CONCURRENCY
    analyze_max_snapshots: int = Field(
        default=DEFAULT_ANALYZE_MAX_SNAPSHOTS,
        ge=ANALYZE_MAX_SNAPSHOTS_MIN,
        le=ANALYZE_MAX_SNAPSHOTS_MAX,
    )
    cursor_launch_stagger_ms: int = DEFAULT_CURSOR_LAUNCH_STAGGER_MS
    cursor_launch_jitter_ms: int = DEFAULT_CURSOR_LAUNCH_JITTER_MS
    cursor_chat_timeout_sec: int = Field(
        default=DEFAULT_CURSOR_CHAT_TIMEOUT_SEC,
        ge=CURSOR_CHAT_TIMEOUT_SEC_MIN,
        le=CURSOR_CHAT_TIMEOUT_SEC_MAX,
    )
    cursor_chat_idle_timeout_sec: int = Field(
        default=DEFAULT_CURSOR_CHAT_IDLE_TIMEOUT_SEC,
        ge=CURSOR_CHAT_IDLE_TIMEOUT_SEC_MIN,
        le=CURSOR_CHAT_IDLE_TIMEOUT_SEC_MAX,
    )
    pipeline_resume_stale_minutes: int = DEFAULT_PIPELINE_RESUME_STALE_MINUTES

    llm_provider_mode: str = DEFAULT_LLM_PROVIDER_MODE
    review_mode: str = DEFAULT_REVIEW_MODE
    http_proxy: str = ""
    serper_api_key: str = ""
    workspace: str = DEFAULT_WORKSPACE
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    cursor_cwd: str | None = None

    updated_at: str | None = None


def _is_real_secret(value: str, placeholder: str) -> bool:
    text = (value or "").strip()
    return bool(text) and text != placeholder


def _is_suspicious_llm_key(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return True
    lowered = text.lower()
    if lowered in SUSPICIOUS_LLM_KEYS:
        return True
    if any(lowered.startswith(prefix) for prefix in SUSPICIOUS_LLM_KEY_PREFIXES):
        return True
    return bool(
        re.search(
            r"(unit[_-]?test|fallbacktest|failconfigured|invalid-key|openai-chain|invalid_key)",
            lowered,
        )
    )


def _provider_entry_usable(entry: LLMProviderConfig) -> bool:
    key = (entry.api_key or "").strip()
    if _is_suspicious_llm_key(key):
        return False
    if entry.provider == LLM_PROVIDER_CURSOR:
        return _is_real_secret(key, PLACEHOLDER_CURSOR_KEY)
    if entry.provider == LLM_PROVIDER_OPENAI:
        return _is_real_secret(key, PLACEHOLDER_OPENAI_KEY)
    return False


def _chain_has_usable_providers(providers: list[LLMProviderConfig]) -> bool:
    return any(_provider_entry_usable(entry) for entry in providers)


def default_llm_providers_from_env(
    *,
    cursor_api_key: str = "",
    cursor_model: str = DEFAULT_CURSOR_MODEL,
    openai_api_key: str = "",
    openai_base_url: str = DEFAULT_LLM_BASE_URL,
    openai_model: str = DEFAULT_LLM_MODEL,
) -> list[LLMProviderConfig]:
    chain: list[LLMProviderConfig] = []
    if _is_real_secret(cursor_api_key, PLACEHOLDER_CURSOR_KEY):
        chain.append(
            LLMProviderConfig(
                provider=LLM_PROVIDER_CURSOR,
                api_key=cursor_api_key.strip(),
                model=(cursor_model or DEFAULT_CURSOR_MODEL).strip(),
            )
        )
    if _is_real_secret(openai_api_key, PLACEHOLDER_OPENAI_KEY):
        chain.append(
            LLMProviderConfig(
                provider=LLM_PROVIDER_OPENAI,
                api_key=openai_api_key.strip(),
                base_url=(openai_base_url or DEFAULT_LLM_BASE_URL).strip(),
                model=(openai_model or DEFAULT_LLM_MODEL).strip(),
            )
        )
    return chain


def _mask_secret(value: str) -> dict[str, Any]:
    text = (value or "").strip()
    if not text:
        return {"set": False, "preview": ""}
    if len(text) <= 8:
        return {"set": True, "preview": "****"}
    return {"set": True, "preview": f"{text[:4]}…{text[-4:]}"}


class RuntimeSettingsManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._data: RuntimeSettings = RuntimeSettings()
        self._path: Path | None = None
        self._bootstrapped = False

    def bootstrap_from_env(self, env_settings: Any) -> RuntimeSettings:
        with self._lock:
            if self._bootstrapped:
                return self._data
            workspace = Path(getattr(env_settings, "appgen_workspace", DEFAULT_WORKSPACE))
            self._path = workspace / SETTINGS_FILENAME
            env_base = self._settings_from_env(env_settings, workspace)
            created_new = False
            if self._path.is_file():
                try:
                    raw = json.loads(self._path.read_text(encoding="utf-8"))
                    merged = env_base.model_dump()
                    merged.update({k: v for k, v in raw.items() if v is not None})
                    self._clamp_legacy_settings(merged)
                    self._data = RuntimeSettings.model_validate(merged)
                except Exception:
                    self._data = env_base
            else:
                self._data = env_base
                created_new = True
            self._sanitize_region_defaults()
            if self._maybe_import_llm_from_env(env_settings):
                created_new = False
            if created_new or (self._path and not self._path.is_file()):
                self._data.updated_at = datetime.now(UTC).isoformat()
                self._save()
            self._bootstrapped = True
            self._sync_legacy_settings(env_settings)
            return self._data

    @staticmethod
    def _settings_from_env(env_settings: Any, workspace: Path) -> RuntimeSettings:
        return RuntimeSettings(
            auto_review_default=False,
            llm_providers=default_llm_providers_from_env(
                cursor_api_key=getattr(env_settings, "cursor_api_key", ""),
                cursor_model=getattr(env_settings, "cursor_model", DEFAULT_CURSOR_MODEL),
                openai_api_key=getattr(env_settings, "llm_api_key", ""),
                openai_base_url=getattr(env_settings, "llm_base_url", DEFAULT_LLM_BASE_URL),
                openai_model=getattr(env_settings, "llm_model", DEFAULT_LLM_MODEL),
            ),
            scan_concurrency=int(getattr(env_settings, "appgen_scan_concurrency", DEFAULT_SCAN_CONCURRENCY)),
            scan_max_concurrency=int(
                getattr(env_settings, "appgen_scan_max_concurrency", DEFAULT_SCAN_MAX_CONCURRENCY)
            ),
            analyze_batch_size=int(
                getattr(env_settings, "appgen_analyze_batch_size", DEFAULT_ANALYZE_BATCH_SIZE)
            ),
            analyze_concurrency=int(
                getattr(env_settings, "appgen_analyze_concurrency", DEFAULT_ANALYZE_CONCURRENCY)
            ),
            cursor_launch_stagger_ms=int(
                getattr(env_settings, "appgen_cursor_launch_stagger_ms", DEFAULT_CURSOR_LAUNCH_STAGGER_MS)
            ),
            cursor_launch_jitter_ms=int(
                getattr(env_settings, "appgen_cursor_launch_jitter_ms", DEFAULT_CURSOR_LAUNCH_JITTER_MS)
            ),
            cursor_chat_timeout_sec=int(
                getattr(env_settings, "appgen_cursor_chat_timeout_sec", DEFAULT_CURSOR_CHAT_TIMEOUT_SEC)
            ),
            cursor_chat_idle_timeout_sec=int(
                getattr(
                    env_settings,
                    "appgen_cursor_chat_idle_timeout_sec",
                    DEFAULT_CURSOR_CHAT_IDLE_TIMEOUT_SEC,
                )
            ),
            default_region_preset=str(
                getattr(env_settings, "appgen_default_regions", DEFAULT_DEFAULT_REGIONS)
            ),
            review_mode=str(getattr(env_settings, "appgen_review_mode", DEFAULT_REVIEW_MODE)),
            http_proxy=str(getattr(env_settings, "appgen_http_proxy", "") or ""),
            serper_api_key=str(getattr(env_settings, "serper_api_key", "") or ""),
            workspace=str(workspace),
            host=str(getattr(env_settings, "appgen_host", DEFAULT_HOST)),
            port=int(getattr(env_settings, "appgen_port", DEFAULT_PORT)),
            cursor_cwd=str(getattr(env_settings, "cursor_cwd", "") or "") or None,
            llm_provider_mode=str(getattr(env_settings, "llm_provider", DEFAULT_LLM_PROVIDER_MODE)),
        )

    def _maybe_import_llm_from_env(self, env_settings: Any) -> bool:
        """settings.json 无可用 LLM 或仅有测试 Key 时，从 .env 导入并落盘。"""
        mode = (self._data.llm_provider_mode or DEFAULT_LLM_PROVIDER_MODE).lower()
        if mode == LLM_PROVIDER_MOCK:
            return False

        env_chain = default_llm_providers_from_env(
            cursor_api_key=getattr(env_settings, "cursor_api_key", ""),
            cursor_model=getattr(env_settings, "cursor_model", DEFAULT_CURSOR_MODEL),
            openai_api_key=getattr(env_settings, "llm_api_key", ""),
            openai_base_url=getattr(env_settings, "llm_base_url", DEFAULT_LLM_BASE_URL),
            openai_model=getattr(env_settings, "llm_model", DEFAULT_LLM_MODEL),
        )
        if not env_chain:
            return False

        current = self._data.llm_providers
        if _chain_has_usable_providers(current):
            return False

        self._data.llm_providers = env_chain
        env_mode = str(getattr(env_settings, "llm_provider", DEFAULT_LLM_PROVIDER_MODE)).lower()
        if env_mode and env_mode != LLM_PROVIDER_MOCK:
            self._data.llm_provider_mode = env_mode
        elif env_chain[0].provider == LLM_PROVIDER_CURSOR:
            self._data.llm_provider_mode = DEFAULT_LLM_PROVIDER_MODE
        self._data.updated_at = datetime.now(UTC).isoformat()
        self._save()
        return True

    def get(self) -> RuntimeSettings:
        with self._lock:
            return self._data

    def reload(self, env_settings: Any) -> RuntimeSettings:
        with self._lock:
            self._bootstrapped = False
            return self.bootstrap_from_env(env_settings)

    def apply_env_settings(self, env_settings: Any) -> RuntimeSettings:
        """测试专用：将 .env 镜像写入运行时。生产环境以 workspace/settings.json 为准。"""
        with self._lock:
            mode = str(getattr(env_settings, "llm_provider", DEFAULT_LLM_PROVIDER_MODE)).lower()
            self._data.llm_provider_mode = mode
            self._data.llm_providers = default_llm_providers_from_env(
                cursor_api_key=getattr(env_settings, "cursor_api_key", ""),
                cursor_model=getattr(env_settings, "cursor_model", DEFAULT_CURSOR_MODEL),
                openai_api_key=getattr(env_settings, "llm_api_key", ""),
                openai_base_url=getattr(env_settings, "llm_base_url", DEFAULT_LLM_BASE_URL),
                openai_model=getattr(env_settings, "llm_model", DEFAULT_LLM_MODEL),
            )
            if mode == LLM_PROVIDER_MOCK:
                self._data.llm_providers = []
            self._data.scan_concurrency = int(getattr(env_settings, "appgen_scan_concurrency", DEFAULT_SCAN_CONCURRENCY))
            self._data.scan_max_concurrency = int(
                getattr(env_settings, "appgen_scan_max_concurrency", DEFAULT_SCAN_MAX_CONCURRENCY)
            )
            self._data.analyze_batch_size = int(
                getattr(env_settings, "appgen_analyze_batch_size", DEFAULT_ANALYZE_BATCH_SIZE)
            )
            self._data.analyze_concurrency = int(
                getattr(env_settings, "appgen_analyze_concurrency", DEFAULT_ANALYZE_CONCURRENCY)
            )
            self._data.cursor_launch_stagger_ms = int(
                getattr(env_settings, "appgen_cursor_launch_stagger_ms", DEFAULT_CURSOR_LAUNCH_STAGGER_MS)
            )
            self._data.cursor_launch_jitter_ms = int(
                getattr(env_settings, "appgen_cursor_launch_jitter_ms", DEFAULT_CURSOR_LAUNCH_JITTER_MS)
            )
            self._data.cursor_chat_timeout_sec = int(
                getattr(env_settings, "appgen_cursor_chat_timeout_sec", DEFAULT_CURSOR_CHAT_TIMEOUT_SEC)
            )
            self._data.cursor_chat_idle_timeout_sec = int(
                getattr(
                    env_settings,
                    "appgen_cursor_chat_idle_timeout_sec",
                    DEFAULT_CURSOR_CHAT_IDLE_TIMEOUT_SEC,
                )
            )
            self._data.review_mode = str(getattr(env_settings, "appgen_review_mode", DEFAULT_REVIEW_MODE))
            self._sync_legacy_settings(env_settings)
            return self._data

    def update(self, patch: dict[str, Any], env_settings: Any) -> RuntimeSettings:
        with self._lock:
            current = self._data.model_dump()
            merged = self._merge_patch(current, patch)
            self._data = RuntimeSettings.model_validate(merged)
            self._sanitize_region_defaults()
            self._data.updated_at = datetime.now(UTC).isoformat()
            self._save()
            self._sync_legacy_settings(env_settings)
            return self._data

    def settings_path(self) -> Path | None:
        return self._path

    def to_public_dict(self) -> dict[str, Any]:
        rc = self.get()
        providers_public = []
        for item in rc.llm_providers:
            providers_public.append(
                {
                    "provider": item.provider,
                    "api_key_set": _is_real_secret(item.api_key, PLACEHOLDER_OPENAI_KEY)
                    or _is_real_secret(item.api_key, PLACEHOLDER_CURSOR_KEY),
                    "api_key_preview": _mask_secret(item.api_key)["preview"],
                    "base_url": item.base_url,
                    "model": item.model,
                }
            )
        return {
            "auto_review_default": rc.auto_review_default,
            "llm_providers": providers_public,
            "llm_provider_mode": rc.llm_provider_mode,
            "rss_marketing_url": rc.rss_marketing_url,
            "rss_legacy_top_url": rc.rss_legacy_top_url,
            "rss_legacy_genre_url": rc.rss_legacy_genre_url,
            "legacy_top_chart_types": rc.legacy_top_chart_types,
            "genres": [g.model_dump() for g in rc.genres],
            "popular_genre_ids": rc.popular_genre_ids,
            "store_regions": [r.model_dump() for r in rc.store_regions],
            "region_presets": rc.region_presets,
            "default_region_preset": self._effective_default_region_preset(),
            "scan_limit_min": rc.scan_limit_min,
            "scan_limit_max": rc.scan_limit_max,
            "default_scan_limit": rc.default_scan_limit,
            "default_scan_enrich": rc.default_scan_enrich,
            "default_charts": rc.default_charts,
            "scan_concurrency": rc.scan_concurrency,
            "scan_max_concurrency": rc.scan_max_concurrency,
            "analyze_batch_size": rc.analyze_batch_size,
            "analyze_concurrency": rc.analyze_concurrency,
            "analyze_max_snapshots": rc.analyze_max_snapshots,
            "analyze_max_snapshots_min": ANALYZE_MAX_SNAPSHOTS_MIN,
            "analyze_max_snapshots_max": ANALYZE_MAX_SNAPSHOTS_MAX,
            "cursor_launch_stagger_ms": rc.cursor_launch_stagger_ms,
            "cursor_launch_jitter_ms": rc.cursor_launch_jitter_ms,
            "cursor_chat_timeout_sec": rc.cursor_chat_timeout_sec,
            "cursor_chat_timeout_sec_min": CURSOR_CHAT_TIMEOUT_SEC_MIN,
            "cursor_chat_timeout_sec_max": CURSOR_CHAT_TIMEOUT_SEC_MAX,
            "cursor_chat_idle_timeout_sec": rc.cursor_chat_idle_timeout_sec,
            "cursor_chat_idle_timeout_sec_min": CURSOR_CHAT_IDLE_TIMEOUT_SEC_MIN,
            "cursor_chat_idle_timeout_sec_max": CURSOR_CHAT_IDLE_TIMEOUT_SEC_MAX,
            "pipeline_resume_stale_minutes": rc.pipeline_resume_stale_minutes,
            "pipeline_resume_stale_minutes_min": PIPELINE_RESUME_STALE_MINUTES_MIN,
            "pipeline_resume_stale_minutes_max": PIPELINE_RESUME_STALE_MINUTES_MAX,
            "review_mode": rc.review_mode,
            "http_proxy": rc.http_proxy,
            "serper_api_key_set": bool((rc.serper_api_key or "").strip()),
            "serper_api_key_preview": _mask_secret(rc.serper_api_key)["preview"],
            "workspace": rc.workspace,
            "host": rc.host,
            "port": rc.port,
            "cursor_cwd": rc.cursor_cwd,
            "chart_types": CHART_RSS_SLUGS,
            "config_source": str(self._path) if self._path else None,
            "updated_at": rc.updated_at,
            "settings_file": str(self._path) if self._path else None,
        }

    @staticmethod
    def _clamp_legacy_settings(data: dict[str, Any]) -> None:
        """加载旧版 settings.json 时静默修正越界值，避免启动失败。"""
        if data.get("analyze_max_snapshots") is not None:
            from appgen.analyze_limits import normalize_analyze_max_snapshots

            data["analyze_max_snapshots"] = normalize_analyze_max_snapshots(
                data["analyze_max_snapshots"],
                clamp=True,
            )
        stale = data.get("pipeline_resume_stale_minutes")
        if stale is not None:
            try:
                data["pipeline_resume_stale_minutes"] = max(
                    PIPELINE_RESUME_STALE_MINUTES_MIN,
                    min(PIPELINE_RESUME_STALE_MINUTES_MAX, int(stale)),
                )
            except (TypeError, ValueError):
                data["pipeline_resume_stale_minutes"] = DEFAULT_PIPELINE_RESUME_STALE_MINUTES
        for key, lo, hi, default in (
            ("cursor_chat_timeout_sec", CURSOR_CHAT_TIMEOUT_SEC_MIN, CURSOR_CHAT_TIMEOUT_SEC_MAX, DEFAULT_CURSOR_CHAT_TIMEOUT_SEC),
            ("cursor_chat_idle_timeout_sec", CURSOR_CHAT_IDLE_TIMEOUT_SEC_MIN, CURSOR_CHAT_IDLE_TIMEOUT_SEC_MAX, DEFAULT_CURSOR_CHAT_IDLE_TIMEOUT_SEC),
        ):
            raw = data.get(key)
            if raw is not None:
                try:
                    data[key] = max(lo, min(hi, int(raw)))
                except (TypeError, ValueError):
                    data[key] = default

    def _merge_patch(self, current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(current)
        for key, value in patch.items():
            if value is None:
                continue
            if key == "llm_providers" and isinstance(value, list):
                merged[key] = self._merge_llm_providers(current.get("llm_providers", []), value)
            elif key == "serper_api_key" and value == "":
                continue
            elif key.endswith("_api_key") and value == "":
                continue
            else:
                merged[key] = value
        return merged

    @staticmethod
    def _merge_llm_providers(
        existing: list[dict[str, Any]], incoming: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for idx, item in enumerate(incoming):
            row = dict(item)
            api_key = (row.get("api_key") or "").strip()
            if not api_key and idx < len(existing):
                row["api_key"] = existing[idx].get("api_key", "")
            result.append(row)
        return result

    def _effective_default_region_preset(self) -> str:
        presets = self._data.region_presets
        preferred = (self._data.default_region_preset or DEFAULT_REGION_PRESET).strip().lower()
        if preferred in presets:
            return preferred
        if presets:
            return sorted(presets.keys())[0]
        return preferred

    def _sanitize_region_defaults(self) -> None:
        presets = dict(self._data.region_presets)
        if not presets:
            return

        # 若仅有 us / eu 分拆预设，自动补全组合预设 us-eu（与代码默认一致）
        if "us-eu" not in presets and "us" in presets and "eu" in presets:
            merged: list[str] = []
            seen: set[str] = set()
            for code in presets["us"] + presets["eu"]:
                c = code.strip().lower()
                if c and c not in seen:
                    seen.add(c)
                    merged.append(c)
            if merged:
                presets["us-eu"] = merged
                self._data.region_presets = presets

        preferred = (self._data.default_region_preset or "").strip().lower()
        if preferred not in presets:
            self._data.default_region_preset = sorted(presets.keys())[0]

    def _save(self) -> None:
        if not self._path:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._data.model_dump()
        self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _sync_legacy_settings(self, env_settings: Any) -> None:
        rc = self._data
        openai = next((p for p in rc.llm_providers if p.provider == LLM_PROVIDER_OPENAI), None)
        cursor = next((p for p in rc.llm_providers if p.provider == LLM_PROVIDER_CURSOR), None)

        env_settings.llm_provider = rc.llm_provider_mode
        env_settings.llm_api_key = openai.api_key if openai else ""
        env_settings.llm_base_url = openai.base_url if openai and openai.base_url else DEFAULT_LLM_BASE_URL
        env_settings.llm_model = openai.model if openai and openai.model else DEFAULT_LLM_MODEL
        env_settings.cursor_api_key = cursor.api_key if cursor else ""
        env_settings.cursor_model = cursor.model if cursor and cursor.model else DEFAULT_CURSOR_MODEL
        env_settings.cursor_cwd = Path(rc.cursor_cwd) if rc.cursor_cwd else None
        env_settings.serper_api_key = rc.serper_api_key
        env_settings.appgen_workspace = Path(rc.workspace)
        env_settings.appgen_host = rc.host
        env_settings.appgen_port = rc.port
        env_settings.appgen_review_mode = rc.review_mode
        env_settings.appgen_default_regions = rc.default_region_preset
        env_settings.appgen_http_proxy = rc.http_proxy
        env_settings.appgen_scan_concurrency = rc.scan_concurrency
        env_settings.appgen_scan_max_concurrency = rc.scan_max_concurrency
        env_settings.appgen_analyze_batch_size = rc.analyze_batch_size
        env_settings.appgen_analyze_concurrency = rc.analyze_concurrency
        env_settings.appgen_cursor_launch_stagger_ms = rc.cursor_launch_stagger_ms
        env_settings.appgen_cursor_launch_jitter_ms = rc.cursor_launch_jitter_ms
        env_settings.appgen_cursor_chat_timeout_sec = rc.cursor_chat_timeout_sec
        env_settings.appgen_cursor_chat_idle_timeout_sec = rc.cursor_chat_idle_timeout_sec


runtime_settings = RuntimeSettingsManager()

"""App Store 区域/国家配置（美区 + 欧洲，不含中国大陆）。"""

from __future__ import annotations

from dataclasses import dataclass

from appgen.constants import BLOCKED_REGION_CODES, DEFAULT_REGION_PRESET
from appgen.runtime_settings import runtime_settings


@dataclass(frozen=True)
class StoreRegion:
    code: str
    name: str
    name_zh: str


def _load_regions() -> list[StoreRegion]:
    rc = runtime_settings.get()
    return [
        StoreRegion(code=r.code, name=r.name, name_zh=r.name_zh)
        for r in rc.store_regions
    ]


def get_region_presets() -> dict[str, list[str]]:
    rc = runtime_settings.get()
    return dict(rc.region_presets)


def get_effective_default_region_preset() -> str:
    """返回可用的默认区域预设；若配置项已删除则回退到第一个预设。"""
    rc = runtime_settings.get()
    presets = get_region_presets()
    preferred = (rc.default_region_preset or DEFAULT_REGION_PRESET).strip().lower()
    if preferred in presets:
        return preferred
    if presets:
        return sorted(presets.keys())[0]
    return preferred


def get_default_region_preset() -> str:
    return get_effective_default_region_preset()


REGION_PRESETS = get_region_presets()
DEFAULT_REGION_PRESET = get_default_region_preset()


def _known_codes() -> dict[str, StoreRegion]:
    return {r.code: r for r in _load_regions()}


ALL_KNOWN_CODES = _known_codes()


def region_label(code: str) -> str:
    region = _known_codes().get(code.lower())
    return f"{region.name_zh} ({code})" if region else code


def format_regions(codes: list[str]) -> str:
    return ", ".join(region_label(c) for c in codes)


def _split_region_tokens(value: str) -> list[str]:
    return [t.strip().lower() for t in value.split(",") if t.strip()]


def expand_region_selection(selection: str | None) -> list[str]:
    """将区域预设名（可逗号多选）和/或国家代码展开为去重后的国家代码列表。"""
    presets = get_region_presets()
    known = _known_codes()

    raw = (selection or "").strip()
    if not raw:
        raw = get_effective_default_region_preset()

    tokens = _split_region_tokens(raw)
    if not tokens:
        raise ValueError("至少选择一个区域")

    codes: list[str] = []
    unknown: list[str] = []

    for token in tokens:
        if token in BLOCKED_REGION_CODES:
            raise ValueError(f"不支持该区域: {token}，本项目仅覆盖美区与欧洲")
        if token in presets:
            for code in presets[token]:
                if code not in codes:
                    codes.append(code)
        elif token in known:
            if token not in codes:
                codes.append(token)
        else:
            unknown.append(token)

    if unknown:
        available = ", ".join(sorted(presets.keys())) if presets else "(无)"
        raise ValueError(
            f"未知区域预设或国家代码: {', '.join(unknown)}，可选预设: {available}"
        )

    if not codes:
        raise ValueError("未解析到有效国家/区域")

    normalized: list[str] = []
    for code in codes:
        if code in BLOCKED_REGION_CODES:
            raise ValueError(f"不支持该区域: {code}，本项目仅覆盖美区与欧洲")
        if code not in known:
            raise ValueError(
                f"未知国家代码: {code}，可用: {', '.join(sorted(known))}"
            )
        if code not in normalized:
            normalized.append(code)
    return normalized


def resolve_region_codes(
    *,
    preset: str | None = None,
    countries: str | None = None,
) -> list[str]:
    """解析区域参数，返回国家代码列表。preset 支持逗号分隔的多预设，如 us,eu。"""
    if countries:
        return expand_region_selection(countries)
    return expand_region_selection(preset)


def refresh_region_cache() -> None:
    global REGION_PRESETS, DEFAULT_REGION_PRESET, ALL_KNOWN_CODES
    REGION_PRESETS = get_region_presets()
    DEFAULT_REGION_PRESET = get_default_region_preset()
    ALL_KNOWN_CODES = _known_codes()

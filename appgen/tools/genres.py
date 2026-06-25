"""App Store 一级分类（genre）映射。"""

from __future__ import annotations

from dataclasses import dataclass

from appgen.constants import (
    CHART_LABELS,
    CHART_RSS_SLUGS,
    DEFAULT_POPULAR_GENRE_IDS,
    DEFAULT_APP_GENRES,
)
from appgen.runtime_settings import runtime_settings


@dataclass(frozen=True)
class AppGenre:
    id: int
    name: str
    name_zh: str
    search_term: str


def _load_genres() -> list[AppGenre]:
    rc = runtime_settings.get()
    return [
        AppGenre(
            id=g.id,
            name=g.name,
            name_zh=g.name_zh,
            search_term=g.search_term,
        )
        for g in rc.genres
    ]


def get_app_genres() -> list[AppGenre]:
    return _load_genres()


# 兼容旧 import
APP_GENRES: list[AppGenre] = get_app_genres()

CHART_TYPES = CHART_RSS_SLUGS


def get_popular_genre_ids() -> list[int]:
    rc = runtime_settings.get()
    return list(rc.popular_genre_ids or DEFAULT_POPULAR_GENRE_IDS)


POPULAR_GENRE_IDS = get_popular_genre_ids()


def get_genre(genre_id: int) -> AppGenre | None:
    for genre in get_app_genres():
        if genre.id == genre_id:
            return genre
    return None


def resolve_genres(genre_ids: list[int] | None) -> list[AppGenre] | None:
    """None 表示全品类；空列表亦视为全品类。"""
    if not genre_ids:
        return None
    genres = [g for g in get_app_genres() if g.id in set(genre_ids)]
    if not genres:
        raise ValueError(f"未找到有效分类 ID: {genre_ids}")
    return genres


def estimate_scan_requests(
    *,
    country_count: int,
    genre_count: int,
    chart_count: int,
) -> int:
    return country_count * genre_count * chart_count


def refresh_genre_cache() -> None:
    global APP_GENRES, POPULAR_GENRE_IDS
    APP_GENRES = get_app_genres()
    POPULAR_GENRE_IDS = get_popular_genre_ids()

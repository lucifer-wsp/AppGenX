from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from appgen.config import settings


class OpportunityFeedback(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    verdict: Literal["bad", "good"]
    reason: str = ""
    scan_id: str
    dedupe_key: str
    title: str
    genre_zh: str = ""
    chart_type: str = ""
    one_liner: str = ""
    suggested_keyword: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ScanPreferences(BaseModel):
    feedbacks: list[OpportunityFeedback] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def opportunity_dedupe_key(
    *,
    title: str,
    country: str,
    genre_zh: str,
    chart_type: str,
) -> str:
    return "|".join(
        [
            title.strip().lower(),
            country.lower(),
            genre_zh.strip().lower(),
            chart_type,
        ]
    )


class ScanPreferencesStore:
    def __init__(self, workspace: Path | None = None) -> None:
        root = workspace or settings.ensure_workspace()
        self.path = root / "scan_preferences.json"

    def load(self) -> ScanPreferences:
        if not self.path.exists():
            return ScanPreferences()
        return ScanPreferences.model_validate_json(self.path.read_text(encoding="utf-8"))

    def save(self, prefs: ScanPreferences) -> None:
        prefs.updated_at = datetime.now(UTC)
        self.path.write_text(prefs.model_dump_json(indent=2), encoding="utf-8")

    def add_feedback(self, feedback: OpportunityFeedback) -> ScanPreferences:
        prefs = self.load()
        prefs.feedbacks = [
            f
            for f in prefs.feedbacks
            if not (f.scan_id == feedback.scan_id and f.dedupe_key == feedback.dedupe_key)
        ]
        prefs.feedbacks.append(feedback)
        self.save(prefs)
        return prefs

    def remove_feedback(self, feedback_id: str) -> ScanPreferences:
        prefs = self.load()
        prefs.feedbacks = [f for f in prefs.feedbacks if f.id != feedback_id]
        self.save(prefs)
        return prefs

    def bad_feedbacks(self, *, limit: int = 30) -> list[OpportunityFeedback]:
        bad = [f for f in self.load().feedbacks if f.verdict == "bad"]
        return bad[-limit:]

    def good_feedbacks(self, *, limit: int = 15) -> list[OpportunityFeedback]:
        good = [f for f in self.load().feedbacks if f.verdict == "good"]
        return good[-limit:]

    def feedback_map_for_scan(self, scan_id: str) -> dict[str, OpportunityFeedback]:
        return {
            f.dedupe_key: f
            for f in self.load().feedbacks
            if f.scan_id == scan_id
        }

    def build_llm_context(self) -> str:
        bad = self.bad_feedbacks(limit=20)
        good = self.good_feedbacks(limit=8)
        if not bad and not good:
            return ""

        parts: list[str] = []
        if bad:
            parts.append("用户已明确标记「不符合期望」的机会（请勿推荐同类方向，除非榜单数据有全新强证据）：")
            for item in bad:
                line = f"- 「{item.title}」· {item.genre_zh or '未知品类'} · {item.chart_type}"
                if item.reason.strip():
                    line += f" — 原因: {item.reason.strip()}"
                elif item.one_liner.strip():
                    line += f" — {item.one_liner.strip()[:120]}"
                parts.append(line)

        rejected_genres = _top_repeated([f.genre_zh for f in bad if f.genre_zh.strip()], min_count=2)
        if rejected_genres:
            parts.append(f"用户多次否定的品类倾向: {', '.join(rejected_genres)}")

        if good:
            parts.append("\n用户标记「符合期望」的方向（可优先参考类似切入点，但仍需榜单证据）：")
            for item in good[-5:]:
                line = f"- 「{item.title}」· {item.genre_zh or '未知品类'}"
                if item.reason.strip():
                    line += f" — 原因: {item.reason.strip()}"
                parts.append(line)

        return "\n".join(parts)

    def is_blocked(self, *, title: str, country: str, genre_zh: str, chart_type: str) -> bool:
        key = opportunity_dedupe_key(
            title=title,
            country=country,
            genre_zh=genre_zh,
            chart_type=chart_type,
        )
        return any(f.verdict == "bad" and f.dedupe_key == key for f in self.load().feedbacks)


def _top_repeated(values: list[str], *, min_count: int) -> list[str]:
    counts: dict[str, int] = {}
    for value in values:
        key = value.strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return sorted(
        [name for name, count in counts.items() if count >= min_count],
        key=lambda name: counts[name],
        reverse=True,
    )

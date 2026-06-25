from __future__ import annotations

from typing import Any

from appgen.discovery import DemandOpportunity
from appgen.models import OpportunityBrief, PainPoint


def brief_from_picked(picked: dict[str, Any]) -> OpportunityBrief:
    """将 scan pick 的机会转为 Scout 产物，避免重复调用 LLM。"""
    opp = DemandOpportunity.model_validate(picked)
    pain_points = [
        PainPoint(
            summary=text,
            evidence="来自市场扫描报告",
            severity=4,
            frequency="high",
        )
        for text in opp.pain_points
    ]
    signals = [opp.why_now] if opp.why_now else []
    if opp.reference_apps:
        signals.append(f"参考应用: {', '.join(opp.reference_apps)}")

    return OpportunityBrief(
        title=opp.title,
        one_liner=opp.one_liner,
        category=opp.genre or opp.genre_zh,
        market_signals=signals,
        pain_points=pain_points,
        differentiation_angle=opp.differentiation,
        confidence_score=opp.confidence_score,
    )

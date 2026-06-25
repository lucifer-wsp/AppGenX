from appgen.discovery import DemandOpportunity
from appgen.models import OpportunityBrief
from appgen.scan_bridge import brief_from_picked


def test_brief_from_picked():
    picked = DemandOpportunity(
        rank=1,
        title="Privacy Period Tracker",
        country="us",
        genre="Health & Fitness",
        genre_zh="健康健美",
        chart_type="top-free",
        one_liner="Local-first period tracking",
        pain_points=["Privacy concerns", "Too many ads"],
        reference_apps=["Flo", "Clue"],
        differentiation="Offline only",
        confidence_score=86,
        suggested_keyword="period tracker offline",
        why_now="Privacy regulation trend",
    )
    brief = brief_from_picked(picked.model_dump())
    assert brief.title == "Privacy Period Tracker"
    assert brief.confidence_score == 86
    assert len(brief.pain_points) == 2


def test_brief_from_picked_dict():
    brief = brief_from_picked(
        {
            "rank": 1,
            "title": "Test App",
            "genre": "Utilities",
            "genre_zh": "工具",
            "chart_type": "top-free",
            "one_liner": "A test",
            "pain_points": ["pain"],
            "confidence_score": 70,
        }
    )
    assert isinstance(brief, OpportunityBrief)

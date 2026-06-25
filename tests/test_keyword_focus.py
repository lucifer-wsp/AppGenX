from appgen.discovery import (
    DemandOpportunity,
    MarketScanner,
    _brief_keyword_score,
    keyword_tokens,
    normalize_search_keyword,
)


def test_keyword_tokens_splits_ampersand():
    assert keyword_tokens("relax & life & happy") == ["relax", "life", "happy"]


def test_normalize_search_keyword():
    assert normalize_search_keyword("relax & life & happy") == "relax life happy"


def test_brief_keyword_score_prefers_search():
    brief = {
        "genre": "Search: relax life happy",
        "genre_zh": "搜索: relax life happy",
        "top_apps": [{"name": "Calm Garden", "description": "cozy relax app"}],
    }
    score = _brief_keyword_score(brief, keyword_tokens("relax & life"))
    generic = _brief_keyword_score(
        {"genre": "Finance", "top_apps": [{"name": "Bank App"}]},
        keyword_tokens("relax & life"),
    )
    assert score > generic


def test_filter_by_keyword_strict():
    scanner = MarketScanner()
    opps = [
        DemandOpportunity(
            rank=1,
            title="Cozy Plant Idle",
            one_liner="relaxing plant care",
            genre="Search: relax",
            genre_zh="搜索",
            chart_type="search",
            suggested_keyword="cozy plant",
            why_now="relax trend",
        ),
        DemandOpportunity(
            rank=2,
            title="Invoice Tool",
            one_liner="business invoicing",
            genre="Business",
            genre_zh="商务",
            chart_type="top-free",
            suggested_keyword="invoice",
        ),
    ]
    filtered = scanner._filter_by_keyword(opps, "relax & life", strict=True)
    assert all("relax" in o.one_liner.lower() or "plant" in o.title.lower() for o in filtered)
    assert not any(o.title == "Invoice Tool" for o in filtered)

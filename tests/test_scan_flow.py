from appgen.scan_flow import plan_scan
from appgen.tools.genres import POPULAR_GENRE_IDS


def test_plan_scan_keyword_mode():
    p = plan_scan(keyword="fitness", genre_ids=[], regions="us", charts=["top-free"])
    assert p["mode"] == "keyword"


def test_plan_scan_categories_mode():
    p = plan_scan(keyword=None, genre_ids=POPULAR_GENRE_IDS[:3], regions="us", charts=["top-free", "top-paid"])
    assert p["mode"] == "categories"
    assert p["genres"] == 3


def test_plan_scan_full_mode():
    p = plan_scan(keyword=None, genre_ids=[], regions="us", charts=["top-free"])
    assert p["mode"] == "full"
    assert p["genres"] == 24  # APP_GENRES count

from appgen.discovery import MarketScanner
from appgen.scan_preferences import OpportunityFeedback, ScanPreferencesStore, opportunity_dedupe_key


def test_feedback_persists_and_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv("APPGEN_WORKSPACE", str(tmp_path))
    from appgen.config import settings

    settings.appgen_workspace = tmp_path
    store = ScanPreferencesStore()
    store.add_feedback(
        OpportunityFeedback(
            verdict="bad",
            reason="太泛，无数据支撑",
            scan_id="s1",
            dedupe_key=opportunity_dedupe_key(
                title="Generic Habit App",
                country="us",
                genre_zh="健康健美",
                chart_type="top-free",
            ),
            title="Generic Habit App",
            genre_zh="健康健美",
            chart_type="top-free",
        )
    )

    ctx = store.build_llm_context()
    assert "Generic Habit App" in ctx
    assert "太泛" in ctx
    assert store.is_blocked(
        title="Generic Habit App",
        country="us",
        genre_zh="健康健美",
        chart_type="top-free",
    )


def test_list_scans_tolerates_legacy_cn_scan(tmp_path, monkeypatch):
    monkeypatch.setenv("APPGEN_WORKSPACE", str(tmp_path))
    from appgen.config import settings
    from appgen.discovery import ScanStore

    settings.appgen_workspace = tmp_path
    scan_dir = tmp_path / "scans" / "legacy1"
    scan_dir.mkdir(parents=True)
    scan_dir.joinpath("scan.json").write_text(
        """{
  "id": "legacy1",
  "country": "cn",
  "status": "completed",
  "categories": [
    {"genre_id": 6002, "genre_name": "Utilities", "genre_name_zh": "工具",
     "chart_type": "top-free", "chart_label": "免费榜", "apps": []}
  ],
  "opportunities": []
}""",
        encoding="utf-8",
    )

    store = ScanStore()
    scans = store.list_scans()
    assert len(scans) == 1
    assert scans[0].status == "legacy_unsupported"
    assert scans[0].categories[0].country == "us"


def test_filter_by_user_feedback(tmp_path, monkeypatch):
    monkeypatch.setenv("APPGEN_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("LLM_PROVIDER", "mock")

    from appgen.config import settings

    settings.appgen_workspace = tmp_path
    settings.llm_provider = "mock"

    scanner = MarketScanner()
    scanner.preferences.add_feedback(
        OpportunityFeedback(
            verdict="bad",
            reason="不喜欢",
            scan_id="s1",
            dedupe_key="blocked|us|健康|top-free",
            title="blocked",
            genre_zh="健康",
            chart_type="top-free",
        )
    )

    items = [
        {"title": "blocked", "country": "us", "genre_zh": "健康", "chart_type": "top-free"},
        {"title": "allowed", "country": "us", "genre_zh": "工具", "chart_type": "top-free"},
    ]
    filtered = scanner._filter_by_user_feedback(items)
    assert len(filtered) == 1
    assert filtered[0]["title"] == "allowed"

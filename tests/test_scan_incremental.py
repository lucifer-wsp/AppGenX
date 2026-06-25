import pytest

from appgen.discovery import MarketScanner
from appgen.models import AppStoreApp


@pytest.mark.asyncio
async def test_incremental_analysis_saves_batches(tmp_path, monkeypatch):
    monkeypatch.setenv("APPGEN_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("CURSOR_API_KEY", "")
    monkeypatch.setenv("LLM_PROVIDER", "mock")

    from appgen.config import settings
    from appgen.discovery import CategorySnapshot, MarketScan
    from appgen.tools.genres import APP_GENRES

    settings.appgen_workspace = tmp_path
    settings.llm_provider = "mock"
    settings.appgen_analyze_batch_size = 1
    settings.appgen_analyze_concurrency = 2

    scanner = MarketScanner()
    genre = next(g for g in APP_GENRES if g.id == 6013)
    scan = MarketScan(id="incr1", countries=["us"])
    scan.categories = [
        CategorySnapshot(
            country="us",
            country_label="美国 (us)",
            genre_id=genre.id,
            genre_name=genre.name,
            genre_name_zh=genre.name_zh,
            chart_type="top-free",
            chart_label="免费榜",
            apps=[AppStoreApp(app_id="1", name="App A", chart_rank=1)],
        ),
        CategorySnapshot(
            country="us",
            country_label="美国 (us)",
            genre_id=6007,
            genre_name="Health",
            genre_name_zh="健康健美",
            chart_type="top-paid",
            chart_label="付费榜",
            apps=[AppStoreApp(app_id="2", name="App B", chart_rank=1)],
        ),
    ]

    result = await scanner._analyze_opportunities_incremental(scan)
    assert len(result) >= 1
    assert scan.phase == "analyze" or scan.analysis_batches_total == 2
    assert scan.analysis_batches_done == scan.analysis_batches_total


def test_scan_live_merge(tmp_path, monkeypatch):
    monkeypatch.setenv("APPGEN_WORKSPACE", str(tmp_path))

    from appgen.config import settings
    from appgen.discovery import MarketScan, ScanStore

    settings.appgen_workspace = tmp_path
    store = ScanStore()
    scan = MarketScan(id="live1", countries=["us"])
    scan.log("创建扫描")
    store.save(scan)

    scan.phase = "analyze"
    scan.analysis_batches_total = 3
    scan.analysis_batches_done = 1
    scan.log("分析进度 1/3")
    store.save_live(scan)

    loaded = store.load("live1")
    assert loaded.phase == "analyze"
    assert loaded.analysis_batches_done == 1
    assert loaded.analysis_batches_total == 3
    assert loaded.live_category_count == 0
    assert any("分析进度" in line for line in loaded.logs)

    store.clear_live("live1")
    after_clear = store.load("live1")
    assert after_clear.phase == "fetch"

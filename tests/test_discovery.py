import pytest

from appgen.discovery import MarketScanner, MarketScan, ScanStore
from appgen.tools.appstore import AppStoreClient
from appgen.tools.genres import APP_GENRES
from appgen.tools.regions import resolve_region_codes


def test_resolve_single_preset():
    codes = resolve_region_codes(preset="us")
    assert "us" in codes
    assert "cn" not in codes


def test_resolve_comma_separated_presets():
    codes = resolve_region_codes(preset="us,eu")
    assert "us" in codes
    assert "gb" in codes
    assert "de" in codes
    assert len(codes) == len(set(codes))


def test_unknown_preset_error_lists_available():
    with pytest.raises(ValueError, match="未知区域预设"):
        resolve_region_codes(preset="not-a-real-preset")


def test_block_china():
    with pytest.raises(ValueError, match="不支持"):
        resolve_region_codes(countries="us,cn")


@pytest.mark.asyncio
async def test_fetch_genre_chart_us_health():
    client = AppStoreClient(country="us")
    genre = next(g for g in APP_GENRES if g.id == 6013)
    apps = await client.fetch_genre_chart(genre, chart_type="top-free", limit=3)
    assert len(apps) >= 1
    assert apps[0].name


@pytest.mark.asyncio
async def test_market_scan_us_subset(tmp_path, monkeypatch):
    monkeypatch.setenv("APPGEN_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("CURSOR_API_KEY", "")
    monkeypatch.setenv("LLM_PROVIDER", "mock")

    from appgen.config import settings

    settings.appgen_workspace = tmp_path
    settings.llm_provider = "mock"
    settings.cursor_api_key = ""

    scanner = MarketScanner()
    genres = [g for g in APP_GENRES if g.id in {6013, 6007}]
    scan = scanner.create_scan(
        countries=["us", "gb"],
        region_preset="us,gb",
        chart_types=["top-free"],
        per_genre_limit=3,
        enrich_top_n=2,
    )

    final = await scanner.run_scan(scan, genres=genres)
    assert final.status == "completed"
    assert len(final.categories) == 4  # 2 genres × 2 countries
    assert len(final.opportunities) >= 1
    assert (tmp_path / "scans" / final.id / "scan_report.md").exists()


def test_scan_store_roundtrip(tmp_path):
    store = ScanStore(tmp_path)
    scan = MarketScan(id="abc123", countries=["us", "gb"])
    store.save(scan)
    loaded = store.load("abc123")
    assert loaded.countries == ["us", "gb"]


def test_items_to_opportunities_coerces_reference_apps_dicts():
    scanner = MarketScanner()
    items = [
        {
            "title": "Sleep tracker MVP",
            "country": "us",
            "genre": "Health",
            "genre_zh": "健康健美",
            "chart_type": "top-paid",
            "one_liner": "Lightweight sleep insights",
            "reference_apps": [
                {"name": "AutoSleep: Watch Tracker", "note": "No data upload"},
                "Pillow",
            ],
            "pain_points": [{"summary": "Too complex onboarding"}, "Ads everywhere"],
            "confidence_score": "72",
        }
    ]
    opps = scanner._items_to_opportunities(items)
    assert len(opps) == 1
    assert opps[0].reference_apps == ["AutoSleep: Watch Tracker", "Pillow"]
    assert opps[0].pain_points == ["Too complex onboarding", "Ads everywhere"]
    assert opps[0].confidence_score == 72

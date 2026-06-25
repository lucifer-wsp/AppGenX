from pathlib import Path

from appgen.models import DesignSpec, PRDDocument, ScreenSpec
from appgen.tools.ios_project import (
    derive_english_product_name,
    format_marketing_name,
    normalize_prd_product_identity,
    render_project_yml,
    sanitize_product_name,
    scaffold_ios_project,
    write_swift_files,
)


def test_sanitize_product_name():
    assert sanitize_product_name("Swipe Clean!") == "SwipeClean"
    assert sanitize_product_name("123App").startswith("App")
    assert sanitize_product_name("一叶微养") == "AppGenProduct"


def test_derive_english_product_name():
    assert derive_english_product_name(marketing_name_en="Leaf Minute Care") == "LeafMinuteCare"
    assert derive_english_product_name(category="Search: relax & life") == "RelaxLife"
    assert derive_english_product_name(tagline="virtual plant care daily") == "VirtualPlantCare"


def test_normalize_prd_product_identity():
    from appgen.models import OpportunityBrief, PRDDocument

    prd = PRDDocument(
        product_name="一叶微养",
        tagline="一盆虚拟绿植，每日浇水一分钟",
        background="test",
        marketing_name_en="Leaf Minute Care",
    )
    normalized = normalize_prd_product_identity(prd)
    assert normalized.product_name == "LeafMinuteCare"
    assert normalized.display_name == "一叶微养"
    assert normalized.marketing_name_en == "Leaf Minute Care"


def test_format_marketing_name():
    assert format_marketing_name("LeafMinuteCare") == "Leaf Minute Care"


def test_render_project_yml():
    yml = render_project_yml(product_name="FocusCalm", bundle_id="com.appgen.focuscalm")
    assert "FocusCalm:" in yml
    assert "com.appgen.focuscalm" in yml


def test_scaffold_ios_project(tmp_path):
    prd = PRDDocument(
        product_name="Focus Calm",
        display_name="专注时刻",
        display_name_zh_hant="專注時刻",
        marketing_name_en="Focus Calm",
        tagline="Stay focused",
        background="Focus app",
        mvp_features=["番茄钟", "呼吸训练"],
    )
    design = DesignSpec(
        color_palette={"primary": "#3366FF", "background": "#F5F5F5"},
        screens=[
            ScreenSpec(name="Home", purpose="主屏"),
            ScreenSpec(name="Timer", purpose="计时"),
        ],
    )
    root = tmp_path / "project"
    result = scaffold_ios_project(root, prd, design, plan_bundle_id="com.test.focuscalm")

    assert result.product_name == "FocusCalm"
    assert (root / "project.yml").exists()
    assert "knownLocalizations" in (root / "project.yml").read_text(encoding="utf-8")
    assert (root / "FocusCalm" / "App" / "FocusCalmApp.swift").exists()
    assert (root / "FocusCalm" / "Features" / "HomeView.swift").exists()
    assert (root / "FocusCalm" / "Features" / "TimerView.swift").exists()
    assert (root / "FocusCalm" / "Configuration" / "L10n.swift").exists()
    assert (root / "FocusCalm" / "Configuration" / "DesignTokens.swift").exists()
    assert (root / "FocusCalm" / "Resources" / "en.lproj" / "Localizable.strings").exists()
    assert (root / "FocusCalm" / "Resources" / "zh-Hans.lproj" / "InfoPlist.strings").exists()
    zh_hans_infoplist = (root / "FocusCalm" / "Resources" / "zh-Hans.lproj" / "InfoPlist.strings").read_text(
        encoding="utf-8"
    )
    assert "专注时刻" in zh_hans_infoplist
    assert (root / "FocusCalmTests" / "FocusCalmTests.swift").exists()


def test_localization_keys(tmp_path):
    design = DesignSpec(
        screens=[
            ScreenSpec(
                name="Home",
                purpose="主屏",
                ui_copy={
                    "cta_en": "Start",
                    "cta_zh_hans": "开始",
                    "cta_zh_hant": "開始",
                },
            ),
        ],
    )
    prd = PRDDocument(product_name="TestApp", tagline="Test", background="x")
    from appgen.tools.ios_project import _collect_screen_strings

    bundles = _collect_screen_strings(
        design,
        prd,
        display_zh_hans="测试",
        display_zh_hant="測試",
        marketing_en="Test App",
    )
    assert bundles["en"]["screen.home.cta"] == "Start"
    assert bundles["zh-Hans"]["screen.home.cta"] == "开始"
    assert bundles["zh-Hant"]["screen.home.cta"] == "開始"


def test_write_swift_files(tmp_path):
    written = write_swift_files(
        tmp_path,
        [("FocusCalm/Features/FooView.swift", "import SwiftUI\n")],
    )
    assert written == ["FocusCalm/Features/FooView.swift"]
    assert (tmp_path / "FocusCalm" / "Features" / "FooView.swift").exists()

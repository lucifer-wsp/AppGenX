"""iOS 工程脚手架、XcodeGen 与 xcodebuild 封装。"""

from __future__ import annotations

import plistlib
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from appgen.models import DesignSpec, OpportunityBrief, PRDDocument, ScreenSpec

_NAME_STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "for", "to", "in", "on", "with", "of", "by",
    "app", "apps", "game", "games", "idle", "cozy", "search", "ios",
})


def sanitize_product_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", name.strip())
    if not cleaned:
        cleaned = "AppGenProduct"
    if cleaned[0].isdigit():
        cleaned = f"App{cleaned}"
    return cleaned


def format_marketing_name(pascal_name: str) -> str:
    """LeafMinuteCare -> Leaf Minute Care"""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", pascal_name.strip())
    return re.sub(r"\s+", " ", spaced).strip()


def _english_words(text: str, *, limit: int = 3) -> list[str]:
    words: list[str] = []
    for raw in re.findall(r"[A-Za-z]{3,}", text or ""):
        token = raw.lower()
        if token in _NAME_STOP_WORDS:
            continue
        words.append(raw[:1].upper() + raw[1:].lower())
        if len(words) >= limit:
            break
    return words


def derive_english_product_name(
    *,
    display_name: str = "",
    tagline: str = "",
    marketing_name_en: str = "",
    opportunity_title: str = "",
    opportunity_one_liner: str = "",
    category: str = "",
) -> str:
    """从推广名/文案/商机信息推导 Xcode 可用的英文 PascalCase 产品名。"""
    for candidate in (marketing_name_en, display_name):
        name = sanitize_product_name(candidate)
        if name != "AppGenProduct":
            return name

    for source in (tagline, opportunity_one_liner, opportunity_title, category):
        words = _english_words(source, limit=3)
        if words:
            return sanitize_product_name("".join(words))

    return "AppGenProduct"


def normalize_prd_product_identity(
    prd: PRDDocument,
    opportunity: OpportunityBrief | None = None,
) -> PRDDocument:
    """统一 PRD 产品标识：product_name 为英文 PascalCase，display_name 为用户可见名。"""
    updated = prd.model_copy(deep=True)
    raw_product = (updated.product_name or "").strip()
    display = (updated.display_name or "").strip()
    marketing = (updated.marketing_name_en or "").strip()

    if raw_product and re.search(r"[^\x00-\x7F]", raw_product):
        if not display:
            display = raw_product
        raw_product = ""

    xcode = sanitize_product_name(raw_product) if raw_product else "AppGenProduct"
    if xcode == "AppGenProduct":
        xcode = derive_english_product_name(
            display_name=display,
            tagline=updated.tagline,
            marketing_name_en=marketing,
            opportunity_title=getattr(opportunity, "title", "") or "",
            opportunity_one_liner=getattr(opportunity, "one_liner", "") or "",
            category=getattr(opportunity, "category", "") or "",
        )

    updated.product_name = xcode
    updated.display_name = display or raw_product or format_marketing_name(xcode)
    if not updated.display_name_zh_hant:
        updated.display_name_zh_hant = updated.display_name
    if not updated.marketing_name_en:
        updated.marketing_name_en = format_marketing_name(xcode)
    return updated


def resolve_product_names(
    prd: PRDDocument,
    opportunity: OpportunityBrief | None = None,
) -> tuple[str, str, str, str]:
    """返回 (xcode_product_name, display_name_zh_hans, display_name_zh_hant, marketing_name_en)。"""
    normalized = normalize_prd_product_identity(prd, opportunity)
    return (
        normalized.product_name,
        normalized.display_name,
        normalized.display_name_zh_hant,
        normalized.marketing_name_en,
    )


def default_bundle_id(product_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "", product_name.lower())
    return f"com.appgen.{slug or 'app'}"


def render_project_yml(*, product_name: str, bundle_id: str, deployment_target: str = "16.0") -> str:
    return f"""name: {product_name}
options:
  bundleIdPrefix: com.appgen
  developmentLanguage: en
  knownLocalizations:
    - en
    - zh-Hans
    - zh-Hant
  deploymentTarget:
    iOS: "{deployment_target}"
  createIntermediateGroups: true
  groupSortPosition: top
settings:
  base:
    SWIFT_VERSION: "5.9"
    IPHONEOS_DEPLOYMENT_TARGET: "{deployment_target}"
    TARGETED_DEVICE_FAMILY: "1"
    DEVELOPMENT_TEAM: ""
    CODE_SIGN_STYLE: Automatic
    CURRENT_PROJECT_VERSION: 1
    MARKETING_VERSION: 1.0.0
    SWIFT_EMIT_LOC_STRINGS: YES
targets:
  {product_name}:
    type: application
    platform: iOS
    sources:
      - path: {product_name}
        excludes:
          - "**/*.md"
    settings:
      base:
        PRODUCT_BUNDLE_IDENTIFIER: {bundle_id}
        INFOPLIST_FILE: {product_name}/Resources/Info.plist
        GENERATE_INFOPLIST_FILE: false
    scheme:
      testTargets:
        - {product_name}Tests
  {product_name}Tests:
    type: bundle.unit-test
    platform: iOS
    sources:
      - path: {product_name}Tests
    dependencies:
      - target: {product_name}
    settings:
      base:
        PRODUCT_BUNDLE_IDENTIFIER: {bundle_id}.tests
        GENERATE_INFOPLIST_FILE: YES
"""


def write_info_plist(path: Path, *, display_name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleDisplayName": display_name,
        "CFBundleLocalizations": ["en", "zh-Hans", "zh-Hant"],
        "CFBundleExecutable": "$(EXECUTABLE_NAME)",
        "CFBundleIdentifier": "$(PRODUCT_BUNDLE_IDENTIFIER)",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": "$(PRODUCT_NAME)",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "$(MARKETING_VERSION)",
        "CFBundleVersion": "$(CURRENT_PROJECT_VERSION)",
        "LSRequiresIPhoneOS": True,
        "UIApplicationSceneManifest": {
            "UIApplicationSupportsMultipleScenes": False,
        },
        "UILaunchScreen": {},
        "UISupportedInterfaceOrientations": [
            "UIInterfaceOrientationPortrait",
        ],
    }
    with path.open("wb") as f:
        plistlib.dump(data, f)


_LOCALE_SUFFIX = {
    "en": "_en",
    "zh-Hans": "_zh_hans",
    "zh-Hant": "_zh_hant",
}


def _l10n_screen_key(screen_name: str, suffix: str) -> str:
    route = sanitize_route_name(screen_name)
    return f"screen.{route.lower()}.{suffix}"


def _escape_strings_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _collect_screen_strings(
    design: DesignSpec,
    prd: PRDDocument,
    *,
    display_zh_hans: str,
    display_zh_hant: str,
    marketing_en: str,
) -> dict[str, dict[str, str]]:
    """locale -> key -> value"""
    bundles: dict[str, dict[str, str]] = {
        "en": {},
        "zh-Hans": {},
        "zh-Hant": {},
    }

    bundles["en"]["app.tagline"] = prd.tagline if _english_words(prd.tagline) else marketing_en
    bundles["zh-Hans"]["app.tagline"] = prd.tagline
    bundles["zh-Hant"]["app.tagline"] = prd.tagline

    for locale, common in (
        ("en", {"common.ok": "OK", "common.cancel": "Cancel", "common.settings": "Settings", "common.back": "Back"}),
        ("zh-Hans", {"common.ok": "确定", "common.cancel": "取消", "common.settings": "设置", "common.back": "返回"}),
        ("zh-Hant", {"common.ok": "確定", "common.cancel": "取消", "common.settings": "設定", "common.back": "返回"}),
    ):
        bundles[locale].update(common)

    screens = design.screens or [ScreenSpec(name="Home", purpose=prd.tagline)]
    for screen in screens:
        route_key = sanitize_route_name(screen.name).lower()
        title_key = f"screen.{route_key}.title"
        purpose_key = f"screen.{route_key}.purpose"
        bundles["en"][title_key] = screen.name
        bundles["zh-Hans"][title_key] = screen.name
        bundles["zh-Hant"][title_key] = screen.name
        bundles["en"][purpose_key] = screen.purpose
        bundles["zh-Hans"][purpose_key] = screen.purpose
        bundles["zh-Hant"][purpose_key] = screen.purpose

        for copy_key, copy_val in (screen.ui_copy or {}).items():
            base = re.sub(r"_(en|zh_hans|zh_hant)$", "", copy_key)
            for locale, suf in _LOCALE_SUFFIX.items():
                localized_key = f"{base}{suf}"
                val = (screen.ui_copy or {}).get(localized_key) or (
                    copy_val if locale == "zh-Hans" and localized_key == copy_key else ""
                )
                if val:
                    bundles[locale][f"screen.{route_key}.{base}"] = val

    bundles["en"]["app.name"] = marketing_en
    bundles["zh-Hans"]["app.name"] = display_zh_hans
    bundles["zh-Hant"]["app.name"] = display_zh_hant
    return bundles


def render_localizable_strings(entries: dict[str, str]) -> str:
    lines = ["/* AppGen generated — do not edit keys manually in production */"]
    for key in sorted(entries):
        lines.append(f'"{_escape_strings_value(key)}" = "{_escape_strings_value(entries[key])}";')
    return "\n".join(lines) + "\n"


def render_infoplist_strings(*, display_name: str) -> str:
    return f'"CFBundleDisplayName" = "{_escape_strings_value(display_name)}";\n'


def write_localization_bundle(
    app_dir: Path,
    design: DesignSpec,
    prd: PRDDocument,
    *,
    display_zh_hans: str,
    display_zh_hant: str,
    marketing_en: str,
) -> None:
    bundles = _collect_screen_strings(
        design,
        prd,
        display_zh_hans=display_zh_hans,
        display_zh_hant=display_zh_hant,
        marketing_en=marketing_en,
    )
    display_by_locale = {
        "en": marketing_en,
        "zh-Hans": display_zh_hans,
        "zh-Hant": display_zh_hant,
    }
    for locale in ("en", "zh-Hans", "zh-Hant"):
        lproj = app_dir / "Resources" / f"{locale}.lproj"
        lproj.mkdir(parents=True, exist_ok=True)
        (lproj / "Localizable.strings").write_text(
            render_localizable_strings(bundles[locale]),
            encoding="utf-8",
        )
        (lproj / "InfoPlist.strings").write_text(
            render_infoplist_strings(display_name=display_by_locale[locale]),
            encoding="utf-8",
        )


def render_design_tokens_swift(design: DesignSpec) -> str:
    typography = design.typography or {}
    typo_lines = []
    for key in ("largeTitle", "title", "body", "caption"):
        if key in typography:
            typo_lines.append(f"        /// DesignSpec: {typography[key]}")
    if not typo_lines:
        typo_lines = ["        /// 默认 Dynamic Type 语义字体"]

    return (
        "import SwiftUI\n\n"
        "/// 布局、动画与交互令牌 — 禁止在 View 中使用裸数字。\n"
        "extension AppTheme {\n"
        "    enum Metrics {\n"
        "        static let spacingXS: CGFloat = 4\n"
        "        static let spacingSM: CGFloat = 8\n"
        "        static let spacingMD: CGFloat = 16\n"
        "        static let spacingLG: CGFloat = 24\n"
        "        static let spacingXL: CGFloat = 32\n"
        "        static let pagePadding: CGFloat = 16\n"
        "        static let cornerRadiusSM: CGFloat = 8\n"
        "        static let cornerRadiusMD: CGFloat = 12\n"
        "        static let cornerRadiusLG: CGFloat = 16\n"
        "        static let borderWidthThin: CGFloat = 1\n"
        "        static let borderWidthThick: CGFloat = 2\n"
        "        static let iconSM: CGFloat = 20\n"
        "        static let iconMD: CGFloat = 24\n"
        "        static let iconLG: CGFloat = 32\n"
        "        static let cardMinHeight: CGFloat = 88\n"
        "        static let progressHeight: CGFloat = 6\n"
        "        static let shadowRadius: CGFloat = 8\n"
        "        static let shadowYOffset: CGFloat = 4\n"
        "    }\n\n"
        "    enum Animation {\n"
        "        static let fast: Double = 0.2\n"
        "        static let standard: Double = 0.35\n"
        "        static let slow: Double = 0.5\n"
        "        static let springResponse: Double = 0.45\n"
        "        static let springDamping: Double = 0.82\n"
        "    }\n\n"
        "    enum Interaction {\n"
        "        static let minimumTapTarget: CGFloat = 44\n"
        "        static let debounceInterval: TimeInterval = 0.3\n"
        "        static let toastDuration: TimeInterval = 2.5\n"
        "    }\n"
        "}\n"
    )


def render_l10n_swift(design: DesignSpec, prd: PRDDocument) -> str:
    screens = design.screens or [ScreenSpec(name="Home", purpose=prd.tagline)]
    screen_enums: list[str] = []
    for screen in screens:
        route = sanitize_route_name(screen.name)
        route_lower = route.lower()
        copy_keys = set()
        for raw_key in (screen.ui_copy or {}):
            base = re.sub(r"_(en|zh_hans|zh_hant)$", "", raw_key)
            copy_keys.add(base)
        copy_props = "\n".join(
            f'            static var {re.sub(r"[^a-zA-Z0-9]", "_", k)}: String {{ tr("screen.{route_lower}.{k}") }}'
            for k in sorted(copy_keys)
        )
        screen_enums.append(
            f"        enum {route} {{\n"
            f'            static var title: String {{ tr("screen.{route_lower}.title") }}\n'
            f'            static var purpose: String {{ tr("screen.{route_lower}.purpose") }}\n'
            f"{copy_props}\n"
            f"        }}"
        )

    screens_block = "\n".join(screen_enums)
    return (
        "import Foundation\n\n"
        "/// 本地化访问层 — 所有 UI 文案须经此类型读取。\n"
        "enum L10n {\n"
        "    enum Common {\n"
        '        static var ok: String { tr("common.ok") }\n'
        '        static var cancel: String { tr("common.cancel") }\n'
        '        static var settings: String { tr("common.settings") }\n'
        '        static var back: String { tr("common.back") }\n'
        "    }\n\n"
        "    enum App {\n"
        '        static var name: String { tr("app.name") }\n'
        '        static var tagline: String { tr("app.tagline") }\n'
        "    }\n\n"
        f"    enum Screen {{\n{screens_block}\n    }}\n\n"
        "    static func tr(_ key: String) -> String {\n"
        '        NSLocalizedString(key, tableName: nil, bundle: .main, value: key, comment: "")\n'
        "    }\n"
        "}\n"
    )


def render_app_constants_swift(
    *,
    marketing_en: str,
    tagline: str,
) -> str:
    safe_tagline = tagline.replace('"', "'")
    return (
        "import Foundation\n\n"
        "/// 非 UI 业务常量 — 用户可见文案请使用 L10n。\n"
        "enum AppConstants {\n"
        "    enum Storage {\n"
        '        static let userPreferencesKey = "app.user_preferences"\n'
        '        static let plantStateKey = "app.plant_state"\n'
        '        static let onboardingCompletedKey = "app.onboarding_completed"\n'
        "    }\n\n"
        "    enum Notification {\n"
        '        static let dailyReminderIdentifier = "app.notification.daily_reminder"\n'
        "    }\n\n"
        "    enum Layout {\n"
        "        static let supportedLocales = [\"en\", \"zh-Hans\", \"zh-Hant\"]\n"
        "    }\n\n"
        f'    static let marketingNameEn = "{marketing_en.replace(chr(34), chr(39))}"\n'
        f'    static let defaultTagline = "{safe_tagline}"\n'
        "}\n"
    )


def render_theme_swift(design: DesignSpec) -> str:
    colors = design.color_palette or {}
    lines = [
        "import SwiftUI",
        "",
        "/// 设计规范色板 — 由 AppGen 从 DesignSpec 生成，禁止硬编码散落颜色。",
        "enum AppTheme {",
        "    enum Colors {",
    ]
    for key, value in colors.items():
        ident = re.sub(r"[^a-zA-Z0-9]", "_", key)
        if ident and ident[0].isdigit():
            ident = f"c_{ident}"
        lines.append(f'        static let {ident} = Color(hex: "{value}")')
    semantic_defaults = [
        ('text_primary', 'Color.primary'),
        ('text_secondary', 'Color.secondary'),
        ('text_tertiary', 'Color(.tertiaryLabel)'),
        ('surface', 'Color(.secondarySystemBackground)'),
        ('divider', 'Color(.separator)'),
    ]
    existing_ids = {re.sub(r"[^a-zA-Z0-9]", "_", k) for k in colors}
    for ident, swift in semantic_defaults:
        if ident not in existing_ids:
            lines.append(f"        static let {ident} = {swift}")
    if not colors:
        lines.extend([
            '        static let primary = Color.accentColor',
            '        static let background = Color(.systemBackground)',
        ])
    lines.extend([
        "    }",
        "",
        "    enum Typography {",
        '        static let largeTitle = Font.largeTitle.weight(.bold)',
        '        static let title = Font.title2.weight(.semibold)',
        '        static let body = Font.body',
        '        static let caption = Font.caption',
        "    }",
        "}",
        "",
        "extension Color {",
        "    init(hex: String) {",
        "        let hex = hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)",
        "        var int: UInt64 = 0",
        "        Scanner(string: hex).scanHexInt64(&int)",
        "        let r, g, b: Double",
        "        switch hex.count {",
        "        case 6:",
        "            r = Double((int >> 16) & 0xFF) / 255",
        "            g = Double((int >> 8) & 0xFF) / 255",
        "            b = Double(int & 0xFF) / 255",
        "        default:",
        "            r = 0; g = 0; b = 0",
        "        }",
        "        self.init(red: r, green: g, blue: b)",
        "    }",
        "}",
    ])
    return "\n".join(lines) + "\n"


def render_app_router(screens: list[str], product_name: str) -> str:
    routes = screens or ["Home"]
    enum_cases = "\n".join(f"    case {sanitize_route_name(s)}" for s in routes)
    body_cases = "\n".join(
        f"        case .{sanitize_route_name(s)}:\n            {sanitize_route_name(s)}View()"
        for s in routes
    )
    return (
        f"import SwiftUI\n\n"
        f"enum AppRoute: Hashable {{\n{enum_cases}\n}}\n\n"
        f"@Observable\n"
        f"final class AppRouter {{\n"
        f"    var path = NavigationPath()\n\n"
        f"    func go(_ route: AppRoute) {{ path.append(route) }}\n"
        f"    func pop() {{ guard !path.isEmpty else {{ return }}; path.removeLast() }}\n"
        f"    func reset() {{ path = NavigationPath() }}\n"
        f"}}\n\n"
        f"struct AppRouteHost: View {{\n"
        f"    let route: AppRoute\n"
        f"    var body: some View {{\n"
        f"        switch route {{\n{body_cases}\n"
        f"        }}\n"
        f"    }}\n"
        f"}}\n"
    )


def sanitize_route_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", " ", name.strip()).title().replace(" ", "")
    if not cleaned:
        return "Home"
    if cleaned[0].isdigit():
        cleaned = f"S{cleaned}"
    return cleaned


def render_root_view(screens: list[str], product_name: str) -> str:
    first = sanitize_route_name(screens[0] if screens else "Home")
    return (
        "import SwiftUI\n\n"
        "struct RootView: View {\n"
        "    @State private var router = AppRouter()\n\n"
        "    var body: some View {\n"
        "        NavigationStack(path: $router.path) {\n"
        f"            {first}View()\n"
        "                .navigationDestination(for: AppRoute.self) { route in\n"
        "                    AppRouteHost(route: route)\n"
        "                }\n"
        "        }\n"
        "        .environment(router)\n"
        "    }\n"
        "}\n"
    )


def render_app_entry(product_name: str) -> str:
    return (
        f"import SwiftUI\n\n"
        f"@main\n"
        f"struct {product_name}App: App {{\n"
        f"    var body: some Scene {{\n"
        f"        WindowGroup {{\n"
        f"            RootView()\n"
        f"        }}\n"
        f"    }}\n"
        f"}}\n"
    )


def render_stub_view(screen_name: str, design_purpose: str = "") -> str:
    type_name = sanitize_route_name(screen_name)
    return (
        f"import SwiftUI\n\n"
        f"/// {design_purpose.replace(chr(34), chr(39))[:120]}\n"
        f"struct {type_name}View: View {{\n"
        f"    var body: some View {{\n"
        f"        ScrollView {{\n"
        f"            VStack(alignment: .leading, spacing: AppTheme.Metrics.spacingMD) {{\n"
        f"                Text(L10n.Screen.{type_name}.title)\n"
        f"                    .font(AppTheme.Typography.largeTitle)\n"
        f"                    .foregroundStyle(AppTheme.Colors.primary)\n"
        f"                Text(L10n.Screen.{type_name}.purpose)\n"
        f"                    .font(AppTheme.Typography.body)\n"
        f"                    .foregroundStyle(AppTheme.Colors.text_secondary)\n"
        f"            }}\n"
        f"            .padding(AppTheme.Metrics.pagePadding)\n"
        f"        }}\n"
        f"        .navigationTitle(L10n.Screen.{type_name}.title)\n"
        f"        .navigationBarTitleDisplayMode(.inline)\n"
        f"    }}\n"
        f"}}\n"
    )


def render_primary_button() -> str:
    return (
        "import SwiftUI\n\n"
        "/// 主操作按钮 — 符合最小点击区域与主题令牌。\n"
        "struct PrimaryButton: View {\n"
        "    let title: String\n"
        "    var isEnabled: Bool = true\n"
        "    let action: () -> Void\n\n"
        "    var body: some View {\n"
        "        Button(action: action) {\n"
        "            Text(title)\n"
        "                .font(AppTheme.Typography.title)\n"
        "                .foregroundStyle(\n"
        "                    isEnabled ? AppTheme.Colors.text_primary : AppTheme.Colors.text_tertiary\n"
        "                )\n"
        "                .frame(maxWidth: .infinity)\n"
        "                .frame(minHeight: AppTheme.Interaction.minimumTapTarget)\n"
        "                .background(\n"
        "                    isEnabled ? AppTheme.Colors.primary : AppTheme.Colors.text_tertiary.opacity(0.3)\n"
        "                )\n"
        "                .clipShape(RoundedRectangle(cornerRadius: AppTheme.Metrics.cornerRadiusMD))\n"
        "        }\n"
        "        .disabled(!isEnabled)\n"
        "        .accessibilityLabel(title)\n"
        "    }\n"
        "}\n"
    )


def render_test_stub(product_name: str) -> str:
    return (
        f"import XCTest\n\n"
        f"final class {product_name}Tests: XCTestCase {{\n"
        f"    func testModuleLoads() {{\n"
        f"        XCTAssertEqual(1 + 1, 2)\n"
        f"    }}\n"
        f"}}\n"
    )


@dataclass
class ScaffoldResult:
    product_name: str
    bundle_id: str
    project_root: Path
    xcodeproj: Path | None
    xcodegen_ran: bool
    message: str


def scaffold_ios_project(
    project_root: Path,
    prd: PRDDocument,
    design: DesignSpec,
    *,
    plan_bundle_id: str = "",
    opportunity: OpportunityBrief | None = None,
) -> ScaffoldResult:
    """创建可编译的 XcodeGen 工程骨架。"""
    product, display_zh_hans, display_zh_hant, marketing_name = resolve_product_names(prd, opportunity)
    bundle_id = plan_bundle_id or default_bundle_id(product)

    if project_root.exists():
        shutil.rmtree(project_root)
    project_root.mkdir(parents=True)

    app_dir = project_root / product
    tests_dir = project_root / f"{product}Tests"

    for sub in [
        "App", "Features", "Domain/Models", "Services", "Resources",
        "Configuration", "Routing", "DesignSystem/Components",
    ]:
        (app_dir / sub).mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True)

    screen_names = [s.name for s in design.screens] or ["Home"]

    files: dict[Path, str] = {
        project_root / "project.yml": render_project_yml(product_name=product, bundle_id=bundle_id),
        app_dir / "Resources" / "Info.plist": "",  # binary plist written separately
        app_dir / "Configuration" / "AppConstants.swift": render_app_constants_swift(
            marketing_en=marketing_name,
            tagline=prd.tagline,
        ),
        app_dir / "Configuration" / "Theme.swift": render_theme_swift(design),
        app_dir / "Configuration" / "DesignTokens.swift": render_design_tokens_swift(design),
        app_dir / "Configuration" / "L10n.swift": render_l10n_swift(design, prd),
        app_dir / "DesignSystem" / "Components" / "PrimaryButton.swift": render_primary_button(),
        app_dir / "Routing" / "AppRouter.swift": render_app_router(screen_names, product),
        app_dir / "Features" / "RootView.swift": render_root_view(screen_names, product),
        app_dir / "App" / f"{product}App.swift": render_app_entry(product),
        tests_dir / f"{product}Tests.swift": render_test_stub(product),
        project_root / "README.md": (
            f"# {display_zh_hans}\n\n"
            f"**App Store (EN):** {marketing_name}\n\n"
            f"**繁体显示名:** {display_zh_hant}\n\n"
            f"{prd.tagline}\n\n"
            "## 本地化\n\n"
            "支持 **en** / **zh-Hans** / **zh-Hant**；UI 文案使用 `L10n`，桌面名见各语言 `InfoPlist.strings`。\n\n"
            "## MVP 功能\n"
            + "\n".join(f"- {f}" for f in prd.mvp_features)
            + "\n\n## 构建\n\n```bash\ncd project && xcodegen generate\n"
            f"xcodebuild -scheme {product} -destination 'platform=iOS Simulator,name=iPhone 16' build\n```\n"
        ),
    }

    for screen in design.screens:
        type_name = sanitize_route_name(screen.name)
        files[app_dir / "Features" / f"{type_name}View.swift"] = render_stub_view(
            screen.name, screen.purpose
        )

    if not design.screens:
        files[app_dir / "Features" / "HomeView.swift"] = render_stub_view("Home", prd.tagline)

    for path, content in files.items():
        if path.name == "Info.plist":
            write_info_plist(path, display_name=marketing_name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    write_localization_bundle(
        app_dir,
        design,
        prd,
        display_zh_hans=display_zh_hans,
        display_zh_hant=display_zh_hant,
        marketing_en=marketing_name,
    )

    xcodegen_ran = False
    xcodeproj: Path | None = None
    message = "骨架文件已写入"

    if shutil.which("xcodegen"):
        proc = subprocess.run(
            ["xcodegen", "generate"],
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        xcodegen_ran = proc.returncode == 0
        candidate = project_root / f"{product}.xcodeproj"
        if candidate.exists():
            xcodeproj = candidate
        if not xcodegen_ran:
            message = f"XcodeGen 失败: {(proc.stderr or proc.stdout)[-500:]}"
        else:
            message = "XcodeGen 工程已生成"
    else:
        message = "XcodeGen 未安装，已写入 project.yml 与源码（请本地运行 xcodegen generate）"

    return ScaffoldResult(
        product_name=product,
        bundle_id=bundle_id,
        project_root=project_root,
        xcodeproj=xcodeproj,
        xcodegen_ran=xcodegen_ran,
        message=message,
    )


@dataclass
class BuildResult:
    success: bool
    skipped: bool
    log: str
    errors: list[str]
    message: str


def run_xcode_build(project_root: Path, scheme: str, *, destination: str | None = None) -> BuildResult:
    if not shutil.which("xcodebuild"):
        return BuildResult(
            success=False,
            skipped=True,
            log="",
            errors=[],
            message="未找到 xcodebuild，请在 macOS + Xcode 环境执行编译验证",
        )

    xcodeproj = next(project_root.glob("*.xcodeproj"), None)
    if xcodeproj is None:
        if shutil.which("xcodegen") and (project_root / "project.yml").exists():
            subprocess.run(["xcodegen", "generate"], cwd=project_root, capture_output=True, text=True)
            xcodeproj = next(project_root.glob("*.xcodeproj"), None)
    if xcodeproj is None:
        no_xcodegen = not shutil.which("xcodegen")
        return BuildResult(
            success=False,
            skipped=no_xcodegen,
            log="",
            errors=["未找到 .xcodeproj"],
            message="工程文件缺失，请先完成 DevScaffold 或安装 XcodeGen",
        )

    dest = destination or "generic/platform=iOS Simulator"
    cmd = [
        "xcodebuild",
        "-project", str(xcodeproj),
        "-scheme", scheme,
        "-destination", dest,
        "build",
        "CODE_SIGNING_ALLOWED=NO",
    ]
    proc = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True)
    log = (proc.stdout or "") + "\n" + (proc.stderr or "")
    errors = _parse_xcode_errors(log)
    success = proc.returncode == 0
    return BuildResult(
        success=success,
        skipped=False,
        log=log[-12000:],
        errors=errors[:20],
        message="编译通过" if success else f"编译失败（{len(errors)} 个错误）",
    )


def _parse_xcode_errors(log: str) -> list[str]:
    errors: list[str] = []
    for line in log.splitlines():
        if " error:" in line or line.strip().startswith("error:"):
            errors.append(line.strip())
    return errors


def write_swift_files(project_root: Path, files: list[tuple[str, str]]) -> list[str]:
    written: list[str] = []
    for rel, content in files:
        rel = rel.replace("\\", "/").lstrip("/")
        path = project_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(rel)
    return written

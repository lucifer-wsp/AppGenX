"""AppGen 默认常量与配置项键名（逻辑代码应引用此模块，避免魔法字符串/数字）。"""

from __future__ import annotations

from typing import Final, Literal

# --- LLM ---
LLM_PROVIDER_CURSOR: Final = "cursor"
LLM_PROVIDER_OPENAI: Final = "openai"
LLM_PROVIDER_MOCK: Final = "mock"

LLMProviderKind = Literal["cursor", "openai", "mock"]

PLACEHOLDER_OPENAI_KEY: Final = "sk-your-key"
PLACEHOLDER_CURSOR_KEY: Final = "cursor_your_key"

# 开发/测试用占位 Key；若写入 settings.json 会在启动时尝试从 .env 迁移真实 Key
SUSPICIOUS_LLM_KEY_PREFIXES: Final = ("sk-test", "cursor_test", "crsr_unit_test", "sk-proj-unit-test")
SUSPICIOUS_LLM_KEYS: Final = frozenset(
    {
        PLACEHOLDER_OPENAI_KEY,
        PLACEHOLDER_CURSOR_KEY,
        "sk-test-real-looking",
        "sk-test",
        "cursor_test_key",
    }
)

DEFAULT_LLM_BASE_URL: Final = "https://api.openai.com/v1"
DEFAULT_LLM_MODEL: Final = "gpt-4o-mini"
DEFAULT_CURSOR_MODEL: Final = "composer-2.5"
DEFAULT_LLM_PROVIDER_MODE: Final = "auto"  # auto | mock | cursor | openai（兼容旧 env）

# --- Review ---
REVIEW_MODE_AUTO: Final = "auto"
REVIEW_MODE_CLI: Final = "cli"
REVIEW_MODE_WEB: Final = "web"
DEFAULT_REVIEW_MODE: Final = REVIEW_MODE_CLI

# --- App Store RSS ---
DEFAULT_RSS_MARKETING_URL: Final = (
    "https://rss.marketingtools.apple.com/api/v2/{country}/apps/{chart_type}/{limit}/apps.json"
)
DEFAULT_RSS_LEGACY_TOP_URL: Final = (
    "https://itunes.apple.com/{country}/rss/{chart}/limit={limit}/json"
)
DEFAULT_RSS_LEGACY_GENRE_URL: Final = (
    "https://itunes.apple.com/{country}/rss/{chart}/limit={limit}/genre={genre_id}/json"
)
DEFAULT_LEGACY_TOP_CHART_TYPES: Final = ("top-grossing",)

ITUNES_SEARCH_URL: Final = "https://itunes.apple.com/search"
ITUNES_LOOKUP_URL: Final = "https://itunes.apple.com/lookup"

# --- 榜单类型 ---
CHART_TOP_FREE: Final = "top-free"
CHART_TOP_PAID: Final = "top-paid"
CHART_TOP_GROSSING: Final = "top-grossing"
CHART_SEARCH: Final = "search"

DEFAULT_CHART_TYPES: Final = (CHART_TOP_FREE, CHART_TOP_PAID)

CHART_RSS_SLUGS: Final = {
    CHART_TOP_FREE: "topfreeapplications",
    CHART_TOP_PAID: "toppaidapplications",
    CHART_TOP_GROSSING: "topgrossingapplications",
}

CHART_LABELS: Final = {
    CHART_TOP_FREE: "免费榜",
    CHART_TOP_PAID: "付费榜",
    CHART_TOP_GROSSING: "畅销榜",
    CHART_SEARCH: "关键词搜索",
}

# --- 扫描限制 ---
SCAN_LIMIT_MIN: Final = 1
SCAN_LIMIT_MAX: Final = 100
DEFAULT_SCAN_LIMIT: Final = 10
DEFAULT_SCAN_ENRICH_TOP_N: Final = 5

# --- 并发与错峰 ---
DEFAULT_SCAN_CONCURRENCY: Final = 10
DEFAULT_SCAN_MAX_CONCURRENCY: Final = 20
DEFAULT_ANALYZE_BATCH_SIZE: Final = 6
DEFAULT_ANALYZE_CONCURRENCY: Final = 3
DEFAULT_ANALYZE_MAX_SNAPSHOTS: Final = 40
ANALYZE_MAX_SNAPSHOTS_MIN: Final = 10
ANALYZE_MAX_SNAPSHOTS_MAX: Final = 120
DEFAULT_CURSOR_LAUNCH_STAGGER_MS: Final = 2500
DEFAULT_CURSOR_LAUNCH_JITTER_MS: Final = 400
DEFAULT_CURSOR_CHAT_TIMEOUT_SEC: Final = 600
DEFAULT_CURSOR_CHAT_IDLE_TIMEOUT_SEC: Final = 120
CURSOR_CHAT_TIMEOUT_SEC_MIN: Final = 60
CURSOR_CHAT_TIMEOUT_SEC_MAX: Final = 3600
CURSOR_CHAT_IDLE_TIMEOUT_SEC_MIN: Final = 30
CURSOR_CHAT_IDLE_TIMEOUT_SEC_MAX: Final = 600

# 流水线：当前阶段无心跳超过该分钟数才允许「恢复执行」（case 3）
DEFAULT_PIPELINE_RESUME_STALE_MINUTES: Final = 8
PIPELINE_RESUME_STALE_MINUTES_MIN: Final = 1
PIPELINE_RESUME_STALE_MINUTES_MAX: Final = 120

SCAN_FETCH_MAX_JOB_RETRIES: Final = 5
SCAN_FETCH_CONCURRENCY_STEPS: Final = (10, 6, 2, 1)
SCAN_FETCH_SUCCESS_STREAK_FOR_RAISE: Final = 3
SCAN_FETCH_BATCH_BACKOFF_MS: Final = (1000, 800, 200)
SCAN_FETCH_JOB_BACKOFF_CAP_SEC: Final = 16.0

# iTunes RSS 会拒绝 python-httpx 等默认 UA，需模拟浏览器
DEFAULT_APPSTORE_USER_AGENT: Final = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

HTTP_MAX_RETRIES: Final = 5
HTTP_RETRYABLE_STATUS: Final = frozenset({403, 408, 429, 500, 502, 503, 504})
HTTP_REQUEST_JITTER_SEC: Final = (0.04, 0.14)
HTTP_403_EXTRA_DELAY_SEC: Final = (0.8, 2.0)

# --- 区域 ---
DEFAULT_REGION_PRESET: Final = "us-eu"
BLOCKED_REGION_CODES: Final = frozenset({"cn", "hk", "mo", "tw"})

DEFAULT_STORE_REGIONS: Final = [
    {"code": "us", "name": "United States", "name_zh": "美国"},
    {"code": "gb", "name": "United Kingdom", "name_zh": "英国"},
    {"code": "de", "name": "Germany", "name_zh": "德国"},
    {"code": "fr", "name": "France", "name_zh": "法国"},
    {"code": "es", "name": "Spain", "name_zh": "西班牙"},
    {"code": "it", "name": "Italy", "name_zh": "意大利"},
    {"code": "nl", "name": "Netherlands", "name_zh": "荷兰"},
    {"code": "se", "name": "Sweden", "name_zh": "瑞典"},
    {"code": "pl", "name": "Poland", "name_zh": "波兰"},
    {"code": "ie", "name": "Ireland", "name_zh": "爱尔兰"},
    {"code": "pt", "name": "Portugal", "name_zh": "葡萄牙"},
]

DEFAULT_REGION_PRESETS: Final = {
    "us": ["us"],
    "eu": ["gb", "de", "fr", "es", "it", "nl", "se", "pl", "ie", "pt"],
    "us-eu": [
        "us",
        "gb",
        "de",
        "fr",
        "es",
        "it",
        "nl",
        "se",
        "pl",
        "ie",
        "pt",
    ],
}

# --- 品类 ---
DEFAULT_POPULAR_GENRE_IDS: Final = [6013, 6007, 6012, 6023, 6015, 6017, 6024]

DEFAULT_APP_GENRES: Final = [
    {"id": 6000, "name": "Business", "name_zh": "商务", "search_term": "business"},
    {"id": 6001, "name": "Weather", "name_zh": "天气", "search_term": "weather"},
    {"id": 6002, "name": "Utilities", "name_zh": "工具", "search_term": "utilities"},
    {"id": 6003, "name": "Travel", "name_zh": "旅游", "search_term": "travel"},
    {"id": 6004, "name": "Sports", "name_zh": "体育", "search_term": "sports"},
    {"id": 6005, "name": "Social Networking", "name_zh": "社交", "search_term": "social"},
    {"id": 6006, "name": "Reference", "name_zh": "参考", "search_term": "reference"},
    {"id": 6007, "name": "Productivity", "name_zh": "效率", "search_term": "productivity"},
    {"id": 6008, "name": "Photo & Video", "name_zh": "摄影与录像", "search_term": "photo video"},
    {"id": 6009, "name": "News", "name_zh": "新闻", "search_term": "news"},
    {"id": 6010, "name": "Navigation", "name_zh": "导航", "search_term": "navigation"},
    {"id": 6011, "name": "Music", "name_zh": "音乐", "search_term": "music"},
    {"id": 6012, "name": "Lifestyle", "name_zh": "生活", "search_term": "lifestyle"},
    {"id": 6013, "name": "Health & Fitness", "name_zh": "健康健美", "search_term": "health fitness"},
    {"id": 6014, "name": "Games", "name_zh": "游戏", "search_term": "games"},
    {"id": 6015, "name": "Finance", "name_zh": "财务", "search_term": "finance"},
    {"id": 6016, "name": "Entertainment", "name_zh": "娱乐", "search_term": "entertainment"},
    {"id": 6017, "name": "Education", "name_zh": "教育", "search_term": "education"},
    {"id": 6018, "name": "Books", "name_zh": "图书", "search_term": "books"},
    {"id": 6020, "name": "Medical", "name_zh": "医疗", "search_term": "medical"},
    {"id": 6023, "name": "Food & Drink", "name_zh": "美食佳饮", "search_term": "food drink"},
    {"id": 6024, "name": "Shopping", "name_zh": "购物", "search_term": "shopping"},
    {"id": 6026, "name": "Developer Tools", "name_zh": "开发者工具", "search_term": "developer tools"},
    {"id": 6027, "name": "Graphics & Design", "name_zh": "图形和设计", "search_term": "design"},
]

# --- 工作区 / 服务 ---
DEFAULT_WORKSPACE: Final = "./workspace"
DEFAULT_HOST: Final = "127.0.0.1"
DEFAULT_PORT: Final = 8787
DEFAULT_DEFAULT_REGIONS: Final = DEFAULT_REGION_PRESET

SETTINGS_FILENAME: Final = "settings.json"

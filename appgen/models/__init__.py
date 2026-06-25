from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class PipelineStage(str, Enum):
    SCOUT = "scout"
    ANALYST = "analyst"
    PM = "pm"
    DESIGNER = "designer"
    DEV_INIT = "dev_init"
    DEV_SCAFFOLD = "dev_scaffold"
    DEV_CODE = "dev_code"
    DEV_VERIFY = "dev_verify"
    QA = "qa"
    STORE = "store"
    COMPLETE = "complete"


class ReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISION_REQUESTED = "revision_requested"


class AppStoreApp(BaseModel):
    app_id: str
    name: str
    bundle_id: str | None = None
    seller: str | None = None
    genre: str | None = None
    price: float | None = None
    rating: float | None = None
    rating_count: int | None = None
    description: str | None = None
    release_notes: str | None = None
    screenshot_urls: list[str] = Field(default_factory=list)
    chart_rank: int | None = None
    chart_category: str | None = None
    source_url: str | None = None


class PainPoint(BaseModel):
    summary: str
    evidence: str
    severity: int = Field(ge=1, le=5, description="1=弱, 5=强")
    frequency: str = "medium"
    target_users: list[str] = Field(default_factory=list)


class OpportunityBrief(BaseModel):
    """Scout Agent 输出的商机简报。"""

    title: str
    one_liner: str
    category: str
    inspiration_apps: list[AppStoreApp] = Field(default_factory=list)
    market_signals: list[str] = Field(default_factory=list)
    pain_points: list[PainPoint] = Field(default_factory=list)
    differentiation_angle: str = ""
    confidence_score: int = Field(ge=0, le=100, default=50)


class RequirementSpec(BaseModel):
    """Analyst Agent 拆解后的需求规格。"""

    problem_statement: str
    user_stories: list[str] = Field(default_factory=list)
    functional_requirements: list[str] = Field(default_factory=list)
    non_functional_requirements: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    success_metrics: list[str] = Field(default_factory=list)
    mvp_scope: list[str] = Field(default_factory=list)
    v2_ideas: list[str] = Field(default_factory=list)


class MonetizationTier(BaseModel):
    name: str
    price: str
    features: list[str] = Field(default_factory=list)


class PRDDocument(BaseModel):
    """PM Agent 生成的 PRD。"""

    product_name: str
    display_name: str = ""
    display_name_zh_hant: str = ""
    marketing_name_en: str = ""
    tagline: str
    background: str
    target_audience: list[str] = Field(default_factory=list)
    user_needs: list[str] = Field(default_factory=list)
    competitive_landscape: list[str] = Field(default_factory=list)
    core_features: list[str] = Field(default_factory=list)
    mvp_features: list[str] = Field(default_factory=list)
    later_features: list[str] = Field(default_factory=list)
    not_doing: list[str] = Field(default_factory=list)
    monetization: list[MonetizationTier] = Field(default_factory=list)
    iteration_roadmap: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    raw_markdown: str = ""


class ScreenSpec(BaseModel):
    model_config = {"populate_by_name": True}

    name: str
    purpose: str
    ui_elements: list[str] = Field(default_factory=list)
    interactions: list[str] = Field(default_factory=list)
    ui_copy: dict[str, str] = Field(default_factory=dict, alias="copy")
    navigation: str = ""


class DesignSpec(BaseModel):
    """Designer Agent 生成的简易设计稿规格。"""

    design_principles: list[str] = Field(default_factory=list)
    color_palette: dict[str, str] = Field(default_factory=dict)
    typography: dict[str, str] = Field(default_factory=dict)
    screens: list[ScreenSpec] = Field(default_factory=list)
    wireframe_notes: str = ""
    raw_markdown: str = ""


class DevInitPlan(BaseModel):
    platform: str = "ios"
    tech_stack: list[str] = Field(default_factory=list)
    project_structure: list[str] = Field(default_factory=list)
    modules: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    scaffold_commands: list[str] = Field(default_factory=list)
    estimated_days: int = 7
    bundle_id: str = ""
    scheme_name: str = ""


class SwiftSourceFile(BaseModel):
    """单 Swift 源文件（DevCode Agent 输出）。"""

    relative_path: str
    content: str


class DevCodeManifest(BaseModel):
    """功能编码阶段产物清单。"""

    product_name: str
    files_written: list[str] = Field(default_factory=list)
    screens_implemented: list[str] = Field(default_factory=list)
    mvp_features_covered: list[str] = Field(default_factory=list)
    implementation_notes: str = ""


class DevCodeOutput(BaseModel):
    """LLM 功能编码输出（一批 Swift 文件）。"""

    files: list[SwiftSourceFile] = Field(default_factory=list)
    screens_implemented: list[str] = Field(default_factory=list)
    mvp_features_covered: list[str] = Field(default_factory=list)
    implementation_notes: str = ""


class DevCodeFixOutput(BaseModel):
    """编译修复：仅提交需修改的文件。"""

    files: list[SwiftSourceFile] = Field(default_factory=list)
    fix_summary: str = ""


class BuildReport(BaseModel):
    """Xcode 编译验证结果。"""

    success: bool = False
    skipped: bool = False
    scheme: str = ""
    attempts: int = 0
    errors: list[str] = Field(default_factory=list)
    log_tail: str = ""
    message: str = ""


class TestPlan(BaseModel):
    test_strategy: str = ""
    unit_tests: list[str] = Field(default_factory=list)
    integration_tests: list[str] = Field(default_factory=list)
    manual_checklist: list[str] = Field(default_factory=list)
    release_criteria: list[str] = Field(default_factory=list)


class LocalizedMetadata(BaseModel):
    locale: str
    title: str
    subtitle: str
    keywords: list[str] = Field(default_factory=list)
    promotional_text: str = ""
    description: str = ""
    whats_new: str = ""


class StoreListing(BaseModel):
    """Store Agent 生成的上架物料。"""

    app_name: str
    bundle_id_suggestion: str = ""
    category_primary: str = ""
    category_secondary: str | None = None
    age_rating_notes: str = ""
    privacy_policy_outline: str = ""
    support_url_placeholder: str = ""
    metadata: list[LocalizedMetadata] = Field(default_factory=list)
    screenshot_captions: list[str] = Field(default_factory=list)
    review_notes_for_apple: str = ""


class ReviewGate(BaseModel):
    stage: PipelineStage
    status: ReviewStatus = ReviewStatus.PENDING
    reviewer_notes: str = ""
    reviewed_at: datetime | None = None


class PipelineRun(BaseModel):
    id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    current_stage: PipelineStage = PipelineStage.SCOUT
    status: str = "running"  # running | paused | completed | failed
    seed_keyword: str | None = None
    seed_category: str | None = None

    opportunity: OpportunityBrief | None = None
    requirements: RequirementSpec | None = None
    prd: PRDDocument | None = None
    design: DesignSpec | None = None
    dev_plan: DevInitPlan | None = None
    dev_code_manifest: DevCodeManifest | None = None
    build_report: BuildReport | None = None
    test_plan: TestPlan | None = None
    store_listing: StoreListing | None = None

    reviews: list[ReviewGate] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)
    logs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def log(self, message: str) -> None:
        ts = datetime.now(UTC).isoformat()
        self.logs.append(f"[{ts}] {message}")
        self.updated_at = datetime.now(UTC)
        from appgen.run_state import touch_stage_heartbeat

        touch_stage_heartbeat(self)

    def artifact_path(self, name: str) -> str | None:
        return self.artifacts.get(name)

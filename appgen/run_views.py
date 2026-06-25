from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from appgen.models import PipelineRun, PipelineStage, ReviewStatus
from appgen.review import STAGE_LABELS
from appgen.run_state import (
    is_run_resumable,
    resume_block_reason,
    resolve_active_stage,
    stage_activity_at,
)
from appgen.runtime_settings import runtime_settings
from appgen.pipeline_tasks import is_pipeline_active
from appgen.storage import ArtifactStore

PIPELINE_STAGES: list[PipelineStage] = [
    PipelineStage.SCOUT,
    PipelineStage.ANALYST,
    PipelineStage.PM,
    PipelineStage.DESIGNER,
    PipelineStage.DEV_INIT,
    PipelineStage.DEV_SCAFFOLD,
    PipelineStage.DEV_CODE,
    PipelineStage.DEV_VERIFY,
    PipelineStage.QA,
    PipelineStage.STORE,
]

# 各阶段可阅读的文档产物（不含代码）
STAGE_DOCUMENT_ARTIFACTS: dict[PipelineStage, list[str]] = {
    PipelineStage.SCOUT: ["01_opportunity.json"],
    PipelineStage.ANALYST: ["02_requirements.json"],
    PipelineStage.PM: ["03_prd.md", "03_prd.json"],
    PipelineStage.DESIGNER: ["04_design.md", "04_design.json"],
    PipelineStage.DEV_INIT: ["05_dev_plan.json"],
    PipelineStage.DEV_SCAFFOLD: ["project/README.md", "project/project.yml"],
    PipelineStage.DEV_CODE: ["05_dev_manifest.json"],
    PipelineStage.DEV_VERIFY: ["05_build_report.json"],
    PipelineStage.QA: ["06_test_plan.md", "06_test_plan.json"],
    PipelineStage.STORE: [
        "07_store_listing.md",
        "07_store_listing.json",
        "07_privacy_policy.html",
    ],
}

STAGE_SECTION_KEY: dict[PipelineStage, str] = {
    PipelineStage.SCOUT: "opportunity",
    PipelineStage.ANALYST: "requirements",
    PipelineStage.PM: "prd",
    PipelineStage.DESIGNER: "design",
    PipelineStage.DEV_INIT: "dev",
    PipelineStage.DEV_SCAFFOLD: "dev_scaffold",
    PipelineStage.DEV_CODE: "dev_code",
    PipelineStage.DEV_VERIFY: "dev_verify",
    PipelineStage.QA: "test",
    PipelineStage.STORE: "store",
}

CODE_EXTENSIONS = {
    ".swift", ".m", ".h", ".py", ".ts", ".tsx", ".js", ".jsx",
    ".go", ".rs", ".java", ".kt", ".gradle", ".pbxproj", ".xcscheme",
    ".xcworkspace", ".xcodeproj",
}

DOCUMENT_EXTENSIONS = {".md", ".json", ".html", ".txt", ".yaml", ".yml", ".xml"}

DOCUMENT_LABELS: dict[str, str] = {
    "01_opportunity.json": "商机简报",
    "02_requirements.json": "需求规格",
    "03_prd.md": "PRD 文档",
    "03_prd.json": "PRD 数据",
    "04_design.md": "设计稿说明",
    "04_design.json": "设计规格",
    "05_dev_plan.json": "开发计划",
    "05_dev_manifest.json": "编码清单",
    "05_build_report.json": "编译报告",
    "project/README.md": "项目说明",
    "project/project.yml": "XcodeGen 配置",
    "06_test_plan.md": "测试计划",
    "06_test_plan.json": "测试数据",
    "07_store_listing.md": "上架文案",
    "07_store_listing.json": "上架数据",
    "07_privacy_policy.html": "隐私政策",
}

STAGE_ARTIFACTS: dict[PipelineStage, list[str]] = {
    PipelineStage.SCOUT: ["01_opportunity.json"],
    PipelineStage.ANALYST: ["02_requirements.json"],
    PipelineStage.PM: ["03_prd.json", "03_prd.md"],
    PipelineStage.DESIGNER: ["04_design.json", "04_design.md"],
    PipelineStage.DEV_INIT: ["05_dev_plan.json"],
    PipelineStage.DEV_SCAFFOLD: ["project/"],
    PipelineStage.DEV_CODE: ["05_dev_manifest.json"],
    PipelineStage.DEV_VERIFY: ["05_build_report.json"],
    PipelineStage.QA: ["06_test_plan.json", "06_test_plan.md"],
    PipelineStage.STORE: ["07_store_listing.json", "07_store_listing.md"],
}

VIEW_SECTIONS: dict[str, tuple[PipelineStage, list[str]]] = {
    "opportunity": (PipelineStage.SCOUT, STAGE_DOCUMENT_ARTIFACTS[PipelineStage.SCOUT]),
    "requirements": (PipelineStage.ANALYST, STAGE_DOCUMENT_ARTIFACTS[PipelineStage.ANALYST]),
    "prd": (PipelineStage.PM, STAGE_DOCUMENT_ARTIFACTS[PipelineStage.PM]),
    "design": (PipelineStage.DESIGNER, STAGE_DOCUMENT_ARTIFACTS[PipelineStage.DESIGNER]),
    "dev": (PipelineStage.DEV_INIT, STAGE_DOCUMENT_ARTIFACTS[PipelineStage.DEV_INIT]),
    "dev_scaffold": (PipelineStage.DEV_SCAFFOLD, STAGE_DOCUMENT_ARTIFACTS[PipelineStage.DEV_SCAFFOLD]),
    "dev_code": (PipelineStage.DEV_CODE, STAGE_DOCUMENT_ARTIFACTS[PipelineStage.DEV_CODE]),
    "dev_verify": (PipelineStage.DEV_VERIFY, STAGE_DOCUMENT_ARTIFACTS[PipelineStage.DEV_VERIFY]),
    "test": (PipelineStage.QA, STAGE_DOCUMENT_ARTIFACTS[PipelineStage.QA]),
    "store": (PipelineStage.STORE, STAGE_DOCUMENT_ARTIFACTS[PipelineStage.STORE]),
}


def is_code_artifact(path: str) -> bool:
    """判断是否为代码类产物（Web 端不展示）。"""
    normalized = path.replace("\\", "/")
    if normalized.startswith("project/") and not normalized.endswith("README.md"):
        return True
    suffix = Path(path).suffix.lower()
    return suffix in CODE_EXTENSIONS


def is_readable_document(path: str) -> bool:
    if is_code_artifact(path):
        return False
    suffix = Path(path).suffix.lower()
    return suffix in DOCUMENT_EXTENSIONS


def _artifact_type(name: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix == ".md":
        return "markdown"
    if suffix == ".json":
        return "json"
    if suffix == ".html":
        return "html"
    if suffix == ".txt":
        return "text"
    return "text"


def _artifact_label(name: str) -> str:
    if name in DOCUMENT_LABELS:
        return DOCUMENT_LABELS[name]
    if name.startswith("fastlane/metadata/"):
        parts = name.split("/")
        return f"元数据 {parts[-2]} · {parts[-1]}"
    return name


def list_stage_documents(run: PipelineRun, store: ArtifactStore, stage: PipelineStage) -> list[dict[str, Any]]:
    """列出某阶段所有可阅读文档（不含代码）。"""
    docs: list[dict[str, Any]] = []
    seen: set[str] = set()

    for name in STAGE_DOCUMENT_ARTIFACTS.get(stage, []):
        if name in seen:
            continue
        if store.artifact_exists(run.id, name) or name in run.artifacts:
            seen.add(name)
            docs.append({
                "name": name,
                "type": _artifact_type(name),
                "label": _artifact_label(name),
            })

    if stage == PipelineStage.STORE:
        for name in sorted(run.artifacts):
            if name.startswith("fastlane/metadata/") and name.endswith(".txt") and name not in seen:
                seen.add(name)
                docs.append({
                    "name": name,
                    "type": "text",
                    "label": _artifact_label(name),
                })
        if store.list_dir(run.id, "fastlane/metadata"):
            for rel in store.list_dir(run.id, "fastlane/metadata"):
                name = f"fastlane/metadata/{rel}"
                if name not in seen and is_readable_document(name):
                    seen.add(name)
                    docs.append({
                        "name": name,
                        "type": "text",
                        "label": _artifact_label(name),
                    })

    return docs


def load_document(store: ArtifactStore, run_id: str, name: str) -> dict[str, Any]:
    if is_code_artifact(name):
        raise PermissionError(f"代码产物不在 Web 端展示: {name}")
    if not is_readable_document(name):
        raise PermissionError(f"不支持的文档类型: {name}")

    text = store.load_text(run_id, name)
    doc_type = _artifact_type(name)
    content: Any = text
    if doc_type == "json":
        content = json.loads(text)
    return {
        "name": name,
        "type": doc_type,
        "label": _artifact_label(name),
        "content": content,
    }


def _stage_has_output(
    run: PipelineRun,
    stage: PipelineStage,
    store: ArtifactStore | None = None,
) -> bool:
    if stage == PipelineStage.DEV_SCAFFOLD:
        if store:
            return store.artifact_exists(run.id, "project/project.yml")
        return "project/project.yml" in run.artifacts or "project/" in run.artifacts
    return {
        PipelineStage.SCOUT: run.opportunity is not None,
        PipelineStage.ANALYST: run.requirements is not None,
        PipelineStage.PM: run.prd is not None,
        PipelineStage.DESIGNER: run.design is not None,
        PipelineStage.DEV_INIT: run.dev_plan is not None,
        PipelineStage.DEV_CODE: run.dev_code_manifest is not None,
        PipelineStage.DEV_VERIFY: run.build_report is not None,
        PipelineStage.QA: run.test_plan is not None,
        PipelineStage.STORE: run.store_listing is not None,
    }.get(stage, False)


def _latest_review(run: PipelineRun, stage: PipelineStage):
    for gate in reversed(run.reviews):
        if gate.stage == stage:
            return gate
    return None


def pending_review_stage(run: PipelineRun) -> PipelineStage | None:
    for gate in reversed(run.reviews):
        if gate.status == ReviewStatus.PENDING:
            return gate.stage
    return None


def build_stage_progress(run: PipelineRun, store: ArtifactStore | None = None) -> list[dict[str, Any]]:
    current_idx = (
        PIPELINE_STAGES.index(run.current_stage)
        if run.current_stage in PIPELINE_STAGES
        else len(PIPELINE_STAGES)
    )
    active_stage = resolve_active_stage(run)

    rows: list[dict[str, Any]] = []
    for idx, stage in enumerate(PIPELINE_STAGES):
        review = _latest_review(run, stage)
        has_output = _stage_has_output(run, stage, store)
        artifacts = [name for name in STAGE_ARTIFACTS.get(stage, []) if name in run.artifacts]

        if review:
            review_status = review.status.value
        elif has_output:
            review_status = "skipped"
        elif idx < current_idx:
            review_status = "unknown"
        else:
            review_status = "pending"

        if run.status == "completed" or (has_output and review and review.status == ReviewStatus.APPROVED):
            stage_status = "done"
        elif stage == active_stage and run.status == "running":
            stage_status = "running" if not has_output else "review"
        elif stage == run.current_stage and run.status in {"running", "paused", "failed"}:
            stage_status = run.status if not has_output else "review"
        elif has_output:
            stage_status = "review" if review and review.status == ReviewStatus.PENDING else "done"
        elif idx < current_idx:
            stage_status = "done"
        else:
            stage_status = "pending"

        if store:
            documents = list_stage_documents(run, store, stage)
        else:
            documents = [
                {"name": n, "type": _artifact_type(n), "label": _artifact_label(n)}
                for n in STAGE_DOCUMENT_ARTIFACTS.get(stage, [])
                if n in run.artifacts
            ]

        rows.append(
            {
                "stage": stage.value,
                "section": STAGE_SECTION_KEY.get(stage, stage.value),
                "label": STAGE_LABELS.get(stage, stage.value),
                "status": stage_status,
                "has_output": has_output,
                "review_status": review_status,
                "review_notes": review.reviewer_notes if review else "",
                "reviewed_at": review.reviewed_at.isoformat() if review and review.reviewed_at else None,
                "artifacts": artifacts,
                "documents": documents,
            }
        )
    return rows


def run_summary(run: PipelineRun) -> dict[str, Any]:
    active = resolve_active_stage(run)
    stale_minutes = int(runtime_settings.get().pipeline_resume_stale_minutes)
    pipeline_active = is_pipeline_active(run.id)
    block_reason = resume_block_reason(
        run,
        stale_minutes=stale_minutes,
        pipeline_active=pipeline_active,
    )
    return {
        "id": run.id,
        "status": run.status,
        "current_stage": run.current_stage.value,
        "seed_keyword": run.seed_keyword,
        "seed_category": run.seed_category,
        "opportunity_title": run.opportunity.title if run.opportunity else None,
        "product_name": run.prd.product_name if run.prd else None,
        "pending_review": pending_review_stage(run).value if pending_review_stage(run) else None,
        "auto_review": bool(run.metadata.get("auto_review")),
        "resumable": is_run_resumable(
            run,
            stale_minutes=stale_minutes,
            pipeline_active=pipeline_active,
        ),
        "resume_block_reason": block_reason,
        "pipeline_active": pipeline_active,
        "pipeline_resume_stale_minutes": stale_minutes,
        "stage_activity_at": stage_activity_at(run).isoformat(),
        "active_stage": active.value if active else None,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
    }


def resolve_section_content(store: ArtifactStore, run: PipelineRun, section: str) -> dict[str, Any]:
    if section not in VIEW_SECTIONS:
        raise ValueError(f"未知板块: {section}，可选: {', '.join(VIEW_SECTIONS)}")

    stage, candidates = VIEW_SECTIONS[section]
    docs = list_stage_documents(run, store, stage)
    if not docs:
        if not _stage_has_output(run, stage, store):
            raise FileNotFoundError(f"运行 {run.id} 的 {section} 阶段尚未产出")
        raise FileNotFoundError(f"运行 {run.id} 缺少 {section} 文档产物")

    # 优先返回 markdown/html，否则第一个文档
    for preferred in candidates:
        for doc in docs:
            if doc["name"] == preferred:
                return load_document(store, run.id, doc["name"])
    return load_document(store, run.id, docs[0]["name"])

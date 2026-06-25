import pytest

from appgen.models import PipelineRun, PipelineStage, ReviewGate, ReviewStatus
from appgen.run_views import (
    build_stage_progress,
    is_code_artifact,
    is_readable_document,
    list_stage_documents,
    resolve_section_content,
)
from appgen.storage import ArtifactStore


def test_build_stage_progress(tmp_path):
    run = PipelineRun(
        id="abc",
        status="paused",
        current_stage=PipelineStage.ANALYST,
        seed_keyword="test",
    )
    run.reviews.append(
        ReviewGate(stage=PipelineStage.SCOUT, status=ReviewStatus.APPROVED, reviewer_notes="ok")
    )
    rows = build_stage_progress(run)
    assert len(rows) == 10
    assert rows[0]["stage"] == "scout"
    assert rows[0]["review_status"] == "approved"
    assert rows[1]["stage"] == "analyst"


def test_resolve_section_prd(tmp_path):
    store = ArtifactStore(tmp_path)
    run = PipelineRun(id="r1")
    store.save_text(run, "03_prd.md", "# Hello PRD\n\nContent")
    store.save_run(run)

    payload = resolve_section_content(store, run, "prd")
    assert payload["type"] == "markdown"
    assert "Hello PRD" in payload["content"]


def test_is_code_artifact():
    assert is_code_artifact("project/Foo/ContentView.swift")
    assert not is_code_artifact("project/README.md")
    assert is_readable_document("03_prd.md")
    assert not is_readable_document("project/App.swift")


def test_list_stage_documents_store(tmp_path):
    store = ArtifactStore(tmp_path)
    run = PipelineRun(id="r1")
    store.save_text(run, "05_dev_plan.json", '{"platform":"ios"}')
    store.save_text(run, "project/README.md", "# Project\n\nDocs only")
    store.save_text(run, "project/project.yml", "name: Test\n")
    store.save_text(run, "project/App.swift", "import SwiftUI")
    run.artifacts["05_dev_plan.json"] = "x"
    run.artifacts["project/README.md"] = "y"
    run.artifacts["project/project.yml"] = "z"
    run.dev_plan = __import__("appgen.models", fromlist=["DevInitPlan"]).DevInitPlan()
    store.save_run(run)

    docs = list_stage_documents(run, store, PipelineStage.DEV_INIT)
    names = [d["name"] for d in docs]
    assert "05_dev_plan.json" in names
    assert "project/README.md" not in names

    scaffold_docs = list_stage_documents(run, store, PipelineStage.DEV_SCAFFOLD)
    scaffold_names = [d["name"] for d in scaffold_docs]
    assert "project/README.md" in scaffold_names
    assert "project/project.yml" in scaffold_names


@pytest.mark.asyncio
async def test_submit_review_reject(tmp_path, monkeypatch):
    from appgen.config import settings
    from appgen.pipeline import PipelineOrchestrator

    monkeypatch.setenv("APPGEN_WORKSPACE", str(tmp_path))
    settings.appgen_workspace = tmp_path

    orch = PipelineOrchestrator()
    run = orch.create_run(keyword="test")
    run.reviews.append(ReviewGate(stage=PipelineStage.SCOUT, status=ReviewStatus.PENDING))
    run.status = "paused"
    orch.store.save_run(run)

    final = await orch.submit_review(run.id, PipelineStage.SCOUT, "reject", "需要重做")
    assert final.status == "paused"
    assert any(
        g.stage == PipelineStage.SCOUT and g.status == ReviewStatus.REJECTED
        for g in final.reviews
    )

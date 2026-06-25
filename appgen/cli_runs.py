from __future__ import annotations

import asyncio
import json
from typing import Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from appgen.config import settings
from appgen.models import PipelineStage
from appgen.pipeline import PipelineOrchestrator
from appgen.run_views import VIEW_SECTIONS, build_stage_progress, resolve_section_content, run_summary
from appgen.review import STAGE_LABELS

review_app = typer.Typer(help="Review 门禁：查看状态、批准、修订、拒绝")
console = Console()


def _orch() -> PipelineOrchestrator:
    return PipelineOrchestrator()


def _print_progress_table(run_id: str, orchestrator: PipelineOrchestrator) -> None:
    run = orchestrator.get_run(run_id)
    table = Table(title=f"流水线进度 — {run_id}")
    table.add_column("阶段")
    table.add_column("产出")
    table.add_column("Review")
    table.add_column("反馈")
    for row in build_stage_progress(run):
        review = row["review_status"]
        if row["review_status"] == "pending" and not row["has_output"]:
            review = "-"
        notes = (row["review_notes"] or "-")[:60]
        table.add_row(
            row["label"],
            "✓" if row["has_output"] else "·",
            review,
            notes,
        )
    console.print(table)


@review_app.command("list")
def review_list(run_id: str = typer.Argument(..., help="运行 ID")) -> None:
    """查看各阶段 Review 状态。"""
    orch = _orch()
    run = orch.get_run(run_id)
    summary = run_summary(run)
    console.print(
        Panel(
            f"状态: {summary['status']}  |  当前阶段: {summary['current_stage']}\n"
            f"待审: {summary['pending_review'] or '无'}",
            title=f"Run {run_id}",
        )
    )
    _print_progress_table(run_id, orch)

    if summary["pending_review"]:
        stage = summary["pending_review"]
        text = orch.review.stage_summary(run, PipelineStage(stage))
        console.print(Panel(text, title=f"待审摘要 — {STAGE_LABELS.get(PipelineStage(stage), stage)}"))


@review_app.command("approve")
def review_approve(
    run_id: str = typer.Argument(...),
    stage: str = typer.Argument(..., help="阶段，如 scout / analyst / pm"),
    notes: str = typer.Option("", "--notes", "-n", help="备注"),
    auto_continue: bool = typer.Option(True, "--continue/--no-continue", help="批准后继续流水线"),
) -> None:
    """批准某阶段并继续下一阶段。"""
    orch = _orch()
    if auto_continue:
        final = asyncio.run(orch.submit_review(run_id, PipelineStage(stage), "approve", notes))
        console.print(f"[green]已批准[/green] {stage}，运行状态: {final.status}")
    else:
        run = orch.get_run(run_id)
        orch.review.approve_web(run, PipelineStage(stage), notes)
        orch.store.save_run(run)
        console.print(f"[green]已批准[/green] {stage}（未继续执行）")


@review_app.command("revise")
def review_revise(
    run_id: str = typer.Argument(...),
    stage: str = typer.Argument(...),
    notes: str = typer.Option(..., "--notes", "-n", prompt=True, help="修订意见"),
) -> None:
    """请求修订并重跑该阶段。"""
    orch = _orch()
    final = asyncio.run(orch.submit_review(run_id, PipelineStage(stage), "revise", notes))
    console.print(f"[yellow]已提交修订[/yellow] {stage}，运行状态: {final.status}")


@review_app.command("reject")
def review_reject(
    run_id: str = typer.Argument(...),
    stage: str = typer.Argument(...),
    notes: str = typer.Option(..., "--notes", "-n", prompt=True, help="拒绝原因"),
) -> None:
    """拒绝某阶段并暂停流水线。"""
    orch = _orch()
    final = asyncio.run(orch.submit_review(run_id, PipelineStage(stage), "reject", notes))
    console.print(f"[red]已拒绝[/red] {stage}，运行状态: {final.status}")


def show_run(
    run_id: str,
    section: Optional[str] = None,
    *,
    orchestrator: PipelineOrchestrator | None = None,
) -> None:
    """查看运行概览或指定板块产物。"""
    orch = orchestrator or _orch()
    run = orch.get_run(run_id)

    if section is None:
        summary = run_summary(run)
        console.print(
            Panel(
                f"状态: [bold]{summary['status']}[/bold]\n"
                f"当前阶段: {summary['current_stage']}\n"
                f"关键词: {summary['seed_keyword'] or '-'}\n"
                f"商机: {summary['opportunity_title'] or '-'}\n"
                f"产品: {summary['product_name'] or '-'}\n"
                f"待审: {summary['pending_review'] or '无'}",
                title=f"Run {run_id}",
            )
        )
        _print_progress_table(run_id, orch)
        console.print(
            "\n查看产物: "
            + " | ".join(f"[bold]appgen show {run_id} {k}[/bold]" for k in VIEW_SECTIONS)
        )
        return

    if section == "progress":
        _print_progress_table(run_id, orch)
        return

    if section == "reviews":
        review_list(run_id)
        return

    try:
        payload = resolve_section_content(orch.store, run, section)
    except (ValueError, FileNotFoundError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    label = section.upper()
    if payload["type"] == "markdown":
        console.print(Panel(Markdown(payload["content"]), title=f"{label} — {payload['name']}"))
    elif payload["type"] == "json":
        console.print(Panel(payload["content"], title=f"{label} — {payload['name']}"))
    elif payload["type"] == "directory":
        table = Table(title=f"{label} — {payload['name']}")
        table.add_column("文件")
        for f in payload["files"][:50]:
            table.add_row(f)
        if len(payload["files"]) > 50:
            table.add_row(f"... 共 {len(payload['files'])} 个文件")
        console.print(table)

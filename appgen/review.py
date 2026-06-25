from __future__ import annotations

from datetime import UTC, datetime

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from appgen.config import settings
from appgen.models import PipelineRun, PipelineStage, ReviewGate, ReviewStatus

console = Console()

STAGE_LABELS = {
    PipelineStage.SCOUT: "需求挖掘 (Scout)",
    PipelineStage.ANALYST: "需求拆解 (Analyst)",
    PipelineStage.PM: "PRD 撰写 (PM)",
    PipelineStage.DESIGNER: "设计稿 (Designer)",
    PipelineStage.DEV_INIT: "开发计划 (DevInit)",
    PipelineStage.DEV_SCAFFOLD: "工程脚手架 (DevScaffold)",
    PipelineStage.DEV_CODE: "功能编码 (DevCode)",
    PipelineStage.DEV_VERIFY: "编译验证 (DevVerify)",
    PipelineStage.QA: "测试验收 (QA)",
    PipelineStage.STORE: "上架物料 (Store)",
}


def is_auto_review(run: PipelineRun) -> bool:
    """全局 auto 模式或单次运行的一键通过开关。"""
    if settings.appgen_review_mode == "auto":
        return True
    return bool(run.metadata.get("auto_review"))


class ReviewManager:
    """人机协同 Review 门禁。"""

    def request_review(self, run: PipelineRun, stage: PipelineStage) -> ReviewGate:
        gate = ReviewGate(stage=stage, status=ReviewStatus.PENDING)
        run.reviews.append(gate)

        if is_auto_review(run):
            gate.status = ReviewStatus.APPROVED
            gate.reviewer_notes = "auto-approved"
            gate.reviewed_at = datetime.now(UTC)
            run.log(f"Review[{stage.value}]: 自动通过")
            return gate

        if settings.appgen_review_mode == "web":
            gate.status = ReviewStatus.PENDING
            run.status = "paused"
            run.log(f"Review[{stage.value}]: 等待 Web 面板确认")
            return gate

        return self._cli_review(run, gate)

    def _cli_review(self, run: PipelineRun, gate: ReviewGate) -> ReviewGate:
        label = STAGE_LABELS.get(gate.stage, gate.stage.value)
        summary = self._stage_summary(run, gate.stage)

        console.print(Panel(summary, title=f"人工 Review — {label}", border_style="cyan"))

        approved = Confirm.ask("是否通过并进入下一阶段？", default=True)
        if approved:
            notes = Prompt.ask("备注（可选）", default="")
            gate.status = ReviewStatus.APPROVED
            gate.reviewer_notes = notes
        else:
            revision = Confirm.ask("是否需要修订当前阶段（否则将拒绝并暂停）？", default=True)
            if revision:
                gate.status = ReviewStatus.REVISION_REQUESTED
                gate.reviewer_notes = Prompt.ask("修订意见")
                run.status = "paused"
            else:
                gate.status = ReviewStatus.REJECTED
                gate.reviewer_notes = Prompt.ask("拒绝原因")
                run.status = "paused"

        gate.reviewed_at = datetime.now(UTC)
        run.log(f"Review[{gate.stage.value}]: {gate.status.value}")
        return gate

    def approve_web(self, run: PipelineRun, stage: PipelineStage, notes: str = "") -> ReviewGate:
        gate = self._find_pending(run, stage)
        gate.status = ReviewStatus.APPROVED
        gate.reviewer_notes = notes
        gate.reviewed_at = datetime.now(UTC)
        if run.status == "paused":
            run.status = "running"
        run.log(f"Review[{stage.value}]: Web 批准")
        return gate

    def reject_web(self, run: PipelineRun, stage: PipelineStage, notes: str) -> ReviewGate:
        gate = self._find_pending(run, stage)
        gate.status = ReviewStatus.REJECTED
        gate.reviewer_notes = notes
        gate.reviewed_at = datetime.now(UTC)
        run.status = "paused"
        run.log(f"Review[{stage.value}]: Web 拒绝")
        return gate

    def revision_web(self, run: PipelineRun, stage: PipelineStage, notes: str) -> ReviewGate:
        gate = self._find_pending(run, stage)
        gate.status = ReviewStatus.REVISION_REQUESTED
        gate.reviewer_notes = notes
        gate.reviewed_at = datetime.now(UTC)
        run.status = "paused"
        run.log(f"Review[{stage.value}]: Web 请求修订 — {notes[:80]}")
        return gate

    def stage_summary(self, run: PipelineRun, stage: PipelineStage) -> str:
        return self._stage_summary(run, stage)

    def _find_pending(self, run: PipelineRun, stage: PipelineStage) -> ReviewGate:
        for gate in reversed(run.reviews):
            if gate.stage == stage and gate.status == ReviewStatus.PENDING:
                return gate
        gate = ReviewGate(stage=stage, status=ReviewStatus.PENDING)
        run.reviews.append(gate)
        return gate

    def _stage_summary(self, run: PipelineRun, stage: PipelineStage) -> str:
        if stage == PipelineStage.SCOUT and run.opportunity:
            o = run.opportunity
            return (
                f"商机: {o.title}\n"
                f"一句话: {o.one_liner}\n"
                f"置信度: {o.confidence_score}\n"
                f"差异化: {o.differentiation_angle}"
            )
        if stage == PipelineStage.ANALYST and run.requirements:
            r = run.requirements
            return (
                f"问题陈述: {r.problem_statement}\n"
                f"MVP: {', '.join(r.mvp_scope)}\n"
                f"不做: {', '.join(r.out_of_scope)}"
            )
        if stage == PipelineStage.PM and run.prd:
            p = run.prd
            return (
                f"产品: {p.product_name}\n"
                f"定位: {p.tagline}\n"
                f"MVP 功能: {', '.join(p.mvp_features)}\n"
                f"付费档: {', '.join(t.name for t in p.monetization)}"
            )
        if stage == PipelineStage.DESIGNER and run.design:
            d = run.design
            screens = ", ".join(s.name for s in d.screens)
            return f"设计原则: {', '.join(d.design_principles)}\n页面: {screens}"
        if stage == PipelineStage.DEV_INIT and run.dev_plan:
            d = run.dev_plan
            return (
                f"技术栈: {', '.join(d.tech_stack)}\n"
                f"模块: {', '.join(d.modules)}\n"
                f"Bundle ID: {d.bundle_id}\n"
                f"预估工期: {d.estimated_days} 天"
            )
        if stage == PipelineStage.DEV_SCAFFOLD:
            root = run.artifacts.get("project_root", "project/")
            return f"Xcode 工程已生成\n路径: {root}\n含 project.yml + Swift 骨架"
        if stage == PipelineStage.DEV_CODE and run.dev_code_manifest:
            m = run.dev_code_manifest
            return (
                f"已写入 {len(m.files_written)} 个文件\n"
                f"屏幕: {', '.join(m.screens_implemented[:8])}\n"
                f"MVP: {', '.join(m.mvp_features_covered[:6])}"
            )
        if stage == PipelineStage.DEV_VERIFY and run.build_report:
            b = run.build_report
            status = "通过" if b.success else "失败"
            return f"编译: {status}\n{b.message}\n尝试次数: {b.attempts}"
        if stage == PipelineStage.QA and run.test_plan:
            t = run.test_plan
            return f"策略: {t.test_strategy}\n手动项: {len(t.manual_checklist)} 条"
        if stage == PipelineStage.STORE and run.store_listing:
            s = run.store_listing
            langs = ", ".join(m.locale for m in s.metadata)
            return f"应用名: {s.app_name}\n语言: {langs}"
        return "暂无摘要"

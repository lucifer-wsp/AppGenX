from __future__ import annotations

import uuid
from typing import Callable

from appgen.agents import (
    AnalystAgent,
    DesignerAgent,
    DevCodeAgent,
    DevInitAgent,
    DevScaffoldAgent,
    DevVerifyAgent,
    PMAgent,
    QAAgent,
    ScoutAgent,
    StoreAgent,
)
from appgen.agents.base import BaseAgent
from appgen.config import settings
from appgen.llm import LLMCallError, LLMClient
from appgen.models import PipelineRun, PipelineStage, ReviewStatus
from appgen.review import ReviewManager
from appgen.run_state import (
    is_run_resumable,
    mark_stage_started,
    next_pipeline_stage,
    resume_block_reason,
    stage_approved,
)
from appgen.runtime_settings import runtime_settings
from appgen.run_views import pending_review_stage
from appgen.storage import ArtifactStore


class PipelineOrchestrator:
    """AppGen 全链路流水线编排器。"""

    STAGE_ORDER: list[PipelineStage] = [
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

    def __init__(self) -> None:
        self.store = ArtifactStore(settings.ensure_workspace())
        self.llm = LLMClient()
        self.review = ReviewManager()
        self._agents: dict[PipelineStage, BaseAgent] = {
            PipelineStage.SCOUT: ScoutAgent(self.llm, self.store),
            PipelineStage.ANALYST: AnalystAgent(self.llm, self.store),
            PipelineStage.PM: PMAgent(self.llm, self.store),
            PipelineStage.DESIGNER: DesignerAgent(self.llm, self.store),
            PipelineStage.DEV_INIT: DevInitAgent(self.llm, self.store),
            PipelineStage.DEV_SCAFFOLD: DevScaffoldAgent(self.llm, self.store),
            PipelineStage.DEV_CODE: DevCodeAgent(self.llm, self.store),
            PipelineStage.DEV_VERIFY: DevVerifyAgent(self.llm, self.store),
            PipelineStage.QA: QAAgent(self.llm, self.store),
            PipelineStage.STORE: StoreAgent(self.llm, self.store),
        }

    def create_run(
        self,
        *,
        keyword: str | None = None,
        category: str | None = None,
        country: str = "us",
        auto_review: bool = False,
    ) -> PipelineRun:
        run = PipelineRun(
            id=uuid.uuid4().hex[:12],
            seed_keyword=keyword,
            seed_category=category,
            metadata={"country": country, "auto_review": auto_review},
        )
        run.log("Pipeline: 新建运行")
        self.store.save_run(run)
        return run

    def _sync_llm_context(self, run: PipelineRun) -> None:
        self.llm.set_pipeline_context(
            opportunity=run.opportunity,
            requirements=run.requirements,
            prd=run.prd,
            design=run.design,
            seed_keyword=run.seed_keyword,
        )

    async def run_until_pause(
        self,
        run: PipelineRun,
        *,
        from_stage: PipelineStage | None = None,
        on_stage_complete: Callable[[PipelineRun, PipelineStage], None] | None = None,
    ) -> PipelineRun:
        start_idx = 0
        if from_stage:
            start_idx = self.STAGE_ORDER.index(from_stage)

        try:
            for stage in self.STAGE_ORDER[start_idx:]:
                if run.status in {"paused", "failed", "completed"}:
                    break

                run.current_stage = stage
                mark_stage_started(run, stage)
                self._sync_llm_context(run)
                agent = self._agents[stage]
                run.log(f"Pipeline: 开始 {agent.name}（{stage.value}）")
                self.store.save_run(run)
                try:
                    run = await agent.run(run)
                except LLMCallError as exc:
                    run.status = "failed"
                    run.log(f"{agent.name}: LLM 失败 — {exc}")
                    self.store.save_run(run)
                    return run
                except Exception as exc:
                    run.status = "failed"
                    run.log(f"{agent.name}: 执行异常 — {exc}")
                    self.store.save_run(run)
                    return run
                self.store.save_run(run)

                if run.status == "failed":
                    return run

                if on_stage_complete:
                    on_stage_complete(run, stage)

                gate = self.review.request_review(run, stage)
                self.store.save_run(run)

                if gate.status == ReviewStatus.REVISION_REQUESTED:
                    self._sync_llm_context(run)
                    try:
                        run = await agent.run(run)
                    except LLMCallError as exc:
                        run.status = "failed"
                        run.log(f"{agent.name}: LLM 失败 — {exc}")
                        self.store.save_run(run)
                        return run
                    gate = self.review.request_review(run, stage)
                    self.store.save_run(run)

                if gate.status != ReviewStatus.APPROVED:
                    run.status = "paused"
                    self.store.save_run(run)
                    return run

            run.current_stage = PipelineStage.COMPLETE
            run.status = "completed"
            run.log("Pipeline: 全链路完成")
            self.store.save_run(run)
            return run
        finally:
            self.llm.clear_pipeline_context()

    def _stage_has_output(self, run: PipelineRun, stage: PipelineStage) -> bool:
        return {
            PipelineStage.SCOUT: run.opportunity is not None,
            PipelineStage.ANALYST: run.requirements is not None,
            PipelineStage.PM: run.prd is not None,
            PipelineStage.DESIGNER: run.design is not None,
            PipelineStage.DEV_INIT: run.dev_plan is not None,
            PipelineStage.DEV_SCAFFOLD: self.store.artifact_exists(run.id, "project/project.yml"),
            PipelineStage.DEV_CODE: run.dev_code_manifest is not None,
            PipelineStage.DEV_VERIFY: run.build_report is not None,
            PipelineStage.QA: run.test_plan is not None,
            PipelineStage.STORE: run.store_listing is not None,
        }.get(stage, False)

    def _stage_approved(self, run: PipelineRun, stage: PipelineStage) -> bool:
        return stage_approved(run, stage)

    async def _continue_after_review(self, run: PipelineRun, stage: PipelineStage) -> PipelineRun:
        gate = self.review.request_review(run, stage)
        self.store.save_run(run)

        if gate.status == ReviewStatus.REVISION_REQUESTED:
            agent = self._agents[stage]
            self._sync_llm_context(run)
            try:
                run = await agent.run(run)
            except LLMCallError as exc:
                run.status = "failed"
                run.log(f"{agent.name}: LLM 失败 — {exc}")
                self.store.save_run(run)
                return run
            gate = self.review.request_review(run, stage)
            self.store.save_run(run)

        if gate.status != ReviewStatus.APPROVED:
            run.status = "paused"
            self.store.save_run(run)
            return run

        next_idx = self.STAGE_ORDER.index(stage) + 1
        if next_idx >= len(self.STAGE_ORDER):
            run.current_stage = PipelineStage.COMPLETE
            run.status = "completed"
            run.log("Pipeline: 全链路完成")
            self.store.save_run(run)
            return run

        return await self.run_until_pause(run, from_stage=self.STAGE_ORDER[next_idx])

    def _resume_stale_minutes(self) -> int:
        return int(runtime_settings.get().pipeline_resume_stale_minutes)

    def _ensure_resumable(self, run: PipelineRun) -> None:
        reason = resume_block_reason(run, stale_minutes=self._resume_stale_minutes())
        if reason:
            raise ValueError(reason)

    async def resume(self, run_id: str) -> PipelineRun:
        run = self.store.load_run(run_id)
        if run.status == "completed":
            return run

        self._ensure_resumable(run)

        # 进程在 Review 提示处被中断：阶段产物已有，但 Review 未完成
        if (
            run.status == "running"
            and self._stage_has_output(run, run.current_stage)
            and not self._stage_approved(run, run.current_stage)
        ):
            return await self._continue_after_review(run, run.current_stage)

        # orphaned running：当前阶段已通过 Review，但后台任务未进入下一阶段
        if run.status == "running" and self._stage_approved(run, run.current_stage):
            nxt = next_pipeline_stage(run.current_stage)
            if nxt is None:
                run.current_stage = PipelineStage.COMPLETE
                run.status = "completed"
                run.log("Pipeline: 全链路完成")
                self.store.save_run(run)
                return run
            run.log(f"Pipeline: 恢复执行（从 {nxt.value}）")
            run.status = "running"
            self.store.save_run(run)
            return await self.run_until_pause(run, from_stage=nxt)

        if run.status == "running" and not self._stage_has_output(run, run.current_stage):
            run.log(f"Pipeline: 恢复执行（重试 {run.current_stage.value}）")
            return await self.run_until_pause(run, from_stage=run.current_stage)

        if run.status not in {"paused", "failed"}:
            return run

        resume_stage = run.current_stage
        if run.status == "paused":
            last_approved_idx = -1
            for idx, stage in enumerate(self.STAGE_ORDER):
                if self._stage_approved(run, stage):
                    last_approved_idx = idx

            next_idx = last_approved_idx + 1
            if next_idx >= len(self.STAGE_ORDER):
                run.current_stage = PipelineStage.COMPLETE
                run.status = "completed"
                self.store.save_run(run)
                return run
            resume_stage = self.STAGE_ORDER[next_idx]

        # failed 且当前阶段已有产物：跳过重复执行，直接进入 Review
        if (
            run.status == "failed"
            and self._stage_has_output(run, resume_stage)
            and not self._stage_approved(run, resume_stage)
        ):
            run.status = "running"
            self.store.save_run(run)
            return await self._continue_after_review(run, resume_stage)

        run.status = "running"
        run.log(f"Pipeline: 恢复执行（从 {resume_stage.value}）")
        self.store.save_run(run)
        return await self.run_until_pause(run, from_stage=resume_stage)

    async def continue_after_approval(self, run_id: str, stage: PipelineStage) -> PipelineRun:
        """某阶段 Review 通过后，从下一阶段继续执行。"""
        run = self.store.load_run(run_id)
        next_idx = self.STAGE_ORDER.index(stage) + 1
        if next_idx >= len(self.STAGE_ORDER):
            run.current_stage = PipelineStage.COMPLETE
            run.status = "completed"
            run.log("Pipeline: 全链路完成")
            self.store.save_run(run)
            return run

        run.status = "running"
        self.store.save_run(run)
        return await self.run_until_pause(run, from_stage=self.STAGE_ORDER[next_idx])

    async def submit_review(
        self,
        run_id: str,
        stage: PipelineStage,
        action: str,
        notes: str = "",
    ) -> PipelineRun:
        """CLI / Web 统一的 Review 提交入口。"""
        run = self.store.load_run(run_id)
        action = action.lower()

        if action == "approve":
            self.review.approve_web(run, stage, notes)
            self.store.save_run(run)
            return await self.continue_after_approval(run_id, stage)

        if action == "revise":
            if not notes.strip():
                raise ValueError("修订必须填写反馈意见")
            self.review.revision_web(run, stage, notes)
            run.status = "running"
            self.store.save_run(run)
            agent = self._agents[stage]
            self._sync_llm_context(run)
            try:
                run = await agent.run(run)
            except LLMCallError as exc:
                run.status = "failed"
                run.log(f"{agent.name}: LLM 失败 — {exc}")
                self.store.save_run(run)
                return run
            self.store.save_run(run)
            return await self._continue_after_review(run, stage)

        if action == "reject":
            if not notes.strip():
                raise ValueError("拒绝必须填写原因")
            self.review.reject_web(run, stage, notes)
            self.store.save_run(run)
            return run

        raise ValueError(f"未知 Review 操作: {action}，可选 approve / revise / reject")

    async def set_auto_review(self, run_id: str, enabled: bool) -> PipelineRun:
        """设置单次运行的一键通过；开启时自动批准待审节点并继续执行。"""
        run = self.store.load_run(run_id)
        run.metadata["auto_review"] = enabled
        self.store.save_run(run)
        run.log(f"Pipeline: 一键通过已{'开启' if enabled else '关闭'}")

        if not enabled:
            return run

        while True:
            run = self.store.load_run(run_id)
            if run.status == "completed":
                return run
            pending = pending_review_stage(run)
            if not pending:
                if run.status in {"paused", "failed"}:
                    run.status = "running"
                    self.store.save_run(run)
                    return await self.resume(run_id)
                return run
            run = await self.submit_review(run_id, pending, "approve", "一键通过")

    def get_run(self, run_id: str) -> PipelineRun:
        return self.store.load_run(run_id)

    def list_runs(self) -> list[PipelineRun]:
        return self.store.list_runs()

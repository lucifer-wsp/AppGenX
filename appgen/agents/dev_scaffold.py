from __future__ import annotations

from appgen.agents.base import BaseAgent
from appgen.models import PipelineRun, PipelineStage
from appgen.tools.ios_project import scaffold_ios_project
from appgen.tools.ios_standards import IOS_DEV_SCAFFOLD_NOTE


class DevScaffoldAgent(BaseAgent):
    """生成 XcodeGen 工程与可编译骨架。"""

    stage = PipelineStage.DEV_SCAFFOLD
    name = "DevScaffold"
    description = "Xcode 工程、目录树、Theme/Router 与页面占位"

    async def run(self, run: PipelineRun) -> PipelineRun:
        if not run.prd or not run.design or not run.dev_plan:
            raise ValueError("DevScaffold 需要 PRD、设计稿与开发计划")

        project_root = self.store.run_dir(run.id) / "project"
        result = scaffold_ios_project(
            project_root,
            run.prd,
            run.design,
            plan_bundle_id=run.dev_plan.bundle_id,
            opportunity=run.opportunity,
        )

        run.dev_plan.scheme_name = result.product_name
        run.dev_plan.bundle_id = result.bundle_id
        self.store.save_json(run, "05_dev_plan.json", run.dev_plan.model_dump())

        run.artifacts["project_root"] = str(project_root)
        run.artifacts["xcode_scheme"] = result.product_name
        run.log(f"DevScaffold: {result.message}（{result.product_name}）— {IOS_DEV_SCAFFOLD_NOTE}")
        return run

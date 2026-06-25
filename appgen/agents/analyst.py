from __future__ import annotations

import json

from appgen.agents.base import BaseAgent
from appgen.models import PipelineRun, PipelineStage, RequirementSpec


class AnalystAgent(BaseAgent):
    """将商机拆解为可执行的需求规格。"""

    stage = PipelineStage.ANALYST
    name = "Analyst"
    description = "需求拆解、细化与 MVP 边界定义"

    async def run(self, run: PipelineRun) -> PipelineRun:
        if not run.opportunity:
            raise ValueError("Analyst 需要 Scout 阶段的 opportunity 产物")

        system = (
            "你是资深需求分析师。"
            "将商机简报拆解为清晰的用户故事、功能需求、非功能需求、成功指标和版本边界。"
            "只输出一个 JSON 对象（RequirementSpec），禁止输出应用列表或 JSON 数组。"
            "不要复述 inspiration_apps，只提炼需求规格。"
        )
        user = (
            f"商机简报:\n{json.dumps(run.opportunity.model_dump(), ensure_ascii=False, indent=2)}\n\n"
            "要求：MVP 范围克制，明确 NOT-DO 和 V2 方向。"
        )

        spec = await self.llm_chat_json(system, user, RequirementSpec)
        run.requirements = spec
        self.store.save_json(run, "02_requirements.json", spec.model_dump())
        run.log(f"Analyst: 拆解完成，MVP 含 {len(spec.mvp_scope)} 项功能")
        return run

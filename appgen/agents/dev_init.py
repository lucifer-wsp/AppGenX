from __future__ import annotations

import json

from appgen.agents.base import BaseAgent
from appgen.models import DevInitPlan, PipelineRun, PipelineStage


class DevInitAgent(BaseAgent):
    """输出 iOS 开发计划（不含代码生成）。"""

    stage = PipelineStage.DEV_INIT
    name = "DevInit"
    description = "技术栈、模块划分、目录规划与工期评估"

    async def run(self, run: PipelineRun) -> PipelineRun:
        if not run.prd or not run.design:
            raise ValueError("DevInit 需要 PRD 与设计稿")

        system = (
            "你是 iOS 技术负责人，负责制定可上线级别的工程计划。"
            "根据 PRD 与设计规格输出 DevInitPlan JSON。\n"
            "要求：\n"
            "- platform 固定 ios；tech_stack 含 SwiftUI、Swift 5.9+、MVVM\n"
            "- project_structure 列出关键 Swift 文件相对路径（Features/、Services/、Domain/）\n"
            "- modules 对应 PRD 的 mvp_features\n"
            "- bundle_id 建议 com.appgen.<product> 格式\n"
            "- scheme_name 与 product_name  PascalCase 一致\n"
            "- scaffold_commands 含 xcodegen generate 与 xcodebuild\n"
            "- 禁止 demo 级简化，按 App Store 上架标准规划"
        )
        user = (
            f"PRD:\n{json.dumps(run.prd.model_dump(), ensure_ascii=False, indent=2)}\n\n"
            f"设计:\n{json.dumps(run.design.model_dump(), ensure_ascii=False, indent=2)}"
        )

        plan = await self.llm_chat_json(system, user, DevInitPlan)
        if not plan.bundle_id:
            from appgen.tools.ios_project import default_bundle_id, sanitize_product_name

            plan.bundle_id = default_bundle_id(sanitize_product_name(run.prd.product_name))
        if not plan.scheme_name:
            from appgen.tools.ios_project import sanitize_product_name

            plan.scheme_name = sanitize_product_name(run.prd.product_name)

        run.dev_plan = plan
        self.store.save_json(run, "05_dev_plan.json", plan.model_dump())
        run.log(f"DevInit: 开发计划已生成（{len(plan.modules)} 模块，预估 {plan.estimated_days} 天）")
        return run

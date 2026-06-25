from __future__ import annotations

import json

from jinja2 import Environment, FileSystemLoader, select_autoescape

from appgen.agents.base import BaseAgent
from appgen.config import settings
from appgen.models import DesignSpec, PipelineRun, PipelineStage
from appgen.tools.ios_standards import IOS_DESIGNER_RULES


class DesignerAgent(BaseAgent):
    """生成简易设计稿规格（UI、交互、文案）。"""

    stage = PipelineStage.DESIGNER
    name = "Designer"
    description = "UI 元素、交互流程、文案与设计原则"

    async def run(self, run: PipelineRun) -> PipelineRun:
        if not run.prd:
            raise ValueError("Designer 需要 PRD 产物")

        system = (
            "你是 iOS 产品设计师。"
            "根据 PRD 输出 DesignSpec JSON：设计原则、色板、字体、各页面 UI 元素、交互、文案。"
            "风格应适合 App Store 上架级品质，但保持 MVP 可落地。\n"
            f"{IOS_DESIGNER_RULES}"
        )
        user = f"PRD:\n{json.dumps(run.prd.model_dump(), ensure_ascii=False, indent=2)}"

        design = await self.llm_chat_json(system, user, DesignSpec)

        env = Environment(
            loader=FileSystemLoader(settings.templates_dir),
            autoescape=select_autoescape(enabled_extensions=()),
        )
        template = env.get_template("design.md.j2")
        design.raw_markdown = template.render(design=design, prd=run.prd)
        run.design = design

        self.store.save_json(run, "04_design.json", design.model_dump())
        self.store.save_text(run, "04_design.md", design.raw_markdown)
        run.log(f"Designer: 设计稿含 {len(design.screens)} 个页面规格")
        return run

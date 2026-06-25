from __future__ import annotations

import json

from jinja2 import Environment, FileSystemLoader, select_autoescape

from appgen.agents.base import BaseAgent
from appgen.config import settings
from appgen.models import PRDDocument, PipelineRun, PipelineStage
from appgen.tools.ios_project import normalize_prd_product_identity
from appgen.tools.search import web_search


class PMAgent(BaseAgent):
    """生成完整 PRD 需求稿。"""

    stage = PipelineStage.PM
    name = "PM"
    description = "PRD 撰写：背景、用户、功能、付费、迭代"

    async def run(self, run: PipelineRun) -> PipelineRun:
        if not run.opportunity or not run.requirements:
            raise ValueError("PM 需要 opportunity 与 requirements")

        competitor_query = f"{run.opportunity.title} app competitors"
        search_results = await web_search(competitor_query)

        system = (
            "你是移动端产品经理，擅长 iOS App PRD。"
            "基于商机与需求规格，输出完整 PRD JSON（PRDDocument schema）。"
            "需包含：背景、目标用户、用户需求、竞品格局、功能设计、付费模式、迭代路线、风险。"
            "命名规范："
            "product_name 必须是英文 PascalCase（如 LeafMinuteCare），用于 Xcode target/scheme，禁止中文；"
            "display_name 是用户桌面显示名（简体中文）；"
            "display_name_zh_hant 是繁体中文桌面显示名（如 一葉微養）；"
            "marketing_name_en 是 App Store 英文推广名，带空格（如 Leaf Minute Care），需符合品类与 ASO。"
        )
        user = (
            f"商机:\n{json.dumps(run.opportunity.model_dump(), ensure_ascii=False, indent=2)}\n\n"
            f"需求规格:\n{json.dumps(run.requirements.model_dump(), ensure_ascii=False, indent=2)}\n\n"
            f"竞品调研:\n{json.dumps(search_results, ensure_ascii=False, indent=2)}"
        )

        prd = await self.llm_chat_json(system, user, PRDDocument)
        prd = normalize_prd_product_identity(prd, run.opportunity)

        env = Environment(
            loader=FileSystemLoader(settings.templates_dir),
            autoescape=select_autoescape(enabled_extensions=()),
        )
        template = env.get_template("prd.md.j2")
        prd.raw_markdown = template.render(prd=prd)
        run.prd = prd

        self.store.save_json(run, "03_prd.json", prd.model_dump())
        self.store.save_text(run, "03_prd.md", prd.raw_markdown)
        run.log(
            f"PM: PRD「{prd.display_name}」已生成"
            f"（Xcode: {prd.product_name}，EN: {prd.marketing_name_en}）"
        )
        return run

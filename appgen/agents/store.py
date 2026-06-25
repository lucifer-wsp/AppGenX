from __future__ import annotations

import json

from jinja2 import Environment, FileSystemLoader, select_autoescape

from appgen.agents.base import BaseAgent
from appgen.config import settings
from appgen.models import PipelineRun, PipelineStage, StoreListing


class StoreAgent(BaseAgent):
    """生成 App Store 上架物料。"""

    stage = PipelineStage.STORE
    name = "Store"
    description = "标题、副标题、描述、多语言、隐私协议大纲"

    async def run(self, run: PipelineRun) -> PipelineRun:
        if not run.prd or not run.design:
            raise ValueError("Store 需要 PRD 与设计稿")

        system = (
            "你是 App Store ASO 与上架专家。"
            "输出 StoreListing JSON：应用名、bundle 建议、分类、年龄分级说明、"
            "隐私政策大纲、多语言 metadata（至少 zh-Hans 与 en-US）、截图文案、审核备注。"
        )
        user = (
            f"PRD:\n{json.dumps(run.prd.model_dump(), ensure_ascii=False, indent=2)}\n\n"
            f"设计:\n{json.dumps(run.design.model_dump(), ensure_ascii=False, indent=2)}"
        )

        listing = await self.llm_chat_json(system, user, StoreListing)
        run.store_listing = listing

        env = Environment(
            loader=FileSystemLoader(settings.templates_dir),
            autoescape=select_autoescape(enabled_extensions=()),
        )

        store_md = env.get_template("store_listing.md.j2").render(listing=listing, prd=run.prd)
        privacy_html = env.get_template("privacy_policy.html.j2").render(
            listing=listing,
            prd=run.prd,
        )

        self.store.save_json(run, "07_store_listing.json", listing.model_dump())
        self.store.save_text(run, "07_store_listing.md", store_md)
        self.store.save_text(run, "07_privacy_policy.html", privacy_html)

        # fastlane metadata 目录结构
        metadata_root = self.store.run_dir(run.id) / "fastlane" / "metadata"
        for meta in listing.metadata:
            locale_dir = metadata_root / meta.locale
            locale_dir.mkdir(parents=True, exist_ok=True)
            (locale_dir / "name.txt").write_text(meta.title, encoding="utf-8")
            (locale_dir / "subtitle.txt").write_text(meta.subtitle, encoding="utf-8")
            (locale_dir / "keywords.txt").write_text(",".join(meta.keywords), encoding="utf-8")
            (locale_dir / "promotional_text.txt").write_text(meta.promotional_text, encoding="utf-8")
            (locale_dir / "description.txt").write_text(meta.description, encoding="utf-8")
            (locale_dir / "release_notes.txt").write_text(meta.whats_new, encoding="utf-8")

        run.artifacts["fastlane_metadata"] = str(metadata_root)
        run.log(f"Store: 上架物料已生成，含 {len(listing.metadata)} 种语言")
        return run

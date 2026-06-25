from __future__ import annotations

import json

import httpx

from appgen.agents.base import BaseAgent
from appgen.models import AppStoreApp, OpportunityBrief, PipelineRun, PipelineStage
from appgen.scan_bridge import brief_from_picked
from appgen.tools.appstore import AppStoreClient
from appgen.tools.search import web_search


def _offline_apps(keyword: str | None, category: str | None) -> list[AppStoreApp]:
    """网络不可用时的占位应用数据。"""
    seed = keyword or category or "focus"
    return [
        AppStoreApp(
            app_id="1000000001",
            name=f"{seed} Pro",
            bundle_id=f"com.example.{seed.replace(' ', '').lower()}",
            seller="Example Inc.",
            genre="Productivity",
            rating=4.2,
            rating_count=1200,
            description=f"Popular {seed} app with mixed reviews about ads and complexity.",
            source_url="https://apps.apple.com",
        ),
        AppStoreApp(
            app_id="1000000002",
            name=f"Simple {seed}",
            bundle_id=f"com.example.simple{seed.replace(' ', '').lower()}",
            seller="Indie Dev",
            genre="Health & Fitness",
            rating=4.6,
            rating_count=340,
            description=f"Minimal {seed} tool praised for clean UI.",
            source_url="https://apps.apple.com",
        ),
    ]


class ScoutAgent(BaseAgent):
    """从 App Store 榜单/搜索发现商机与痛点信号。"""

    stage = PipelineStage.SCOUT
    name = "Scout"
    description = "App Store 需求挖掘与市场信号采集"

    async def run(self, run: PipelineRun) -> PipelineRun:
        picked = run.metadata.get("picked_opportunity")
        if picked:
            return await self._run_from_picked(run, picked)

        client = AppStoreClient(country=run.metadata.get("country", "us"))
        apps: list[AppStoreApp] = []

        try:
            if run.seed_keyword:
                apps = await client.search_apps(run.seed_keyword, limit=8)
                run.log(f"Scout: 搜索关键词「{run.seed_keyword}」，找到 {len(apps)} 个应用")
            else:
                chart = run.seed_category or "top-free"
                apps = await client.fetch_top_charts(chart_type=chart, limit=15)
                run.log(f"Scout: 拉取榜单 {chart}，共 {len(apps)} 个应用")
        except (httpx.HTTPError, OSError) as exc:
            apps = _offline_apps(run.seed_keyword, run.seed_category)
            run.log(f"Scout: App Store 请求失败，使用离线样本 ({exc})")

        detailed = await self._enrich_apps(client, apps[:5])
        if not detailed:
            detailed = _offline_apps(run.seed_keyword, run.seed_category)

        search_context = ""
        if run.seed_keyword:
            try:
                results = await web_search(f"{run.seed_keyword} app store reviews pain points")
                search_context = json.dumps(results[:5], ensure_ascii=False, indent=2)
            except (httpx.HTTPError, OSError) as exc:
                search_context = json.dumps([{"title": "offline", "snippet": str(exc)}])

        system = (
            "你是 App Store 商机侦察专家 Scout。"
            "根据榜单应用、用户评论信号和联网调研，识别可做的 Micro-App 机会。"
            "你必须输出单个 JSON 对象（不是数组），字段符合 OpportunityBrief："
            "title, one_liner, category, market_signals, pain_points, differentiation_angle, confidence_score。"
        )
        user = (
            f"种子关键词: {run.seed_keyword or '无'}\n"
            f"种子分类/榜单: {run.seed_category or 'top-free'}\n\n"
            f"参考应用数据:\n{json.dumps([a.model_dump() for a in detailed], ensure_ascii=False, indent=2)}\n\n"
            f"联网调研:\n{search_context}\n\n"
            "请给出高置信度、可差异化切入的商机简报。只输出一个 JSON 对象。"
        )

        brief = await self.llm_chat_json(system, user, OpportunityBrief)
        brief.inspiration_apps = detailed
        run.opportunity = brief
        self.store.save_json(run, "01_opportunity.json", brief.model_dump())
        run.log(f"Scout: 生成商机「{brief.title}」，置信度 {brief.confidence_score}")
        return run

    async def _run_from_picked(self, run: PipelineRun, picked: dict) -> PipelineRun:
        """scan pick 已选定方向时，直接复用扫描结果，跳过 LLM。"""
        brief = brief_from_picked(picked)
        client = AppStoreClient(country=run.metadata.get("country", "us"))
        keyword = run.seed_keyword or picked.get("suggested_keyword", "")

        apps: list[AppStoreApp] = []
        if keyword:
            try:
                apps = await client.search_apps(keyword, limit=6)
            except (httpx.HTTPError, OSError):
                pass

        if apps:
            brief.inspiration_apps = await self._enrich_apps(client, apps[:5])
        else:
            ref_names = picked.get("reference_apps") or []
            brief.inspiration_apps = [
                AppStoreApp(app_id=f"ref-{i}", name=name, source_url=None)
                for i, name in enumerate(ref_names[:5], start=1)
            ]

        run.opportunity = brief
        self.store.save_json(run, "01_opportunity.json", brief.model_dump())
        scan_id = run.metadata.get("picked_from_scan", "")
        run.log(
            f"Scout: 复用扫描机会「{brief.title}」"
            + (f" (scan {scan_id})" if scan_id else "")
        )
        return run

    async def _enrich_apps(
        self,
        client: AppStoreClient,
        apps: list[AppStoreApp],
    ) -> list[AppStoreApp]:
        detailed: list[AppStoreApp] = []
        for app in apps:
            if not app.app_id or app.app_id.startswith("ref-"):
                detailed.append(app)
                continue
            try:
                detail = await client.lookup_app(app.app_id)
                detailed.append(detail or app)
            except (httpx.HTTPError, OSError):
                detailed.append(app)
        return detailed

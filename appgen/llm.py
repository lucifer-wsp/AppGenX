from __future__ import annotations

import copy
import json
import re
from typing import Any, Literal, TypeVar

from collections.abc import Callable

from openai import OpenAI
from pydantic import BaseModel

from appgen.constants import (
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    LLM_PROFILE_ANALYZE,
    LLM_PROFILE_CODE,
    LLM_PROFILE_DEFAULT,
    LLM_PROVIDER_CURSOR,
    LLM_PROVIDER_MOCK,
    LLM_PROVIDER_OPENAI,
    LLMProfileKind,
    PLACEHOLDER_CURSOR_KEY,
    PLACEHOLDER_OPENAI_KEY,
)
from appgen.runtime_settings import (
    LLMProviderConfig,
    _chain_has_usable_providers,
    merge_stage_providers_with_fallback,
    runtime_settings,
)

T = TypeVar("T", bound=BaseModel)

ProviderName = Literal["mock", "openai", "cursor"]


class LLMCallError(RuntimeError):
    """已配置 LLM provider 但调用失败，禁止静默回退到无关 Mock 数据。"""


def _sanitize_llm_error_detail(detail: str) -> str:
    text = (detail or "").strip()
    if not text:
        return "已配置 provider 但均不可用"
    lower = text.lower()
    if "timed out after" in lower:
        match = re.search(r"timed out after (\d+) seconds?", lower)
        sec = match.group(1) if match else "?"
        return f"Cursor CLI 子进程超时（{sec}s）"
    if "cursor cli 超时" in lower:
        return text[:400]
    if len(text) > 400:
        return text[:400] + "…"
    return text


def _llm_failure_hint(reason: str) -> str:
    lower = reason.lower()
    if "无输出超时" in reason:
        return "模型可能卡住，可重试或换模型；DevCode 已拆分为每批 2 屏。"
    if "总时长超限" in reason:
        return "请减少 DevCode 每批屏幕数，或检查 prompt 是否过大。"
    if "timed out" in lower or "超时" in reason:
        return "DevCode 已启用流式输出；若仍超时请减少每批屏幕数。"
    if any(token in lower for token in ("usage", "quota", "rate limit", "out of")):
        return "Cursor 配额或速率可能已用尽，请检查 Cursor 账户用量。"
    return "请检查设置页 LLM Provider / API Key，或运行 appgen doctor 确认后端可用。"

MOCK_DATA: dict[str, dict[str, Any]] = {
    "OpportunityBrief": {
        "title": "专注番茄钟健康助手",
        "one_liner": "把专注计时与身心放松结合，服务高压职场人",
        "category": "Health & Fitness",
        "market_signals": ["冥想类应用增长", "专注工具评论抱怨广告过多"],
        "pain_points": [
            {
                "summary": "现有专注 App 广告干扰强",
                "evidence": "App Store 评论高频吐槽",
                "severity": 4,
                "frequency": "high",
                "target_users": ["职场白领"],
            }
        ],
        "differentiation_angle": "无广告 + 轻量呼吸训练",
        "confidence_score": 72,
    },
    "RequirementSpec": {
        "problem_statement": "用户需要低打扰的专注与放松工具",
        "user_stories": ["作为上班族，我希望 25 分钟专注后自动提醒休息"],
        "functional_requirements": ["番茄钟", "呼吸练习", "统计面板"],
        "non_functional_requirements": ["启动 < 1s", "离线可用"],
        "out_of_scope": ["社交功能", "账号体系"],
        "success_metrics": ["7 日留存 > 25%"],
        "mvp_scope": ["番茄钟", "呼吸练习", "本地统计"],
        "v2_ideas": ["Apple Watch 同步", "白噪音"],
    },
    "PRDDocument": {
        "product_name": "FocusCalm",
        "display_name": "FocusCalm",
        "display_name_zh_hant": "FocusCalm",
        "marketing_name_en": "Focus Calm",
        "tagline": "专注之间，呼吸一下",
        "background": "高压工作人群需要低摩擦的专注与放松工具。",
        "target_audience": ["25-40 岁职场人", "自由职业者"],
        "user_needs": ["减少广告干扰", "快速进入专注状态"],
        "competitive_landscape": ["Forest", "潮汐", "Calm"],
        "core_features": ["番茄钟", "呼吸训练", "专注统计"],
        "mvp_features": ["番茄钟", "呼吸训练"],
        "later_features": ["小组件", "健康数据同步"],
        "not_doing": ["社区", "直播课"],
        "monetization": [
            {"name": "Free", "price": "¥0", "features": ["基础番茄钟"]},
            {"name": "Pro", "price": "¥28/月", "features": ["无广告", "主题皮肤"]},
        ],
        "iteration_roadmap": ["V1 MVP", "V1.1 小组件", "V2 Watch"],
        "risks": ["竞品同质化", "留存不足"],
        "raw_markdown": "",
    },
    "DesignSpec": {
        "design_principles": ["极简", "低认知负担"],
        "color_palette": {"primary": "#4A90D9", "background": "#F7F9FC"},
        "typography": {"title": "SF Pro Display Semibold", "body": "SF Pro Text"},
        "screens": [
            {
                "name": "Home",
                "purpose": "开始专注",
                "ui_elements": ["大圆形计时器", "开始按钮"],
                "interactions": ["点击开始/暂停"],
                "ui_copy": {"cta": "开始专注"},
                "navigation": "底部 Tab：首页 / 统计 / 设置",
            }
        ],
        "wireframe_notes": "首页单主操作，减少选择",
        "raw_markdown": "",
    },
    "DevInitPlan": {
        "platform": "ios",
        "tech_stack": ["SwiftUI", "Swift 5.9+"],
        "project_structure": ["App/", "Features/", "Services/", "Resources/"],
        "modules": ["Timer", "Breathing", "Stats"],
        "dependencies": [],
        "scaffold_commands": ["xcodegen generate"],
        "estimated_days": 10,
        "bundle_id": "com.appgen.focuscalm",
        "scheme_name": "FocusCalm",
    },
    "DevCodeOutput": {
        "files": [],
        "screens_implemented": ["Home"],
        "mvp_features_covered": ["番茄钟", "呼吸训练"],
        "implementation_notes": "Mock 模式保留 DevScaffold 骨架",
    },
    "DevCodeFixOutput": {
        "files": [],
        "fix_summary": "Mock 无需修复",
    },
    "TestPlan": {
        "test_strategy": "MVP 以手动冒烟 + 核心单元测试为主",
        "unit_tests": ["计时器状态机", "呼吸节奏计算"],
        "integration_tests": ["专注完成通知"],
        "manual_checklist": ["首次启动引导", "后台恢复计时"],
        "release_criteria": ["无崩溃", "核心流程通过"],
    },
    "StoreListing": {
        "app_name": "FocusCalm",
        "bundle_id_suggestion": "com.example.focuscalm",
        "category_primary": "Health & Fitness",
        "age_rating_notes": "4+，无受限内容",
        "privacy_policy_outline": "不收集个人身份信息，仅本地存储专注记录",
        "metadata": [
            {
                "locale": "zh-Hans",
                "title": "FocusCalm 专注呼吸",
                "subtitle": "番茄钟与放松训练",
                "keywords": ["专注", "番茄钟", "呼吸"],
                "promotional_text": "高压时刻，给自己 25 分钟",
                "description": "FocusCalm 帮助你专注工作并在间隙放松。",
                "whats_new": "首次发布",
            },
            {
                "locale": "en-US",
                "title": "FocusCalm Focus & Breathe",
                "subtitle": "Pomodoro with calm breaks",
                "keywords": ["focus", "pomodoro", "breathe"],
                "promotional_text": "25 minutes of calm focus",
                "description": "FocusCalm helps you focus and unwind.",
                "whats_new": "Initial release",
            },
        ],
        "screenshot_captions": ["一键开始专注", "呼吸放松训练", "查看专注趋势"],
        "review_notes_for_apple": "无特殊硬件需求，测试账号不需要",
    },
}


def _slug_product_name(keyword: str | None, title: str | None) -> str:
    for source in (keyword, title):
        if not source:
            continue
        parts = re.findall(r"[a-zA-Z0-9]+", source)
        if parts:
            return "".join(p.capitalize() for p in parts[:4])
    text = (title or keyword or "MicroApp").strip()
    return text[:24] if text else "MicroApp"


def _bundle_id_from_name(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "", name).lower() or "microapp"
    return f"com.appgen.{slug[:24]}"


def _opp_snapshot(ctx: dict[str, Any]) -> dict[str, Any]:
    opp = ctx.get("opportunity")
    if opp is None:
        kw = str(ctx.get("seed_keyword") or "").strip()
        return {
            "title": kw or "Micro App",
            "one_liner": kw or "A focused micro-app opportunity",
            "category": "Productivity",
            "differentiation_angle": "",
            "pain_points": [],
        }
    if isinstance(opp, dict):
        pains = opp.get("pain_points") or []
        if pains and isinstance(pains[0], str):
            pain_models = [
                {"summary": p, "evidence": p, "severity": 3, "frequency": "medium", "target_users": []}
                for p in pains[:5]
            ]
        else:
            pain_models = pains
        return {
            "title": str(opp.get("title") or "Micro App"),
            "one_liner": str(opp.get("one_liner") or ""),
            "category": str(opp.get("category") or "Productivity"),
            "differentiation_angle": str(
                opp.get("differentiation_angle") or opp.get("differentiation") or ""
            ),
            "pain_points": pain_models,
        }
    return {
        "title": opp.title,
        "one_liner": opp.one_liner,
        "category": opp.category,
        "differentiation_angle": opp.differentiation_angle,
        "pain_points": [
            p.model_dump() if hasattr(p, "model_dump") else p for p in (opp.pain_points or [])
        ],
    }


def _build_contextual_mock(model_name: str, ctx: dict[str, Any], template: dict[str, Any]) -> dict[str, Any]:
    """基于当前流水线上下文生成 Mock，避免各阶段复用无关的静态模板。"""
    if not ctx.get("opportunity") and not ctx.get("seed_keyword"):
        return copy.deepcopy(template)

    snap = _opp_snapshot(ctx)
    keyword = str(ctx.get("seed_keyword") or "").strip()
    product = _slug_product_name(keyword, snap["title"])
    bundle = _bundle_id_from_name(product)
    tagline = snap["one_liner"] or snap["title"]
    diff = snap["differentiation_angle"] or tagline
    pain_summaries: list[str] = []
    for p in snap["pain_points"]:
        if isinstance(p, dict):
            pain_summaries.append(str(p.get("summary") or p.get("evidence") or ""))
        else:
            pain_summaries.append(str(p))
    pain_summaries = [p for p in pain_summaries if p.strip()]
    mvp_items = pain_summaries[:3] if pain_summaries else [f"{snap['title']} 核心流程", "设置与偏好"]
    req = ctx.get("requirements")
    req_mvp = req.get("mvp_scope") if isinstance(req, dict) else None
    if req_mvp:
        mvp_items = list(req_mvp)

    if model_name == "OpportunityBrief":
        data = copy.deepcopy(template)
        data.update(
            {
                "title": snap["title"],
                "one_liner": tagline,
                "category": snap["category"],
                "differentiation_angle": diff,
                "confidence_score": 70,
            }
        )
        if pain_summaries:
            data["pain_points"] = [
                {
                    "summary": pain_summaries[0],
                    "evidence": pain_summaries[0],
                    "severity": 4,
                    "frequency": "high",
                    "target_users": ["目标用户"],
                }
            ]
        return data

    if model_name == "RequirementSpec":
        return {
            "problem_statement": tagline or f"用户需要 {snap['title']} 相关能力",
            "user_stories": [
                f"作为用户，我希望通过 {snap['title']} 解决 {pain_summaries[0]}"
                if pain_summaries
                else f"作为用户，我希望使用 {snap['title']}"
            ],
            "functional_requirements": mvp_items,
            "non_functional_requirements": ["启动 < 2s", "离线可用"],
            "out_of_scope": ["社交", "重运营内容库"],
            "success_metrics": ["核心流程 7 日留存 > 20%"],
            "mvp_scope": mvp_items[:5],
            "v2_ideas": ["小组件", "iCloud 同步"],
        }

    if model_name == "PRDDocument":
        xcode_name = re.sub(r"[^A-Za-z0-9]+", "", product) or "AppGenProduct"
        return {
            "product_name": xcode_name,
            "display_name": product,
            "display_name_zh_hant": product,
            "marketing_name_en": re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", xcode_name),
            "tagline": tagline,
            "background": tagline or f"基于商机「{snap['title']}」的 MVP。",
            "target_audience": ["独立开发者目标用户", "App Store 轻度用户"],
            "user_needs": pain_summaries[:3] or [tagline],
            "competitive_landscape": ["同类榜单应用"],
            "core_features": mvp_items,
            "mvp_features": mvp_items[:5],
            "later_features": ["主题扩展", "Widget"],
            "not_doing": ["社区", "直播"],
            "monetization": [
                {"name": "Free", "price": "¥0", "features": ["基础功能"]},
                {"name": "Pro", "price": "¥18/月", "features": ["去广告", "高级功能"]},
            ],
            "iteration_roadmap": ["V1 MVP", "V1.1 优化", "V2 扩展"],
            "risks": ["竞品同质化", "留存不足"],
            "raw_markdown": "",
        }

    if model_name == "DesignSpec":
        return {
            "design_principles": ["极简", "低认知负担"],
            "color_palette": {"primary": "#4A90D9", "background": "#F7F9FC"},
            "typography": {"title": "SF Pro Display Semibold", "body": "SF Pro Text"},
            "screens": [
                {
                    "name": "Home",
                    "purpose": snap["title"],
                    "ui_elements": ["主操作区", "状态摘要"],
                    "interactions": ["点击主操作"],
                    "ui_copy": {"cta": "开始"},
                    "navigation": "底部 Tab：首页 / 设置",
                }
            ],
            "wireframe_notes": f"围绕「{snap['title']}」的单主操作首页",
            "raw_markdown": "",
        }

    if model_name == "DevInitPlan":
        return {
            "platform": "ios",
            "tech_stack": ["SwiftUI", "Swift 5.9+"],
            "project_structure": ["App/", "Features/", "Services/", "Resources/"],
            "modules": mvp_items[:4] or ["Core"],
            "dependencies": [],
            "scaffold_commands": ["xcodegen generate"],
            "estimated_days": 10,
            "bundle_id": bundle,
            "scheme_name": product,
        }

    if model_name == "DevCodeOutput":
        return {
            "files": [],
            "screens_implemented": ["Home"],
            "mvp_features_covered": mvp_items[:5],
            "implementation_notes": f"Mock 模式保留 {product} 脚手架",
        }

    if model_name == "DevCodeFixOutput":
        return {"files": [], "fix_summary": "Mock 无需修复"}

    if model_name == "TestPlan":
        return {
            "test_strategy": f"{product} MVP 手动冒烟 + 核心单元测试",
            "unit_tests": ["主流程状态", "空态与错误态"],
            "integration_tests": ["冷启动到核心操作"],
            "manual_checklist": ["首次启动", "核心流程完成"],
            "release_criteria": ["无崩溃", "MVP 流程可走通"],
        }

    if model_name == "StoreListing":
        return {
            "app_name": product,
            "bundle_id_suggestion": bundle,
            "category_primary": snap["category"] or "Productivity",
            "age_rating_notes": "4+",
            "privacy_policy_outline": "仅本地存储，不上传个人身份信息",
            "metadata": [
                {
                    "locale": "zh-Hans",
                    "title": f"{product} {snap['title'][:12]}",
                    "subtitle": tagline[:30],
                    "keywords": [keyword or snap["title"], "app"],
                    "promotional_text": tagline[:50],
                    "description": tagline,
                    "whats_new": "首次发布",
                },
                {
                    "locale": "en-US",
                    "title": product,
                    "subtitle": tagline[:30],
                    "keywords": [keyword or product.lower(), "app"],
                    "promotional_text": tagline[:50],
                    "description": tagline or product,
                    "whats_new": "Initial release",
                },
            ],
            "screenshot_captions": ["核心流程", "设置", "状态概览"],
            "review_notes_for_apple": "无特殊硬件需求",
        }

    return copy.deepcopy(template)


def _valid_openai_key(api_key: str) -> bool:
    from appgen.runtime_settings import _is_suspicious_llm_key

    text = (api_key or "").strip()
    return bool(text) and text != PLACEHOLDER_OPENAI_KEY and not _is_suspicious_llm_key(text)


def _valid_cursor_key(api_key: str) -> bool:
    from appgen.runtime_settings import _is_suspicious_llm_key

    text = (api_key or "").strip()
    return bool(text) and text != PLACEHOLDER_CURSOR_KEY and not _is_suspicious_llm_key(text)


def _provider_source_for_profile(profile: LLMProfileKind) -> list[LLMProviderConfig]:
    rc = runtime_settings.get()
    if profile == LLM_PROFILE_ANALYZE and rc.llm_analyze_providers:
        merged = merge_stage_providers_with_fallback(rc.llm_analyze_providers, rc.llm_providers)
        if _chain_has_usable_providers(merged):
            return merged
    if profile == LLM_PROFILE_CODE and rc.llm_code_providers:
        merged = merge_stage_providers_with_fallback(rc.llm_code_providers, rc.llm_providers)
        if _chain_has_usable_providers(merged):
            return merged
    return rc.llm_providers


def build_provider_chain(profile: LLMProfileKind = LLM_PROFILE_DEFAULT) -> list[LLMProviderConfig]:
    rc = runtime_settings.get()
    mode = (rc.llm_provider_mode or "auto").lower()

    if mode == LLM_PROVIDER_MOCK:
        return []

    def is_valid(entry: LLMProviderConfig) -> bool:
        if entry.provider == LLM_PROVIDER_CURSOR:
            return _valid_cursor_key(entry.api_key)
        if entry.provider == LLM_PROVIDER_OPENAI:
            return _valid_openai_key(entry.api_key)
        return False

    chain = [entry for entry in _provider_source_for_profile(profile) if is_valid(entry)]

    if mode == LLM_PROVIDER_OPENAI:
        return [entry for entry in chain if entry.provider == LLM_PROVIDER_OPENAI]
    if mode == LLM_PROVIDER_CURSOR:
        cursor_part = [entry for entry in chain if entry.provider == LLM_PROVIDER_CURSOR]
        openai_part = [entry for entry in chain if entry.provider == LLM_PROVIDER_OPENAI]
        return cursor_part + openai_part
    return chain


def resolve_provider(profile: LLMProfileKind = LLM_PROFILE_DEFAULT) -> ProviderName:
    chain = build_provider_chain(profile)
    if not chain:
        return LLM_PROVIDER_MOCK

    first = chain[0]
    if first.provider == LLM_PROVIDER_CURSOR:
        from appgen.llm_cursor import cursor_available_with

        if cursor_available_with(first.api_key):
            return LLM_PROVIDER_CURSOR
        if len(chain) > 1 and chain[1].provider == LLM_PROVIDER_OPENAI:
            return LLM_PROVIDER_OPENAI
        return LLM_PROVIDER_MOCK
    return LLM_PROVIDER_OPENAI


class LLMClient:
    """统一 LLM 客户端：按设置页配置的 provider 列表依次尝试，全部失败则 Mock。"""

    def __init__(self) -> None:
        self._provider: ProviderName | None = None
        self._pipeline_context: dict[str, Any] = {}
        self._last_chat_error: str = ""

    def reset(self) -> None:
        self._provider = None
        self._last_chat_error = ""

    def set_pipeline_context(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if value is None:
                self._pipeline_context.pop(key, None)
            else:
                if hasattr(value, "model_dump"):
                    self._pipeline_context[key] = value.model_dump()
                else:
                    self._pipeline_context[key] = value

    def clear_pipeline_context(self) -> None:
        self._pipeline_context = {}

    def _providers_configured(self, profile: LLMProfileKind = LLM_PROFILE_DEFAULT) -> bool:
        return bool(build_provider_chain(profile))

    def _fail_or_mock(self, model_type: type[T], *, reason: str, profile: LLMProfileKind = LLM_PROFILE_DEFAULT) -> T:
        if self._providers_configured(profile):
            clean = _sanitize_llm_error_detail(reason.removeprefix("LLM 调用失败："))
            hint = _llm_failure_hint(clean)
            raise LLMCallError(f"LLM 调用失败：{clean} {hint}")
        return model_type.model_validate(self._mock_data_for(model_type))

    @property
    def provider(self) -> ProviderName:
        return self.provider_for(LLM_PROFILE_DEFAULT)

    def provider_for(self, profile: LLMProfileKind = LLM_PROFILE_DEFAULT) -> ProviderName:
        return resolve_provider(profile)

    @property
    def enabled(self) -> bool:
        return self.enabled_for(LLM_PROFILE_DEFAULT)

    def enabled_for(self, profile: LLMProfileKind = LLM_PROFILE_DEFAULT) -> bool:
        return self.provider_for(profile) != LLM_PROVIDER_MOCK

    def chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.4,
        json_mode: bool = False,
        on_progress: Callable[[str, int], None] | None = None,
        profile: LLMProfileKind = LLM_PROFILE_DEFAULT,
    ) -> str:
        chain = build_provider_chain(profile)
        if not chain:
            self._last_chat_error = ""
            return json.dumps({"message": "mock"}, ensure_ascii=False)

        last_error: Exception | None = None
        for entry in chain:
            try:
                if entry.provider == LLM_PROVIDER_CURSOR:
                    from appgen.llm_cursor import cursor_available_with, cursor_chat_with

                    if not cursor_available_with(entry.api_key):
                        continue
                    self._provider = LLM_PROVIDER_CURSOR
                    self._last_chat_error = ""
                    return cursor_chat_with(
                        entry,
                        system,
                        user,
                        temperature=temperature,
                        json_mode=json_mode,
                        on_progress=on_progress,
                    )
                if entry.provider == LLM_PROVIDER_OPENAI:
                    self._provider = LLM_PROVIDER_OPENAI
                    self._last_chat_error = ""
                    return self._openai_chat_with(entry, system, user, temperature=temperature)
            except Exception as exc:
                last_error = exc
                continue

        self._provider = LLM_PROVIDER_MOCK
        self._last_chat_error = _sanitize_llm_error_detail(
            str(last_error).strip() if last_error else ""
        )
        return json.dumps({"message": "mock"}, ensure_ascii=False)

    def _openai_chat_with(
        self,
        entry: LLMProviderConfig,
        system: str,
        user: str,
        *,
        temperature: float,
    ) -> str:
        client = OpenAI(
            api_key=entry.api_key,
            base_url=entry.base_url or DEFAULT_LLM_BASE_URL,
        )
        response = client.chat.completions.create(
            model=entry.model or DEFAULT_LLM_MODEL,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""

    def chat_json(
        self,
        system: str,
        user: str,
        model_type: type[T],
        *,
        temperature: float = 0.3,
        on_progress: Callable[[str, int], None] | None = None,
        profile: LLMProfileKind = LLM_PROFILE_DEFAULT,
    ) -> T:
        if not build_provider_chain(profile):
            return model_type.model_validate(self._mock_data_for(model_type))

        schema_hint = json.dumps(model_type.model_json_schema(), ensure_ascii=False, indent=2)
        base_prompt = (
            f"{user}\n\n"
            f"输出类型: {model_type.__name__}\n"
            "你必须只输出一个 JSON 对象（以 { 开头、以 } 结尾），禁止输出 JSON 数组。\n"
            "不要 markdown 代码块，不要解释文字。\n"
            f"JSON Schema:\n{schema_hint}"
        )
        strict_system = (
            f"{system}\n\n"
            "重要：你的回复有且仅有一个 JSON 对象，顶层不能是数组。"
        )

        last_error: Exception | None = None
        for attempt in range(3):
            extra = ""
            if attempt > 0:
                extra = (
                    f"\n\n第 {attempt + 1} 次尝试：上次格式无效（{last_error}）。"
                    "请只输出单个 JSON 对象，字段名必须与 Schema 完全一致。"
                )
            raw = self.chat(
                strict_system,
                base_prompt + extra,
                temperature=temperature,
                json_mode=True,
                on_progress=on_progress,
                profile=profile,
            )
            try:
                data = self._extract_json(raw)
                if isinstance(data, dict) and data.get("message") == "mock":
                    detail = self._last_chat_error or "已配置 provider 但均不可用"
                    return self._fail_or_mock(
                        model_type,
                        reason=f"LLM 调用失败：{detail}",
                        profile=profile,
                    )
                obj = self._coerce_to_model_dict(data, model_type)
                return model_type.model_validate(obj)
            except LLMCallError:
                raise
            except Exception as exc:
                last_error = exc

        return self._fail_or_mock(
            model_type,
            reason=f"LLM 返回格式无效（{last_error}）",
            profile=profile,
        )

    def _schema_keys(self, model_type: type[BaseModel]) -> tuple[set[str], set[str]]:
        schema = model_type.model_json_schema()
        return set(schema.get("properties", {})), set(schema.get("required", []))

    def _score_dict_for_model(self, item: dict[str, Any], model_type: type[BaseModel]) -> int:
        props, required = self._schema_keys(model_type)
        score = sum(3 for key in required if key in item)
        score += sum(1 for key in props if key in item)
        if "app_id" in item or "bundle_id" in item:
            score -= 5
        return score

    def _coerce_to_model_dict(self, data: Any, model_type: type[BaseModel]) -> dict[str, Any]:
        if isinstance(data, dict):
            return data

        if isinstance(data, list):
            dict_items = [item for item in data if isinstance(item, dict)]
            if dict_items:
                best = max(dict_items, key=lambda d: self._score_dict_for_model(d, model_type))
                if self._score_dict_for_model(best, model_type) > 0:
                    return best

            if data and all(isinstance(item, str) for item in data):
                wrapped = self._wrap_string_list(data, model_type)
                if wrapped:
                    return wrapped

        raise ValueError(
            f"无法将 {type(data).__name__} 转为 {model_type.__name__}，"
            f"收到: {str(data)[:200]}"
        )

    def _wrap_string_list(self, items: list[str], model_type: type[BaseModel]) -> dict[str, Any] | None:
        name = model_type.__name__
        if name == "RequirementSpec":
            return {
                "problem_statement": "Users need a focused solution based on the opportunity brief.",
                "user_stories": items,
                "functional_requirements": items,
                "mvp_scope": items[:5],
                "out_of_scope": [],
                "success_metrics": ["User completes core flow without drop-off"],
            }
        if name == "PRDDocument":
            return {
                "product_name": items[0][:80] if items else "App",
                "tagline": items[1] if len(items) > 1 else "",
                "background": items[0] if items else "",
                "target_audience": items[2:4] if len(items) > 2 else [],
                "user_needs": items,
                "core_features": items,
                "mvp_features": items[:5],
                "later_features": [],
                "not_doing": [],
                "monetization": [],
                "iteration_roadmap": [],
                "risks": [],
            }
        return None

    def _mock_data_for(self, model_type: type[BaseModel]) -> dict[str, Any]:
        template = MOCK_DATA.get(model_type.__name__, {"message": "mock"})
        return _build_contextual_mock(model_type.__name__, self._pipeline_context, template)

    def _extract_json(self, text: str) -> Any:
        text = text.strip()
        fence = re.search(r"```(?:json)?\s*([\[\{].*[\]\}])\s*```", text, re.DOTALL)
        if fence:
            text = fence.group(1)

        obj_start = text.find("{")
        if obj_start >= 0:
            try:
                parsed, _ = json.JSONDecoder().raw_decode(text[obj_start:])
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

        arr_start = text.find("[")
        if arr_start >= 0:
            try:
                parsed, _ = json.JSONDecoder().raw_decode(text[arr_start:])
                return parsed
            except json.JSONDecodeError:
                pass

        if obj_start >= 0:
            end = text.rfind("}")
            if end > obj_start:
                return json.loads(text[obj_start : end + 1])

        return json.loads(text)

    def extract_json_list(self, text: str) -> list[Any]:
        text = text.strip()
        fence = re.search(r"```(?:json)?\s*([\[\{].*[\]\}])\s*```", text, re.DOTALL)
        if fence:
            text = fence.group(1)

        arr_start = text.find("[")
        if arr_start >= 0:
            try:
                parsed, _ = json.JSONDecoder().raw_decode(text[arr_start:])
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                pass

        data = self._extract_json(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("opportunities", "items", "results", "data"):
                val = data.get(key)
                if isinstance(val, list):
                    return val
            if "title" in data or "one_liner" in data:
                return [data]
        return []


llm = LLMClient()


def apply_runtime_settings() -> None:
    """热更新后刷新 LLM 与品类/区域缓存。"""
    llm.reset()
    from appgen.tools.genres import refresh_genre_cache
    from appgen.tools.regions import refresh_region_cache

    refresh_genre_cache()
    refresh_region_cache()

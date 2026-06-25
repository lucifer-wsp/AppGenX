from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from appgen.agents.base import BaseAgent
from appgen.models import DevCodeManifest, DevCodeOutput, PipelineRun, PipelineStage
from appgen.tools.ios_project import sanitize_product_name, write_swift_files
from appgen.tools.ios_standards import IOS_PRODUCTION_CODING_RULES


class DevCodeAgent(BaseAgent):
    """按 PRD/设计稿生成功能代码。"""

    stage = PipelineStage.DEV_CODE
    name = "DevCode"
    description = "按设计稿与 PRD 实现 SwiftUI 功能代码"

    BATCH_SIZE = 2

    async def run(self, run: PipelineRun) -> PipelineRun:
        if not run.prd or not run.design or not run.dev_plan:
            raise ValueError("DevCode 需要 PRD、设计稿与开发计划")

        project_root = self.store.run_dir(run.id) / "project"
        if not project_root.exists():
            raise ValueError("DevCode 需要 DevScaffold 已生成 project/")

        product = sanitize_product_name(run.prd.product_name)
        screens = run.design.screens or []
        all_written: list[str] = []
        all_screens: list[str] = []
        all_mvp: list[str] = []
        notes: list[str] = []

        existing = self._list_swift_files(project_root, product)
        all_screen_names = [s.name for s in screens]

        if not screens:
            batches: list[list] = [[]]
        else:
            batches = [
                screens[i : i + self.BATCH_SIZE]
                for i in range(0, len(screens), self.BATCH_SIZE)
            ]

        design_tokens = {
            "design_principles": run.design.design_principles,
            "color_palette": run.design.color_palette,
            "typography": run.design.typography,
            "wireframe_notes": run.design.wireframe_notes,
        }

        for idx, batch in enumerate(batches, start=1):
            batch_names = [s.name for s in batch]
            run.log(f"DevCode: 编码批次 {idx}/{len(batches)} — {', '.join(batch_names) or '核心模块'}")
            self.store.save_run(run)

            system = (
                "你是资深 iOS 工程师，负责将 PRD 与设计稿落地为可上架 SwiftUI 代码。\n"
                f"{IOS_PRODUCTION_CODING_RULES}\n"
                "输出 DevCodeOutput JSON：files 为完整 Swift 源文件（relative_path 相对 project/）。\n"
                f"产品目录名：{product}/\n"
                f"全局设计令牌：\n{json.dumps(design_tokens, ensure_ascii=False, indent=2)}\n"
                "每屏至少生成 Features/{Screen}View.swift；复杂屏增加 ViewModel。\n"
                "MVP 功能须在 Services/ 或 Features/ 中有对应实现。\n"
                "新增 UI 文案时须同时更新三语 Resources/*.lproj/Localizable.strings。\n"
                "复用已有 PrimaryButton、AppTheme、L10n、AppConstants 结构，勿重复定义。"
            )
            user = (
                f"PRD 摘要:\n{json.dumps(self._prd_context(run), ensure_ascii=False, indent=2)}\n\n"
                f"本批次屏幕（完整 DesignSpec）:\n"
                f"{json.dumps(self._design_context(run.design, batch, all_screen_names), ensure_ascii=False, indent=2)}\n\n"
                f"开发计划:\n{json.dumps(self._dev_plan_context(run), ensure_ascii=False, indent=2)}\n\n"
                f"已有 Swift 文件（路径）:\n{json.dumps(existing[:60], ensure_ascii=False)}\n"
            )

            last_progress_log = 0.0
            last_phase = ""

            def on_progress(phase: str, received_chars: int) -> None:
                nonlocal last_progress_log, last_phase
                now = time.monotonic()
                if phase != last_phase or now - last_progress_log >= 8:
                    run.log(f"DevCode: {phase}… 已接收 ~{received_chars} 字符")
                    self.store.save_run(run)
                    last_progress_log = now
                    last_phase = phase

            output = await self.llm_chat_json(
                system,
                user,
                DevCodeOutput,
                on_progress=on_progress,
            )
            pairs = [(f.relative_path, f.content) for f in output.files if f.relative_path and f.content]
            if pairs:
                written = write_swift_files(project_root, pairs)
                all_written.extend(written)
                existing.extend(written)
                run.log(f"DevCode: 批次 {idx} 已写入 {len(written)} 个文件")
                self.store.save_run(run)
            all_screens.extend(output.screens_implemented or batch_names)
            all_mvp.extend(output.mvp_features_covered)
            if output.implementation_notes:
                notes.append(output.implementation_notes)

        manifest = DevCodeManifest(
            product_name=product,
            files_written=sorted(set(all_written)),
            screens_implemented=sorted(set(all_screens)),
            mvp_features_covered=sorted(set(all_mvp)) or list(run.prd.mvp_features),
            implementation_notes="\n".join(notes),
        )
        run.dev_code_manifest = manifest
        self.store.save_json(run, "05_dev_manifest.json", manifest.model_dump())
        run.log(
            f"DevCode: 已写入 {len(manifest.files_written)} 个文件，"
            f"覆盖 {len(manifest.screens_implemented)} 个屏幕"
        )
        return run

    @staticmethod
    def _prd_context(run: PipelineRun) -> dict[str, Any]:
        prd = run.prd
        assert prd is not None
        return {
            "product_name": prd.product_name,
            "display_name": prd.display_name,
            "display_name_zh_hant": prd.display_name_zh_hant,
            "tagline": prd.tagline,
            "target_audience": prd.target_audience,
            "mvp_features": prd.mvp_features,
            "core_features": prd.core_features,
            "not_doing": prd.not_doing,
        }

    @staticmethod
    def _dev_plan_context(run: PipelineRun) -> dict[str, Any]:
        plan = run.dev_plan
        assert plan is not None
        return {
            "platform": plan.platform,
            "tech_stack": plan.tech_stack,
            "modules": plan.modules,
            "project_structure": plan.project_structure,
            "dependencies": plan.dependencies,
            "bundle_id": plan.bundle_id,
            "scheme_name": plan.scheme_name,
        }

    @staticmethod
    def _design_context(design, batch, all_screen_names: list[str]) -> dict[str, Any]:
        batch_names = {s.name for s in batch}
        other = [name for name in all_screen_names if name not in batch_names]
        ctx: dict[str, Any] = {
            "screens": [s.model_dump() for s in design.screens if s.name in batch_names],
        }
        if other:
            ctx["other_screens_not_in_this_batch"] = other
        return ctx

    def _list_swift_files(self, project_root: Path, product: str) -> list[str]:
        base = project_root / product
        if not base.exists():
            return []
        return sorted(str(p.relative_to(project_root)) for p in base.rglob("*.swift"))

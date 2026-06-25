from __future__ import annotations

import asyncio
import json

from appgen.config import settings
from appgen.agents.base import BaseAgent
from appgen.models import BuildReport, DevCodeFixOutput, PipelineRun, PipelineStage
from appgen.tools.ios_project import run_xcode_build, sanitize_product_name, write_swift_files
from appgen.tools.ios_standards import IOS_PRODUCTION_CODING_RULES

MAX_FIX_ATTEMPTS = 3


class DevVerifyAgent(BaseAgent):
    """xcodebuild 编译验证与错误修复循环。"""

    stage = PipelineStage.DEV_VERIFY
    name = "DevVerify"
    description = "Xcode 编译验证与自动修复"

    async def run(self, run: PipelineRun) -> PipelineRun:
        if not run.prd or not run.dev_plan:
            raise ValueError("DevVerify 需要 PRD 与开发计划")

        project_root = self.store.run_dir(run.id) / "project"
        scheme = run.dev_plan.scheme_name or sanitize_product_name(run.prd.product_name)

        report = BuildReport(scheme=scheme)

        if settings.llm_provider == "mock":
            report.success = True
            report.skipped = True
            report.attempts = 0
            report.message = "Mock 模式跳过真实编译"
            run.build_report = report
            self.store.save_json(run, "05_build_report.json", report.model_dump())
            run.log(f"DevVerify: {report.message}")
            return run

        build = run_xcode_build(project_root, scheme)
        report.attempts = 1
        report.log_tail = build.log[-8000:]
        report.errors = build.errors
        report.skipped = build.skipped

        if build.skipped:
            report.success = True
            report.message = f"{build.message}（无 Xcode 环境，跳过编译）"
            run.build_report = report
            self.store.save_json(run, "05_build_report.json", report.model_dump())
            run.log(f"DevVerify: {report.message}")
            return run

        if build.success:
            report.success = True
            report.message = build.message
            run.build_report = report
            self.store.save_json(run, "05_build_report.json", report.model_dump())
            run.log("DevVerify: 编译通过")
            return run

        report.message = build.message
        run.log(f"DevVerify: 首次编译失败，启动修复循环（最多 {MAX_FIX_ATTEMPTS} 次）")

        for attempt in range(2, MAX_FIX_ATTEMPTS + 2):
            fix = await asyncio.to_thread(self._request_fix, run, project_root, build.errors, build.log)
            if fix.files:
                write_swift_files(
                    project_root,
                    [(f.relative_path, f.content) for f in fix.files],
                )
                run.log(f"DevVerify: 修复批次 {attempt - 1} — {fix.fix_summary[:120]}")

            build = run_xcode_build(project_root, scheme)
            report.attempts = attempt
            report.log_tail = build.log[-8000:]
            report.errors = build.errors

            if build.success:
                report.success = True
                report.message = f"第 {attempt} 次编译通过"
                run.build_report = report
                self.store.save_json(run, "05_build_report.json", report.model_dump())
                run.log(f"DevVerify: {report.message}")
                return run

        report.success = False
        report.message = f"编译仍未通过（{len(report.errors)} 个错误）"
        run.build_report = report
        self.store.save_json(run, "05_build_report.json", report.model_dump())
        run.status = "failed"
        run.log(f"DevVerify: {report.message}")
        return run

    def _request_fix(
        self,
        run: PipelineRun,
        project_root,
        errors: list[str],
        log: str,
    ) -> DevCodeFixOutput:
        system = (
            "你是 iOS 编译错误修复专家。根据 xcodebuild 错误日志，输出 DevCodeFixOutput JSON，"
            "仅包含需要修改的 Swift 文件的完整内容（relative_path 相对 project/）。\n"
            f"{IOS_PRODUCTION_CODING_RULES}"
        )
        user = (
            f"编译错误:\n{json.dumps(errors[:30], ensure_ascii=False, indent=2)}\n\n"
            f"日志片段:\n{log[-6000:]}\n\n"
            f"PRD 产品: {run.prd.product_name if run.prd else ''}\n"
            f"开发计划:\n{json.dumps(run.dev_plan.model_dump(), ensure_ascii=False, indent=2) if run.dev_plan else '{}'}"
        )
        return self.llm.chat_json(system, user, DevCodeFixOutput)

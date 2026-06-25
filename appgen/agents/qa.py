from __future__ import annotations

import json
from pathlib import Path

from appgen.agents.base import BaseAgent
from appgen.models import PipelineRun, PipelineStage, TestPlan
from appgen.tools.ios_project import render_test_stub, run_xcode_build, sanitize_product_name


class QAAgent(BaseAgent):
    """编译通过后的测试计划与 XCTest 生成。"""

    stage = PipelineStage.QA
    name = "QA"
    description = "测试策略、单元测试与发布检查清单"

    async def run(self, run: PipelineRun) -> PipelineRun:
        if not run.prd or not run.dev_plan:
            raise ValueError("QA 需要 PRD 与开发计划")
        if not run.build_report or not run.build_report.success:
            raise ValueError("QA 需要在 DevVerify 编译通过后才能执行")

        build_ctx = ""
        if run.build_report:
            build_ctx = json.dumps(run.build_report.model_dump(), ensure_ascii=False, indent=2)
        manifest_ctx = ""
        if run.dev_code_manifest:
            manifest_ctx = json.dumps(run.dev_code_manifest.model_dump(), ensure_ascii=False, indent=2)

        system = (
            "你是移动端 QA 负责人。DevVerify 已编译通过，请基于 PRD、开发计划、编码清单输出 TestPlan JSON。\n"
            "要求：\n"
            "- unit_tests 须对应真实模块（ViewModel、Service）\n"
            "- manual_checklist 覆盖 PRD mvp_features 与 Design 屏幕\n"
            "- release_criteria 含编译通过、核心流程、无崩溃、隐私合规\n"
            "- 禁止仅写「手动测试通过」等空泛项"
        )
        user = (
            f"PRD:\n{json.dumps(run.prd.model_dump(), ensure_ascii=False, indent=2)}\n\n"
            f"开发计划:\n{json.dumps(run.dev_plan.model_dump(), ensure_ascii=False, indent=2)}\n\n"
            f"编码清单:\n{manifest_ctx}\n\n"
            f"编译报告:\n{build_ctx}"
        )

        plan = await self.llm_chat_json(system, user, TestPlan)
        run.test_plan = plan
        self.store.save_json(run, "06_test_plan.json", plan.model_dump())

        self._ensure_unit_tests(run)

        checklist_md = "# 测试与发布检查清单\n\n"
        if run.build_report:
            checklist_md += f"## 编译状态\n- [{'x' if run.build_report.success else ' '}] {run.build_report.message}\n\n"
        checklist_md += f"## 策略\n{plan.test_strategy}\n\n"
        checklist_md += "## 单元测试\n" + "\n".join(f"- {item}" for item in plan.unit_tests) + "\n\n"
        checklist_md += "## 手动冒烟\n" + "\n".join(f"- [ ] {item}" for item in plan.manual_checklist)
        checklist_md += "\n\n## 发布标准\n" + "\n".join(f"- {item}" for item in plan.release_criteria)
        self.store.save_text(run, "06_test_plan.md", checklist_md)

        run.log("QA: 测试计划已生成（编译已通过前置检查）")
        return run

    def _ensure_unit_tests(self, run: PipelineRun) -> None:
        project_root = self.store.run_dir(run.id) / "project"
        if not project_root.exists() or not run.prd:
            return
        product = sanitize_product_name(run.prd.product_name)
        tests_dir = project_root / f"{product}Tests"
        test_file = tests_dir / f"{product}Tests.swift"
        if not test_file.exists():
            tests_dir.mkdir(parents=True, exist_ok=True)
            test_file.write_text(render_test_stub(product), encoding="utf-8")

        scheme = run.dev_plan.scheme_name if run.dev_plan else product
        test_build = run_xcode_build(
            project_root,
            scheme,
            destination="generic/platform=iOS Simulator",
        )
        if test_build.success:
            run.log("QA: xcodebuild test 构建检查通过")
        elif test_build.skipped:
            run.log("QA: 跳过 xcodebuild test（无 Xcode 环境）")

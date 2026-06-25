# AppGen Agent 协作规范

本仓库实现 **AppGen** — 从 App Store 商机发现到上架物料生成的多智能体流水线。

## Agent 角色

| 代号 | 模块 | Playbook |
|------|------|----------|
| Scout | `appgen/agents/scout.py` | 从榜单/搜索发现机会，输出 `OpportunityBrief` |
| Analyst | `appgen/agents/analyst.py` | 拆解用户故事与 MVP 边界 |
| PM | `appgen/agents/pm.py` | 按 `templates/prd.md.j2` 生成 PRD |
| Designer | `appgen/agents/designer.py` | 输出页面级 UI/交互/文案规格 |
| DevInit | `appgen/agents/dev_init.py` | 输出工程计划（技术栈、模块、Bundle ID） |
| DevScaffold | `appgen/agents/dev_scaffold.py` | XcodeGen 工程 + Theme/Router 骨架 |
| DevCode | `appgen/agents/dev_code.py` | 按 PRD/设计分批生成功能 Swift 代码 |
| DevVerify | `appgen/agents/dev_verify.py` | xcodebuild 编译验证与错误修复 |
| QA | `appgen/agents/qa.py` | 编译通过后的测试与发布检查清单 |
| Store | `appgen/agents/store.py` | ASO metadata + 隐私协议 + fastlane 目录 |

## 人机 Review 节点

每个 Agent 执行完毕后触发 `ReviewManager`（`appgen/review.py`）：

- `cli`：终端交互确认（默认）
- `auto`：自动通过（开发/CI）
- `web`：Dashboard 暂停等待批准

Review 未通过时流水线 `paused`，可修改产物后 `appgen resume <run_id>`。

## 扩展新 Agent

1. 在 `appgen/models/` 定义输出 Pydantic 模型
2. 继承 `BaseAgent`，实现 `run()`
3. 注册到 `PipelineOrchestrator.STAGE_ORDER` 与 `_agents`
4. 在 `review.py` 的 `_stage_summary` 添加摘要
5. 如需文档输出，在 `appgen/templates/` 添加 Jinja2 模板

## 命令

```bash
appgen run --keyword "..."     # 启动流水线
appgen serve                   # Web Dashboard
pytest                         # 测试
```

## 约定

- 产物统一写入 `workspace/runs/<run_id>/`
- LLM 调用使用 OpenAI 兼容接口（`appgen/llm.py`）
- 无 API Key 时走 Mock，保证可离线测试（DevVerify 跳过真实编译）
- iOS 工程依赖 **XcodeGen**（`brew install xcodegen`）与 **Xcode**（DevVerify 真实编译）
- DevCode 须遵守 MVVM、AppTheme、无 force unwrap 等生产规范（见 `dev_code.py`）
- QA 仅在 `build_report.success == true` 时执行
- Web 顶栏「一键通过」开关对应 `run.metadata.auto_review`；CLI 等效 `--auto`

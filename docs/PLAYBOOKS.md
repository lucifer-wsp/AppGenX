# AppGen Playbooks

各 Agent 的执行策略与质量门槛。

## Scout — 商机挖掘

**输入**: 关键词 或 App Store 榜单类型  
**工具**: `AppStoreClient`（RSS 榜单 + iTunes Search/Lookup）、`web_search`  
**策略**:
- 优先识别评论/描述中的高频痛点
- 避开巨头碾压领域（社交、通用 IM）
- 置信度 < 50 建议在 Review 阶段驳回

**输出**: `OpportunityBrief`

## Analyst — 需求拆解

**输入**: `OpportunityBrief`  
**策略**:
- MVP 功能 ≤ 5 项
- 明确 NOT-DO 清单
- 每条用户故事可测试

**输出**: `RequirementSpec`

## PM — PRD 撰写

**输入**: 商机 + 需求规格 + 竞品搜索  
**模板**: `templates/prd.md.j2`  
**必含章节**: 背景、用户、功能、付费三档、迭代路线、风险

**输出**: `PRDDocument` + `03_prd.md`

## Designer — 设计规格

**输入**: PRD  
**策略**:
- 单屏主操作不超过 1 个
- 文案简短、可本地化
- 色板 ≤ 5 色

**输出**: `DesignSpec` + `04_design.md`

## DevInit — 项目初始化

**输入**: PRD + Design  
**默认栈**: SwiftUI + 模块化目录  
**输出**: `project/` 脚手架 + `05_dev_plan.json`

## QA — 测试计划

**输入**: PRD + DevPlan  
**输出**: 单元/集成/手动清单 + 发布标准

## Store — 上架物料

**输入**: PRD + Design  
**语言**: 至少 zh-Hans + en-US  
**输出**:
- `07_store_listing.md`
- `07_privacy_policy.html`
- `fastlane/metadata/<locale>/*.txt`

## Review 质量门槛

| 阶段 | 通过条件 |
|------|----------|
| Scout | 差异化清晰、置信度 ≥ 60 |
| Analyst | MVP 可 2 周内实现 |
| PM | 付费模式与功能一致 |
| Designer | 核心流程有完整页面 |
| DevInit | 技术栈与团队能力匹配 |
| QA | 发布清单可执行 |
| Store | 文案无夸大、隐私描述准确 |

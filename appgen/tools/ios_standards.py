"""iOS 生产环境编码、设计与交互规范（Agent prompt 共用）。"""

IOS_PRODUCTION_CODING_RULES = """
生产环境 iOS 编码规范（必须全部遵守）：

【多语言 — 简体 / 繁体 / 英文】
1. 所有用户可见文案必须通过 L10n 访问，禁止 Text("硬编码中文/英文")、navigationTitle("…") 等魔法字符串
2. 使用 L10n.Screen.{ScreenName}.xxx 或 L10n.Common.xxx；新增文案须同步写入三语 Localizable.strings（en / zh-Hans / zh-Hant）
3. 桌面显示名由 InfoPlist.strings 三语配置，代码中读取 AppConstants 仅作非 UI 用途
4. accessibilityLabel / accessibilityHint 同样走 L10n，支持 VoiceOver 多语言

【设计令牌 — 禁止魔法字符串与魔法数字】
5. 颜色仅使用 AppTheme.Colors.*；字体仅使用 AppTheme.Typography.*
6. 间距、圆角、尺寸、线宽仅使用 AppTheme.Metrics.*；动画时长仅使用 AppTheme.Animation.*
7. 交互常量（最小点击区域 44pt、防抖间隔等）仅使用 AppTheme.Interaction.*
8. 业务配置数值（冷却秒数、阈值等）放在 AppConstants 或 Domain 层命名常量，禁止 View 内裸数字
9. 路由、UserDefaults key、通知 identifier 等字符串常量集中在 AppConstants 或对应 Service，禁止散落字面量

【架构与 Swift 规范】
10. SwiftUI + MVVM：每屏 View + ViewModel（@Observable），业务逻辑不进 View
11. 禁止 force unwrap（!）；使用 guard let / if let / ?? 安全处理
12. 严格遵循 DesignSpec 的 ui_elements、interactions、ui_copy（三语版本）、navigation
13. 实现 PRD mvp_features 的可运行逻辑（可 mock 外部 API，但结构须完整）
14. 单文件职责清晰；Services 层处理持久化/网络/系统 API
15. 错误态 / 空态 / 加载态必须处理；禁止 placeholder Text("TODO") 作为最终 UI
16. 代码须能通过 Swift 编译器 strict 检查；遵循 Apple HIG 与 Dynamic Type 基本适配

【交互规范】
17. 可点击控件最小 hit target 44×44pt（AppTheme.Interaction.minimumTapTarget）
18. 主操作使用 DesignSystem/Components 中 PrimaryButton 等复用组件
19. 导航遵循 DesignSpec.navigation；返回与 modal 行为符合 iOS 平台惯例
20. 关键操作提供触觉反馈（HapticFeedbackService）与明确视觉反馈
"""

IOS_DESIGNER_RULES = """
设计规范补充（DesignSpec 输出须满足）：
1. color_palette 键名使用语义化 snake_case（如 primary、background、text_primary），DevScaffold 会生成 AppTheme.Colors
2. typography 键名对应 AppTheme.Typography（title、body、caption 等）
3. 每个 screen 的 ui_copy 必须为每个文案键提供三语版本，命名约定：
   - {key}_en（英文）
   - {key}_zh_hans（简体中文）
   - {key}_zh_hant（繁体中文）
   例如 cta_en / cta_zh_hans / cta_zh_hant
4. interactions 须描述点击、滑动、弹窗、空态/错误态反馈，便于 DevCode 落地
5. ui_elements 须可映射到 SwiftUI 组件与 AppTheme 令牌
"""

IOS_DEV_SCAFFOLD_NOTE = (
    "工程已含 en / zh-Hans / zh-Hant 本地化、AppTheme 设计令牌、L10n 访问层；"
    "DevCode 须在此基础上扩展，不得绕过上述结构。"
)

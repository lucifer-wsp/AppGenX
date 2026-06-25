from __future__ import annotations

import asyncio
import os
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from appgen.cli_runs import review_app, show_run
from appgen.config import settings
from appgen.discovery import MarketScanner
from appgen.pipeline import PipelineOrchestrator
from appgen.scan_flow import normalize_scan_limit
from appgen.tools.genres import APP_GENRES, CHART_LABELS, CHART_TYPES
from appgen.tools.regions import (
    DEFAULT_REGION_PRESET,
    REGION_PRESETS,
    format_regions,
    region_label,
    resolve_region_codes,
)

app = typer.Typer(
    name="appgen",
    help="AppGen Agent — 从 App Store 需求挖掘到上架的全链路多智能体系统",
    no_args_is_help=True,
)
scan_app = typer.Typer(help="全分类市场扫描与机会筛选")
app.add_typer(scan_app, name="scan")
app.add_typer(review_app, name="review")
console = Console()


def _orch() -> PipelineOrchestrator:
    return PipelineOrchestrator()


@app.command("run")
def run_pipeline(
    keyword: Optional[str] = typer.Option(None, "--keyword", "-k", help="App Store 搜索关键词"),
    category: Optional[str] = typer.Option(
        None,
        "--category",
        "-c",
        help="榜单类型，如 top-free / top-paid / top-grossing",
    ),
    country: str = typer.Option("us", "--country", help="App Store 国家/地区代码（如 us, gb, de）"),
    auto: bool = typer.Option(False, "--auto", help="跳过人工 Review（一键通过所有节点）"),
) -> None:
    """启动一次完整 AppGen 流水线。"""
    if not keyword and not category:
        category = "top-free"
        console.print("[yellow]未指定关键词，将分析免费榜 Top 应用[/yellow]")

    orchestrator = _orch()
    run = orchestrator.create_run(
        keyword=keyword, category=category, country=country, auto_review=auto
    )

    console.print(f"[green]已创建运行[/green] id={run.id}")

    def on_complete(r, stage):
        console.print(f"  ✓ 阶段完成: {stage.value}")

    final = asyncio.run(
        orchestrator.run_until_pause(run, on_stage_complete=on_complete)
    )

    console.print(f"\n[bold]状态:[/bold] {final.status}")
    console.print(f"[bold]产物目录:[/bold] {settings.appgen_workspace / 'runs' / final.id}")


@app.command("resume")
def resume_pipeline(
    run_id: str = typer.Argument(..., help="运行 ID"),
    auto: bool = typer.Option(False, "--auto", help="开启一键通过并继续执行"),
) -> None:
    """恢复已暂停或失败的流水线。"""
    orchestrator = _orch()
    if auto:
        final = asyncio.run(orchestrator.set_auto_review(run_id, True))
    else:
        final = asyncio.run(orchestrator.resume(run_id))
    console.print(f"运行 {run_id} 状态: {final.status}")


@app.command("status")
def show_status(run_id: str = typer.Argument(..., help="运行 ID")) -> None:
    """查看单次运行状态、阶段进度与 Review。"""
    show_run(run_id)


@app.command("show")
def show_artifact(
    run_id: str = typer.Argument(..., help="运行 ID"),
    section: Optional[str] = typer.Argument(
        None,
        help="板块: opportunity / requirements / prd / design / dev / dev_scaffold / dev_code / dev_verify / test / store / progress / reviews",
    ),
) -> None:
    """查看 PRD、设计稿、开发/测试进度等产物。"""
    show_run(run_id, section)


@app.command("list")
def list_runs() -> None:
    """列出所有历史运行。"""
    orchestrator = _orch()
    runs = orchestrator.list_runs()
    if not runs:
        console.print("暂无运行记录")
        return

    table = Table(title="AppGen Runs")
    table.add_column("ID")
    table.add_column("状态")
    table.add_column("阶段")
    table.add_column("关键词")
    table.add_column("产品")
    for run in runs:
        table.add_row(
            run.id,
            run.status,
            run.current_stage.value,
            run.seed_keyword or run.seed_category or "-",
            run.prd.product_name if run.prd else "-",
        )
    console.print(table)


@app.command("doctor")
def doctor() -> None:
    """检查当前环境与 LLM 配置（以 workspace/settings.json 为唯一配置源）。"""
    from appgen.config import Settings
    from appgen.llm import build_provider_chain, resolve_provider
    from appgen.llm_cursor import _resolve_agent_bin, cursor_available_with
    from appgen.runtime_settings import (
        LLMProviderConfig,
        _mask_secret,
        _provider_entry_usable,
        default_llm_providers_from_env,
        runtime_settings,
    )

    rc = runtime_settings.get()
    settings_path = runtime_settings.settings_path()
    chain = build_provider_chain()

    table = Table(title="AppGen 环境检查")
    table.add_column("项")
    table.add_column("状态")
    table.add_row("配置来源", str(settings_path) if settings_path else "内存默认")
    table.add_row("LLM 模式", rc.llm_provider_mode or "auto")

    cursor_entry = next((p for p in rc.llm_providers if p.provider == "cursor"), None)
    openai_entry = next((p for p in rc.llm_providers if p.provider == "openai"), None)

    def _provider_status(entry: LLMProviderConfig | None) -> str:
        if not entry or not (entry.api_key or "").strip():
            return "未配置"
        preview = _mask_secret(entry.api_key)["preview"]
        if not _provider_entry_usable(entry):
            return f"无效/测试 Key ({preview})"
        return f"已配置 ({preview})"

    table.add_row("Cursor Provider", _provider_status(cursor_entry))
    table.add_row("Cursor CLI (agent)", "已安装" if _resolve_agent_bin() else "未安装")
    if cursor_entry and _provider_entry_usable(cursor_entry):
        table.add_row(
            "Cursor 可用",
            "是" if cursor_available_with(cursor_entry.api_key) else "否（检查 CLI / Key）",
        )
    table.add_row("OpenAI Provider", _provider_status(openai_entry))

    if chain:
        chain_desc = " → ".join(f"{e.provider}({e.model or 'default'})" for e in chain)
        table.add_row("Provider 链", chain_desc)
    else:
        table.add_row("Provider 链", "空（Mock 或 Key 无效）")

    try:
        provider = resolve_provider()
        table.add_row("实际使用", provider)
    except RuntimeError as exc:
        table.add_row("实际使用", f"错误: {exc}")

    table.add_row("默认区域", rc.default_region_preset)
    table.add_row("Review 模式", rc.review_mode)
    console.print(table)

    env_cfg = Settings()
    env_chain = default_llm_providers_from_env(
        cursor_api_key=env_cfg.cursor_api_key,
        cursor_model=env_cfg.cursor_model,
        openai_api_key=env_cfg.llm_api_key,
        openai_base_url=env_cfg.llm_base_url,
        openai_model=env_cfg.llm_model,
    )
    env_cursor = next((p for p in env_chain if p.provider == "cursor"), None)
    env_openai = next((p for p in env_chain if p.provider == "openai"), None)
    env_has_extra = False
    if env_cursor and _provider_entry_usable(env_cursor):
        if not cursor_entry or env_cursor.api_key != cursor_entry.api_key:
            env_has_extra = True
    if env_openai and _provider_entry_usable(env_openai):
        if not openai_entry or env_openai.api_key != openai_entry.api_key:
            env_has_extra = True
    if env_has_extra and settings_path and settings_path.is_file():
        console.print(
            "\n[yellow]提示：[/yellow].env 中的 LLM Key 与 "
            f"[cyan]{settings_path}[/cyan] 不一致。"
            "\n运行时仅使用 settings.json；请在 Web 设置页修改并保存，或删除 settings.json 后重启以从 .env 重新生成。"
        )

    if not _resolve_agent_bin():
        console.print(
            "\n[yellow]提示：[/yellow] 安装 Cursor CLI：\n"
            "  curl -fsSL https://cursor.com/install | bash\n"
            "  export PATH=\"$HOME/.local/bin:$PATH\""
        )

    try:
        if resolve_provider() == "mock":
            console.print(
                "\n[yellow]当前为 Mock 模式（零费用）。[/yellow]\n"
                "调试建议：\n"
                "  1. 只拉数据: appgen scan run --no-analyze\n"
                "  2. 在 Web 设置页配置 Cursor / OpenAI Provider 链\n"
                "  3. 强制 Mock: 设置页模式选 Mock"
            )
    except RuntimeError:
        pass


@app.command("serve")
def serve_web(
    host: str = typer.Option(None, "--host"),
    port: int = typer.Option(None, "--port"),
) -> None:
    """启动 Web Dashboard（Review 与进度查看）。"""
    import uvicorn

    uvicorn.run(
        "appgen.web.app:app",
        host=host or settings.appgen_host,
        port=port or settings.appgen_port,
        reload=False,
    )


@scan_app.command("run")
def scan_market(
    regions: Optional[str] = typer.Option(
        None,
        "--regions",
        "-r",
        help=f"区域预设: {', '.join(REGION_PRESETS)}（默认读取 APPGEN_DEFAULT_REGIONS）",
    ),
    countries: Optional[str] = typer.Option(
        None,
        "--countries",
        help="显式指定国家代码，逗号分隔，如 us,gb,de（不可含 cn）",
    ),
    charts: str = typer.Option(
        "top-free",
        "--charts",
        help="榜单，逗号分隔：top-free,top-paid,top-grossing",
    ),
    limit: int = typer.Option(15, "--limit", help="每个分类拉取的应用数量（1–100）"),
    enrich: int = typer.Option(5, "--enrich", help="每个分类补充详情的 Top N 应用"),
    genre_ids: Optional[str] = typer.Option(
        None,
        "--genres",
        help="仅扫描指定分类 ID，逗号分隔，如 6013,6007",
    ),
    no_analyze: bool = typer.Option(False, "--no-analyze", help="只采集数据，不做机会分析"),
) -> None:
    """扫描 App Store 各分类榜单（美区 + 欧洲），汇总需求机会。"""
    preset = regions or settings.appgen_default_regions or DEFAULT_REGION_PRESET
    try:
        country_codes = resolve_region_codes(preset=preset if not countries else None, countries=countries)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    chart_types = [c.strip() for c in charts.split(",") if c.strip()]
    try:
        limit = normalize_scan_limit(limit)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    scanner = MarketScanner()
    scan = scanner.create_scan(
        countries=country_codes,
        region_preset=preset,
        chart_types=chart_types,
        per_genre_limit=limit,
        enrich_top_n=enrich,
    )

    genres = None
    if genre_ids:
        ids = {int(x.strip()) for x in genre_ids.split(",") if x.strip()}
        genres = [g for g in APP_GENRES if g.id in ids]
        if not genres:
            raise typer.BadParameter(f"未找到有效分类 ID: {genre_ids}")

    genre_count = len(genres or APP_GENRES)
    total = len(country_codes) * genre_count * len(chart_types)
    console.print(
        Panel(
            f"扫描 ID: [bold]{scan.id}[/bold]\n"
            f"区域: {format_regions(country_codes)}\n"
            f"请求数: {len(country_codes)} 区域 × {genre_count} 分类 × {len(chart_types)} 榜单 = {total}\n"
            f"预计耗时: {max(2, total // 4)}–{max(5, total // 2)} 分钟",
            title="开始市场扫描（美区 + 欧洲）",
            border_style="green",
        )
    )

    with console.status("[bold green]正在扫描 App Store…"):
        final = asyncio.run(
            scanner.run_scan(scan, genres=genres, skip_analyze=no_analyze)
        )

    if final.status == "failed":
        console.print(f"[red]扫描失败:[/red] {final.error}")
        raise typer.Exit(code=1)

    out = settings.appgen_workspace / "scans" / final.id
    console.print(f"\n[green]扫描完成[/green]")
    console.print(f"产物目录: {out}")
    console.print(f"报告: {out / 'scan_report.md'}")
    if final.opportunities:
        console.print(f"\n运行 [bold]appgen scan show {final.id}[/bold] 查看机会列表")


@scan_app.command("list")
def list_scans() -> None:
    """列出历史市场扫描。"""
    scans = MarketScanner().list_scans()
    if not scans:
        console.print("暂无扫描记录，先运行: appgen scan run")
        return

    table = Table(title="市场扫描记录")
    table.add_column("ID")
    table.add_column("状态")
    table.add_column("区域")
    table.add_column("分类快照")
    table.add_column("机会数")
    for scan in scans:
        table.add_row(
            scan.id,
            scan.status,
            format_regions(scan.countries),
            str(len(scan.categories)),
            str(len(scan.opportunities)),
        )
    console.print(table)


@scan_app.command("show")
def show_scan(
    scan_id: str = typer.Argument(..., help="扫描 ID"),
    top: int = typer.Option(15, "--top", help="显示前 N 条机会"),
) -> None:
    """查看扫描机会列表，辅助选定方向。"""
    scan = MarketScanner().get_scan(scan_id)
    if not scan.opportunities:
        console.print("[yellow]该扫描暂无机会分析，可重新运行或检查 scan_report.md[/yellow]")
        return

    table = Table(title=f"扫描 {scan_id} — 推荐机会")
    table.add_column("#", justify="right")
    table.add_column("分数", justify="right")
    table.add_column("方向")
    table.add_column("区域")
    table.add_column("分类")
    table.add_column("关键词")

    for opp in scan.opportunities[:top]:
        table.add_row(
            str(opp.rank),
            str(opp.confidence_score),
            opp.title,
            f"{opp.country_label} · {opp.genre_zh}/{CHART_LABELS.get(opp.chart_type, opp.chart_type)}",
            opp.suggested_keyword,
        )
    console.print(table)
    console.print(f"\n详情: {settings.appgen_workspace / 'scans' / scan_id / 'scan_report.md'}")
    console.print(f"选定后: [bold]appgen scan pick {scan_id} <序号>[/bold]")


@scan_app.command("pick")
def pick_opportunity(
    scan_id: str = typer.Argument(..., help="扫描 ID"),
    index: int = typer.Argument(..., help="机会序号（scan show 中的 # 列）"),
    auto: bool = typer.Option(False, "--auto", help="跳过人工 Review（一键通过所有节点）"),
) -> None:
    """从扫描结果中选定一个方向，启动完整 AppGen 流水线。"""
    scan = MarketScanner().get_scan(scan_id)
    if not scan.opportunities:
        console.print("[red]该扫描没有可挑选的机会[/red]")
        raise typer.Exit(code=1)

    opp = next((o for o in scan.opportunities if o.rank == index), None)
    if opp is None:
        console.print(f"[red]未找到序号 {index}，请运行 appgen scan show {scan_id}[/red]")
        raise typer.Exit(code=1)

    console.print(
        Panel(
            f"[bold]{opp.title}[/bold]（{opp.confidence_score} 分）\n"
            f"{opp.one_liner}\n\n"
            f"区域: {opp.country_label}\n"
            f"分类: {opp.genre_zh}\n"
            f"差异化: {opp.differentiation}\n"
            f"关键词: {opp.suggested_keyword}",
            title=f"已选定机会 #{index}",
            border_style="cyan",
        )
    )

    keyword = opp.suggested_keyword or opp.title
    orchestrator = _orch()
    run = orchestrator.create_run(
        keyword=keyword,
        category=opp.chart_type,
        country=opp.country,
        auto_review=auto,
    )
    run.metadata["picked_from_scan"] = scan_id
    run.metadata["picked_opportunity"] = opp.model_dump()
    orchestrator.store.save_run(run)

    console.print(f"\n[green]已创建流水线[/green] id={run.id}")

    def on_complete(r, stage):
        console.print(f"  ✓ {stage.value}")

    try:
        final = asyncio.run(orchestrator.run_until_pause(run, on_stage_complete=on_complete))
    except Exception as exc:
        run.status = "failed"
        run.log(f"Pipeline 失败: {exc}")
        orchestrator.store.save_run(run)
        console.print(f"[red]流水线失败:[/red] {exc}")
        console.print(f"修复后可重试: [bold]appgen resume {run.id}[/bold]")
        raise typer.Exit(code=1) from exc

    console.print(f"\n状态: {final.status}")
    console.print(f"产物: {settings.appgen_workspace / 'runs' / final.id}")


if __name__ == "__main__":
    app()

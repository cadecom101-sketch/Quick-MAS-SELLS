#!/usr/bin/env python3
"""Quick-MAS-SELLS — CLI entry point.

Usage:
  python main.py serve          # Start FastAPI server (default port 8000)
  python main.py run-cycle      # Execute one full MAS pipeline cycle
  python main.py loop           # Run continuous loop (1 cycle/hour)
  python main.py status         # Show pipeline state summary
  python main.py approve <id>   # HITL-approve a pipeline by ID
"""
from __future__ import annotations

import asyncio
import sys
from typing import Optional

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from config.settings import get_settings
from mas.orchestrator import Orchestrator
from mas.state.store import init_store
from mas.telemetry.logger import configure_logging

app_cli = typer.Typer(help="Quick-MAS-SELLS — Adaptive Multi-Agent Dropshipping System")
console = Console()


async def _get_orchestrator() -> Orchestrator:
    cfg = get_settings()
    store = await init_store(cfg.database_url.replace("sqlite+aiosqlite:///", ""))
    return Orchestrator(store)


@app_cli.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Bind host"),
    port: int = typer.Option(8000, help="Port"),
    reload: bool = typer.Option(False, help="Auto-reload on code changes"),
):
    """Start the FastAPI REST server."""
    configure_logging()
    console.print(f"[bold green]Starting Quick-MAS-SELLS API on {host}:{port}[/]")
    uvicorn.run(
        "api.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


@app_cli.command(name="run-cycle")
def run_cycle():
    """Execute one full pipeline cycle (discover → validate → content → deploy → monitor)."""
    configure_logging()

    async def _run():
        orch = await _get_orchestrator()
        console.print("[bold cyan]Running pipeline cycle...[/]")
        summary = await orch.run_cycle()
        console.print_json(data=summary)

    asyncio.run(_run())


@app_cli.command()
def loop(
    interval: int = typer.Option(3600, help="Seconds between cycles"),
    max_cycles: Optional[int] = typer.Option(None, help="Stop after N cycles"),
):
    """Run the orchestrator in continuous loop mode."""
    configure_logging()

    async def _run():
        orch = await _get_orchestrator()
        await orch.run_loop(interval_seconds=interval, max_cycles=max_cycles)

    asyncio.run(_run())


@app_cli.command()
def status():
    """Show current pipeline state summary."""

    async def _run():
        orch = await _get_orchestrator()
        from mas.state.models import PipelineState
        all_pipelines = await orch.store.list_pipelines(limit=1000)

        table = Table(title="Quick-MAS-SELLS — Pipeline Status", show_lines=True)
        table.add_column("ID", style="dim", width=12)
        table.add_column("State", style="bold")
        table.add_column("Title", max_width=35)
        table.add_column("Price", justify="right")
        table.add_column("ROAS", justify="right")
        table.add_column("Source")
        table.add_column("Updated")

        state_colours = {
            "DISCOVERED": "white",
            "SUPPLIER_VALIDATED": "cyan",
            "CONTENT_GENERATED": "blue",
            "AWAITING_APPROVAL": "yellow",
            "CAMPAIGN_LIVE": "green",
            "MONITORING": "green",
            "SCALED": "bold green",
            "KILLED": "red",
            "FAILED": "bold red",
        }

        for p in all_pipelines:
            colour = state_colours.get(p.state.value, "white")
            roas_str = (
                f"{p.latest_metrics.roas:.2f}x" if p.latest_metrics else "—"
            )
            table.add_row(
                p.id[:8] + "…",
                f"[{colour}]{p.state.value}[/]",
                p.discovered_product.title[:35] if p.discovered_product else "—",
                f"${p.supplier.price_usd:.2f}" if p.supplier else "—",
                roas_str,
                p.discovered_product.source.value if p.discovered_product else "—",
                p.updated_at.strftime("%m-%d %H:%M"),
            )

        console.print(table)
        console.print(f"\nTotal: {len(all_pipelines)} pipelines")
        console.print("Health:", orch.health_report())

    asyncio.run(_run())


@app_cli.command()
def approve(pipeline_id: str = typer.Argument(..., help="Pipeline ID to approve")):
    """HITL: Approve a campaign awaiting human review and deploy it."""

    async def _run():
        orch = await _get_orchestrator()
        result = await orch.approve_pipeline(pipeline_id)
        console.print(f"[green]Approved![/] Pipeline {pipeline_id} → state: {result['state']}")

    asyncio.run(_run())


@app_cli.command()
def digest():
    """Email the daily P&L digest to the admin (wire this to a daily cron)."""
    configure_logging()

    async def _run():
        orch = await _get_orchestrator()
        stats = await orch.build_dashboard_stats()
        from mas.tools.email_alerts import send_daily_digest
        await send_daily_digest(stats)
        console.print(f"[green]Digest sent.[/] Net profit: ${stats.get('net_profit_usd', 0):.2f}")

    asyncio.run(_run())


if __name__ == "__main__":
    app_cli()

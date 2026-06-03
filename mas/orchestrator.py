"""MAS Orchestrator — coordinates all agents in a deterministic execution loop.

Execution order per cycle:
  0. GuardrailAgent         — spend cap + early kill (ALWAYS runs first)
  1. TrendSpotterAgent      — discover new products
  2. SupplierIntelAgent     — validate on AliExpress
  3. ContentForgeAgent      — generate landing page + ads
  4. CampaignDeployAgent    — create + activate Meta & TikTok campaigns
  5. PerformanceMonitorAgent — track ROI, auto-scale/kill

Fail-closed: if any agent becomes unhealthy (3 consecutive failures), the
orchestrator skips that agent for the current cycle and emails an alert.
All state transitions are idempotent — re-running a cycle is safe.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from mas.agents.campaign_deploy import CampaignDeployAgent
from mas.agents.content_forge import ContentForgeAgent
from mas.agents.guardrail import GuardrailAgent
from mas.agents.performance_monitor import PerformanceMonitorAgent
from mas.agents.supplier_intel import SupplierIntelAgent
from mas.agents.trend_spotter import TrendSpotterAgent
from mas.state.store import StateStore
from mas.telemetry.logger import get_logger

logger = get_logger("Orchestrator")


class Orchestrator:
    def __init__(self, store: StateStore) -> None:
        self.store = store
        self.guardrail = GuardrailAgent(store)
        self.trend_spotter = TrendSpotterAgent(store)
        self.supplier_intel = SupplierIntelAgent(store)
        self.content_forge = ContentForgeAgent(store)
        self.campaign_deploy = CampaignDeployAgent(store)
        self.performance_monitor = PerformanceMonitorAgent(store)
        self._cycle_count = 0

    @property
    def agents(self):
        return [
            self.guardrail,
            self.trend_spotter,
            self.supplier_intel,
            self.content_forge,
            self.campaign_deploy,
            self.performance_monitor,
        ]

    def health_report(self) -> dict:
        return {
            agent.name: {
                "healthy": agent.healthy,
                "consecutive_failures": agent._consecutive_failures,
            }
            for agent in self.agents
        }

    async def run_cycle(self) -> dict:
        """Execute one full pipeline cycle. Returns cycle summary."""
        self._cycle_count += 1
        cycle_id = self._cycle_count
        started_at = datetime.utcnow()

        logger.info("orchestrator_cycle_start", cycle=cycle_id)
        summary = {"cycle": cycle_id, "steps": {}}

        # ── Step 0: Guardrails (always runs — fail-closed) ──────────────────────
        try:
            guardrail_result = await self.guardrail.run()
            summary["steps"]["guardrail"] = guardrail_result
            if guardrail_result.get("daily_cap", {}).get("breached"):
                logger.error("orchestrator_daily_cap_breached")
        except Exception as exc:
            logger.error("orchestrator_guardrail_failed", error=str(exc))
            summary["steps"]["guardrail"] = {"error": str(exc), "deployment_blocked": True}

        # ── Step 1: Discover ────────────────────────────────────────────────────
        if self.trend_spotter.healthy:
            try:
                new_ids = await self.trend_spotter.run()
                summary["steps"]["trend_spotter"] = {"new_products": len(new_ids), "ids": new_ids}
            except Exception as exc:
                logger.error("orchestrator_step_failed", step="trend_spotter", error=str(exc))
                summary["steps"]["trend_spotter"] = {"error": str(exc)}
        else:
            summary["steps"]["trend_spotter"] = {"skipped": "agent_unhealthy"}

        # ── Step 2: Validate Supplier ───────────────────────────────────────────
        if self.supplier_intel.healthy:
            try:
                validated = await self.supplier_intel.process_queue()
                summary["steps"]["supplier_intel"] = {"validated": len(validated)}
            except Exception as exc:
                logger.error("orchestrator_step_failed", step="supplier_intel", error=str(exc))
                summary["steps"]["supplier_intel"] = {"error": str(exc)}
        else:
            summary["steps"]["supplier_intel"] = {"skipped": "agent_unhealthy"}

        # ── Step 3: Generate Content ────────────────────────────────────────────
        if self.content_forge.healthy:
            try:
                generated = await self.content_forge.process_queue()
                summary["steps"]["content_forge"] = {"generated": len(generated)}
            except Exception as exc:
                logger.error("orchestrator_step_failed", step="content_forge", error=str(exc))
                summary["steps"]["content_forge"] = {"error": str(exc)}
        else:
            summary["steps"]["content_forge"] = {"skipped": "agent_unhealthy"}

        # ── Step 4: Deploy Campaigns ────────────────────────────────────────────
        if self.campaign_deploy.healthy:
            try:
                deployed = await self.campaign_deploy.process_queue()
                summary["steps"]["campaign_deploy"] = {"deployed": len(deployed)}
            except Exception as exc:
                logger.error("orchestrator_step_failed", step="campaign_deploy", error=str(exc))
                summary["steps"]["campaign_deploy"] = {"error": str(exc)}
        else:
            summary["steps"]["campaign_deploy"] = {"skipped": "agent_unhealthy"}

        # ── Step 5: Monitor Performance ─────────────────────────────────────────
        if self.performance_monitor.healthy:
            try:
                monitored = await self.performance_monitor.process_queue()
                summary["steps"]["performance_monitor"] = {"monitored": len(monitored)}
            except Exception as exc:
                logger.error("orchestrator_step_failed", step="performance_monitor", error=str(exc))
                summary["steps"]["performance_monitor"] = {"error": str(exc)}
        else:
            summary["steps"]["performance_monitor"] = {"skipped": "agent_unhealthy"}

        elapsed = (datetime.utcnow() - started_at).total_seconds()
        summary["elapsed_seconds"] = round(elapsed, 2)
        summary["health"] = self.health_report()

        logger.info("orchestrator_cycle_complete", cycle=cycle_id, elapsed=elapsed)
        return summary

    async def run_loop(self, interval_seconds: int = 3600, max_cycles: Optional[int] = None) -> None:
        """Run continuously. interval_seconds = pause between cycles (default: 1 hour)."""
        logger.info("orchestrator_loop_start", interval=interval_seconds)
        cycle = 0
        while True:
            cycle += 1
            await self.run_cycle()
            if max_cycles and cycle >= max_cycles:
                logger.info("orchestrator_max_cycles_reached", cycles=cycle)
                break
            logger.info("orchestrator_sleeping", seconds=interval_seconds)
            await asyncio.sleep(interval_seconds)

    async def approve_pipeline(self, pipeline_id: str) -> dict:
        """Human-in-the-Loop: approve a pipeline waiting at the HITL gate."""
        pipeline = await self.campaign_deploy.approve_and_deploy(pipeline_id)
        return {"pipeline_id": pipeline.id, "state": pipeline.state.value}

    async def build_dashboard_stats(self) -> dict:
        """Aggregate P&L across all pipelines (shared by /analytics/dashboard and digest).

        Uses only the latest metrics snapshot per pipeline — ad-platform insights are
        cumulative-to-date, so summing every snapshot would double-count.
        """
        all_pipelines = await self.store.list_pipelines(limit=10_000)
        by_state: dict = {}
        spend = revenue = cogs = fees = 0.0
        purchases = orders = 0
        performers = []

        for p in all_pipelines:
            by_state[p.state.value] = by_state.get(p.state.value, 0) + 1
            orders += len(p.orders)
            lm = p.latest_metrics
            if lm:
                spend += lm.spend_usd
                revenue += lm.revenue_usd
                cogs += lm.cogs_usd
                fees += lm.stripe_fees_usd
                purchases += lm.purchases
                if lm.roas > 0:
                    performers.append({
                        "title": p.discovered_product.title if p.discovered_product else "?",
                        "state": p.state.value,
                        "roas": lm.roas,
                        "spend": lm.spend_usd,
                        "net_profit": lm.net_profit_usd,
                    })

        performers.sort(key=lambda x: x["roas"], reverse=True)
        return {
            "by_state": by_state,
            "total_spend_usd": round(spend, 2),
            "total_revenue_usd": round(revenue, 2),
            "net_profit_usd": round(revenue - spend - cogs - fees, 2),
            "overall_roas": round(revenue / spend, 2) if spend else 0.0,
            "total_purchases": purchases,
            "total_orders": orders,
            "top_performers": performers[:10],
        }

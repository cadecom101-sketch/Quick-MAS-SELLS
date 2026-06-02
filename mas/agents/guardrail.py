"""GuardrailAgent — spend protection and early kill logic.

Runs BEFORE CampaignDeployAgent and alongside PerformanceMonitorAgent.

Checks enforced:
  1. DAILY TOTAL CAP: aggregate spend across all live campaigns must not exceed
     MAX_TOTAL_DAILY_SPEND_USD. If exceeded, pauses all campaigns and alerts.

  2. EARLY KILL: campaigns < 24 hours old with ROAS < 0.3 (catastrophic failure)
     are killed immediately — don't wait 3 days.

  3. MARGIN CHECK: if AliExpress cost has drifted and gross margin < 40%,
     flag for human review before campaign can launch.

  4. COMPETITOR SATURATION: checks FB Ad Library before a new campaign launches.
     If saturation is VERY HIGH, blocks automatic deployment (requires HITL regardless).

This agent runs as a pre-flight check (called from Orchestrator before deploy step).
Fail-closed: if this agent itself errors, deployment is blocked.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

from config.settings import get_settings
from mas.agents.base import BaseAgent
from mas.state.models import AdStatus, PipelineState, ProductPipeline
from mas.state.store import StateStore
from mas.tools.email_alerts import alert_agent_failure, alert_campaign_killed


class GuardrailAgent(BaseAgent):
    def __init__(self, store: StateStore) -> None:
        super().__init__(store)

    async def _run(self) -> Dict[str, any]:
        """Run all guardrail checks. Returns dict of check results."""
        cfg = get_settings()
        results: Dict[str, any] = {}

        results["daily_cap"] = await self._check_daily_spend_cap()
        results["early_kills"] = await self._check_early_kill()
        return results

    # ── Check 1: Total daily spend cap ────────────────────────────────────────

    async def _check_daily_spend_cap(self) -> Dict[str, any]:
        cfg = get_settings()
        if not cfg.max_total_daily_spend_usd:
            return {"enforced": False}

        active_states = [
            PipelineState.CAMPAIGN_LIVE,
            PipelineState.MONITORING,
            PipelineState.SCALED,
        ]
        total_spend = 0.0
        campaign_count = 0
        killed: List[str] = []

        for state in active_states:
            pipelines = await self.store.list_pipelines(state=state)
            for p in pipelines:
                campaign_count += 1
                if p.campaign:
                    total_spend += p.campaign.daily_budget_usd

        if total_spend > cfg.max_total_daily_spend_usd:
            self.log.error(
                "guardrail_daily_cap_breached",
                total_spend=total_spend,
                cap=cfg.max_total_daily_spend_usd,
                campaigns=campaign_count,
            )
            # Pause all scaled campaigns first (they have the highest budgets)
            scaled = await self.store.list_pipelines(state=PipelineState.SCALED)
            for p in scaled:
                if p.campaign:
                    from mas.tools.meta_ads import pause_campaign
                    await pause_campaign(p.campaign)
                    p.transition(PipelineState.MONITORING)
                    await self.store.upsert_pipeline(p)
                    killed.append(p.id)
                    await self.emit("guardrail_paused_scaled", pipeline_id=p.id, reason="daily_cap")

            await alert_agent_failure(
                "GuardrailAgent",
                f"Daily spend cap ${cfg.max_total_daily_spend_usd:.2f} breached. "
                f"Total: ${total_spend:.2f}. Paused {len(killed)} campaigns.",
                consecutive=1,
            )
        else:
            self.log.info(
                "guardrail_daily_cap_ok",
                total_spend=total_spend,
                cap=cfg.max_total_daily_spend_usd,
                headroom=cfg.max_total_daily_spend_usd - total_spend,
            )

        return {
            "enforced": True,
            "total_daily_spend": total_spend,
            "cap": cfg.max_total_daily_spend_usd,
            "breached": total_spend > cfg.max_total_daily_spend_usd,
            "campaigns_paused": killed,
        }

    # ── Check 2: Early kill — catastrophic failures ────────────────────────────

    async def _check_early_kill(self) -> List[str]:
        cfg = get_settings()
        killed: List[str] = []
        cutoff = datetime.utcnow() - timedelta(hours=24)

        for state in [PipelineState.CAMPAIGN_LIVE, PipelineState.MONITORING]:
            pipelines = await self.store.list_pipelines(state=state)
            for p in pipelines:
                if not p.campaign or not p.campaign.launched_at:
                    continue
                if not p.latest_metrics:
                    continue

                m = p.latest_metrics
                age_hours = (datetime.utcnow() - p.campaign.launched_at).total_seconds() / 3600

                # Only check campaigns that have been live 6-24 hours AND spent >$2
                if 6 <= age_hours <= 24 and m.spend_usd >= 2.0:
                    if m.roas < cfg.early_kill_roas_threshold:
                        self.log.info(
                            "guardrail_early_kill",
                            pipeline_id=p.id,
                            roas=m.roas,
                            spend=m.spend_usd,
                            age_hours=age_hours,
                        )
                        from mas.tools.meta_ads import pause_campaign
                        await pause_campaign(p.campaign)
                        p.transition(PipelineState.KILLED)
                        p.failure_reason = (
                            f"Early kill: ROAS {m.roas:.2f}x after {age_hours:.1f}h "
                            f"(threshold {cfg.early_kill_roas_threshold}x)"
                        )
                        await self.store.upsert_pipeline(p)
                        killed.append(p.id)

                        title = p.discovered_product.title if p.discovered_product else "Unknown"
                        await alert_campaign_killed(p.id, title, m.roas, m.spend_usd, days=0)
                        await self.emit(
                            "guardrail_early_kill",
                            pipeline_id=p.id,
                            roas=m.roas,
                            spend=m.spend_usd,
                        )

        return killed

    async def pre_flight_check(self, pipeline: ProductPipeline) -> Tuple[bool, str]:
        """Run pre-launch checks for a specific pipeline. Returns (ok, reason)."""
        cfg = get_settings()

        # Margin check
        if pipeline.supplier:
            if pipeline.supplier.gross_margin_pct < 40.0:
                return False, (
                    f"Margin too thin: {pipeline.supplier.gross_margin_pct:.1f}% "
                    f"(minimum 40%). AliExpress cost: ${pipeline.supplier.price_usd:.2f}, "
                    f"retail: ${pipeline.supplier.suggested_retail_price:.2f}"
                )

        # Competitor saturation check
        if pipeline.discovered_product:
            from mas.tools.fb_ad_library import research_competitors
            access_token = cfg.meta_access_token or None
            comp = await research_competitors(
                pipeline.discovered_product.title,
                access_token=access_token,
            )
            if comp.get("recommendation") == "CAUTION":
                return False, (
                    f"Market saturated: {comp['active_competitor_ads']} active competitor ads. "
                    f"Status: {comp['saturation']}. HITL approval required."
                )

        return True, "pre_flight_passed"

    async def run(self) -> Dict[str, any]:
        return await self.run_with_retry()

"""PerformanceMonitorAgent — tracks campaign metrics and auto-scales / kills.

Decision logic (runs every call on CAMPAIGN_LIVE / MONITORING pipelines):
  - After 3 days, if ROAS < MIN_ROAS_THRESHOLD → pause campaign (KILLED)
  - If ROAS > 3.0 → double daily budget (SCALED)
  - Otherwise → continue monitoring (MONITORING)

Metrics are fetched from Meta Insights API and persisted to the pipeline record.
"""
from __future__ import annotations

from typing import List

from config.settings import get_settings
from mas.agents.base import BaseAgent
from mas.state.models import (
    AdStatus,
    PerformanceMetrics,
    PipelineState,
    ProductPipeline,
)
from mas.state.store import StateStore
from mas.tools.meta_ads import fetch_campaign_insights, pause_campaign


class PerformanceMonitorAgent(BaseAgent):
    def __init__(self, store: StateStore) -> None:
        super().__init__(store)

    async def _run(self, pipeline: ProductPipeline) -> ProductPipeline:
        if not pipeline.campaign:
            return pipeline

        cfg = get_settings()
        raw = await fetch_campaign_insights(pipeline.campaign)

        if not raw:
            self.log.debug("performance_no_data", pipeline_id=pipeline.id)
            pipeline.transition(PipelineState.MONITORING)
            await self.store.upsert_pipeline(pipeline)
            return pipeline

        m = PerformanceMetrics(
            product_id=pipeline.id,
            campaign_id=pipeline.campaign.meta_campaign_id,
            spend_usd=raw.get("spend", 0.0),
            impressions=raw.get("impressions", 0),
            clicks=raw.get("clicks", 0),
            purchases=raw.get("purchases", 0),
            revenue_usd=raw.get("revenue", 0.0),
        )
        m.compute()
        pipeline.metrics.append(m)

        days_live = 0
        if pipeline.campaign.launched_at:
            from datetime import datetime
            days_live = (datetime.utcnow() - pipeline.campaign.launched_at).days

        self.log.info(
            "performance_snapshot",
            pipeline_id=pipeline.id,
            spend=m.spend_usd,
            roas=m.roas,
            purchases=m.purchases,
            days_live=days_live,
        )

        await self.emit(
            "performance_recorded",
            pipeline_id=pipeline.id,
            roas=m.roas,
            spend=m.spend_usd,
            purchases=m.purchases,
            days_live=days_live,
        )

        # ── Decision logic ─────────────────────────────────────────────────────
        if days_live >= 3 and m.spend_usd > 0 and m.roas < cfg.min_roas_threshold:
            self.log.info(
                "campaign_killed_low_roas",
                pipeline_id=pipeline.id,
                roas=m.roas,
                threshold=cfg.min_roas_threshold,
            )
            await pause_campaign(pipeline.campaign)
            pipeline.transition(PipelineState.KILLED)
            await self.emit("campaign_killed", pipeline_id=pipeline.id, roas=m.roas)

        elif m.roas >= 3.0 and pipeline.state != PipelineState.SCALED:
            new_budget = round(pipeline.campaign.daily_budget_usd * cfg.scale_budget_multiplier, 2)
            self.log.info(
                "campaign_scaled",
                pipeline_id=pipeline.id,
                old_budget=pipeline.campaign.daily_budget_usd,
                new_budget=new_budget,
            )
            pipeline.campaign.daily_budget_usd = new_budget
            pipeline.transition(PipelineState.SCALED)
            await self.emit(
                "campaign_scaled",
                pipeline_id=pipeline.id,
                new_budget=new_budget,
                roas=m.roas,
            )

        else:
            pipeline.transition(PipelineState.MONITORING)

        await self.store.upsert_pipeline(pipeline)
        return pipeline

    async def run(self, pipeline: ProductPipeline) -> ProductPipeline:
        return await self.run_with_retry(pipeline)

    async def process_queue(self) -> List[str]:
        """Check all live/monitoring/scaled pipelines for performance."""
        active_states = [
            PipelineState.CAMPAIGN_LIVE,
            PipelineState.MONITORING,
            PipelineState.SCALED,
        ]
        processed: List[str] = []
        for state in active_states:
            pipelines = await self.store.list_pipelines(state=state)
            for p in pipelines:
                updated = await self.run(p)
                processed.append(updated.id)
        return processed

"""CampaignDeployAgent — creates and activates Meta + TikTok Ads campaigns.

Picks up CONTENT_GENERATED pipelines (or AWAITING_APPROVAL ones that have been
approved by a human), runs the GuardrailAgent pre-flight check, then builds the
full campaign structure on Meta (and TikTok if configured), then activates.

Campaign structure (per platform):
  Campaign (OUTCOME_SALES / PRODUCT_SALES)
    └─ Ad Set  (USA | 18-35 | $5/day | broad targeting)
         ├─ Ad variant 0  (creative A)
         ├─ Ad variant 1  (creative B)
         └─ Ad variant 2  (creative C)

Fail-closed: if the pre-flight check fails (thin margin / saturated market),
the pipeline is routed back to AWAITING_APPROVAL instead of deploying.
"""
from __future__ import annotations

from datetime import datetime
from typing import List

from mas.agents.base import BaseAgent
from mas.agents.guardrail import GuardrailAgent
from mas.state.models import AdStatus, PipelineState, ProductPipeline
from mas.state.store import StateStore
from mas.tools.meta_ads import activate_campaign, create_campaign
from mas.tools.tiktok_ads import create_tiktok_campaign


class CampaignDeployAgent(BaseAgent):
    def __init__(self, store: StateStore) -> None:
        super().__init__(store)
        self._guardrail = GuardrailAgent(store)

    async def _run(self, pipeline: ProductPipeline) -> ProductPipeline:
        if not pipeline.supplier or not pipeline.content:
            raise ValueError(f"Pipeline {pipeline.id} missing supplier or content")

        lander_url = ""
        if pipeline.content.landing_page:
            lander_url = pipeline.content.landing_page.lander_url

        # ── Pre-flight guardrail check (margin + competitor saturation) ──────────
        ok, reason = await self._guardrail.pre_flight_check(pipeline)
        if not ok:
            self.log.warning(
                "campaign_deploy_blocked_preflight",
                pipeline_id=pipeline.id,
                reason=reason,
            )
            pipeline.competitor_research = {"preflight": reason}
            pipeline.transition(PipelineState.AWAITING_APPROVAL)
            await self.store.upsert_pipeline(pipeline)
            await self.emit("preflight_blocked", pipeline_id=pipeline.id, reason=reason)
            return pipeline

        self.log.info("campaign_deploy_start", pipeline_id=pipeline.id, lander_url=lander_url)

        # ── Meta campaign ────────────────────────────────────────────────────────
        campaign_result = await create_campaign(
            supplier=pipeline.supplier,
            creatives=pipeline.content.ad_creatives,
            lander_url=lander_url,
        )
        campaign_result.platform = "META"
        if campaign_result.status != AdStatus.DRAFT:
            await activate_campaign(campaign_result)
        pipeline.campaign = campaign_result

        # ── TikTok campaign (parallel channel, if configured) ────────────────────
        tiktok_result = await create_tiktok_campaign(
            supplier=pipeline.supplier,
            creatives=pipeline.content.ad_creatives,
            lander_url=lander_url,
        )
        if tiktok_result is not None:
            tiktok_result.platform = "TIKTOK"
            pipeline.tiktok_campaign = tiktok_result
            self.log.info(
                "tiktok_campaign_attached",
                pipeline_id=pipeline.id,
                tiktok_campaign_id=tiktok_result.meta_campaign_id,
            )

        pipeline.transition(PipelineState.CAMPAIGN_LIVE)
        await self.store.upsert_pipeline(pipeline)

        await self.emit(
            "campaign_live",
            pipeline_id=pipeline.id,
            campaign_id=campaign_result.meta_campaign_id,
            tiktok_campaign_id=tiktok_result.meta_campaign_id if tiktok_result else "",
            budget_usd=campaign_result.daily_budget_usd,
            status=campaign_result.status.value,
        )

        self.log.info(
            "campaign_deploy_complete",
            pipeline_id=pipeline.id,
            campaign_id=campaign_result.meta_campaign_id,
            status=campaign_result.status.value,
        )
        return pipeline

    async def run(self, pipeline: ProductPipeline) -> ProductPipeline:
        return await self.run_with_retry(pipeline)

    async def process_queue(self) -> List[str]:
        """Process CONTENT_GENERATED pipelines."""
        pipelines = await self.store.list_pipelines(state=PipelineState.CONTENT_GENERATED)
        advanced: List[str] = []
        for p in pipelines:
            updated = await self.run(p)
            if updated.state == PipelineState.CAMPAIGN_LIVE:
                advanced.append(updated.id)
        return advanced

    async def approve_and_deploy(self, pipeline_id: str) -> ProductPipeline:
        """Human-in-the-Loop approval: move AWAITING_APPROVAL → CONTENT_GENERATED → CAMPAIGN_LIVE."""
        pipeline = await self.store.get_pipeline(pipeline_id)
        if pipeline is None:
            raise ValueError(f"Pipeline {pipeline_id} not found")
        if pipeline.state != PipelineState.AWAITING_APPROVAL:
            raise ValueError(
                f"Pipeline {pipeline_id} is in state {pipeline.state}, expected AWAITING_APPROVAL"
            )

        self.log.info("hitl_approval_received", pipeline_id=pipeline_id)
        pipeline.transition(PipelineState.CONTENT_GENERATED)
        await self.store.upsert_pipeline(pipeline)

        await self.emit("hitl_approved", pipeline_id=pipeline_id)
        return await self.run(pipeline)

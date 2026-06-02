"""ContentForgeAgent — generates landing pages and Facebook ad creatives via Claude.

Picks up SUPPLIER_VALIDATED pipelines, calls Claude (with prompt caching for
the system prompt) to produce:
  - A full HTML landing page (saved to landers/{pipeline_id}.html)
  - 3 Facebook ad creative variants

Advances state to CONTENT_GENERATED, or AWAITING_APPROVAL if HITL is enabled.
"""
from __future__ import annotations

from typing import List

from config.settings import get_settings
from mas.agents.base import BaseAgent
from mas.state.models import PipelineState, ProductPipeline
from mas.state.store import StateStore
from mas.tools.page_builder import generate_content


class ContentForgeAgent(BaseAgent):
    def __init__(self, store: StateStore) -> None:
        super().__init__(store)

    async def _run(self, pipeline: ProductPipeline) -> ProductPipeline:
        if not pipeline.supplier:
            raise ValueError(f"Pipeline {pipeline.id} has no supplier")

        cfg = get_settings()
        self.log.info("content_forge_start", pipeline_id=pipeline.id)

        description = ""
        if pipeline.discovered_product:
            description = pipeline.discovered_product.description

        content = await generate_content(
            supplier=pipeline.supplier,
            discovered_description=description,
        )

        pipeline.content = content

        # Decide next state: HITL gate or straight to CONTENT_GENERATED
        if cfg.hitl_enabled:
            pipeline.transition(PipelineState.AWAITING_APPROVAL)
            await self.emit(
                "hitl_gate_triggered",
                pipeline_id=pipeline.id,
                approval_instructions=(
                    f"POST /campaigns/{pipeline.id}/approve "
                    f"with header X-Admin-Secret: <ADMIN_SECRET> to go live."
                ),
            )
            self.log.info(
                "content_forge_hitl_gate",
                pipeline_id=pipeline.id,
                lander_url=content.landing_page.lander_url if content.landing_page else "",
            )
        else:
            pipeline.transition(PipelineState.CONTENT_GENERATED)

        await self.store.upsert_pipeline(pipeline)

        await self.emit(
            "content_generated",
            pipeline_id=pipeline.id,
            lander_url=content.landing_page.lander_url if content.landing_page else "",
            ad_variants=len(content.ad_creatives),
            hitl=cfg.hitl_enabled,
        )
        return pipeline

    async def run(self, pipeline: ProductPipeline) -> ProductPipeline:
        return await self.run_with_retry(pipeline)

    async def process_queue(self) -> List[str]:
        """Process all SUPPLIER_VALIDATED pipelines."""
        pipelines = await self.store.list_pipelines(state=PipelineState.SUPPLIER_VALIDATED)
        advanced: List[str] = []
        for p in pipelines:
            updated = await self.run(p)
            if updated.state in (
                PipelineState.CONTENT_GENERATED,
                PipelineState.AWAITING_APPROVAL,
            ):
                advanced.append(updated.id)
        return advanced

"""SupplierIntelAgent — validates discovered products on AliExpress.

For each DISCOVERED pipeline, searches AliExpress for the best-matching supplier
that meets review count and rating thresholds. Advances state to SUPPLIER_VALIDATED
on success, or records a failure and leaves the pipeline for retry / human review.
"""
from __future__ import annotations

from typing import List

from mas.agents.base import BaseAgent
from mas.state.models import PipelineState, ProductPipeline
from mas.state.store import StateStore
from mas.tools.aliexpress_tool import find_supplier


class SupplierIntelAgent(BaseAgent):
    def __init__(self, store: StateStore) -> None:
        super().__init__(store)

    async def _run(self, pipeline: ProductPipeline) -> ProductPipeline:
        if not pipeline.discovered_product:
            raise ValueError(f"Pipeline {pipeline.id} has no discovered_product")

        keyword = pipeline.discovered_product.title
        self.log.info("supplier_search_start", pipeline_id=pipeline.id, keyword=keyword)

        supplier = await find_supplier(
            product_id=pipeline.id,
            keyword=keyword,
        )

        if supplier is None:
            pipeline.record_failure(f"No AliExpress supplier found for '{keyword}'")
            await self.store.upsert_pipeline(pipeline)
            await self.emit(
                "supplier_not_found",
                pipeline_id=pipeline.id,
                keyword=keyword,
            )
            return pipeline

        pipeline.supplier = supplier
        pipeline.transition(PipelineState.SUPPLIER_VALIDATED)
        await self.store.upsert_pipeline(pipeline)

        await self.emit(
            "supplier_validated",
            pipeline_id=pipeline.id,
            aliexpress_item_id=supplier.aliexpress_item_id,
            price=supplier.price_usd,
            reviews=supplier.review_count,
            rating=supplier.rating,
            margin_pct=supplier.gross_margin_pct,
        )

        self.log.info(
            "supplier_intel_complete",
            pipeline_id=pipeline.id,
            price=supplier.price_usd,
            retail=supplier.suggested_retail_price,
            margin=supplier.gross_margin_pct,
        )
        return pipeline

    async def run(self, pipeline: ProductPipeline) -> ProductPipeline:
        return await self.run_with_retry(pipeline)

    async def process_queue(self) -> List[str]:
        """Process all DISCOVERED pipelines. Returns list of advanced pipeline IDs."""
        pipelines = await self.store.list_pipelines(state=PipelineState.DISCOVERED)
        advanced: List[str] = []
        for p in pipelines:
            updated = await self.run(p)
            if updated.state == PipelineState.SUPPLIER_VALIDATED:
                advanced.append(updated.id)
        return advanced

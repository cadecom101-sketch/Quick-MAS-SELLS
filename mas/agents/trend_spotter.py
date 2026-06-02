"""TrendSpotterAgent — discovers trending products from TikTok and Amazon.

Runs discovery across both platforms, deduplicates by title similarity,
and persists new ProductPipeline records in state DISCOVERED.
"""
from __future__ import annotations

import asyncio
from typing import List

from config.settings import get_settings
from mas.agents.base import BaseAgent
from mas.state.models import DiscoveredProduct, PipelineState, ProductPipeline
from mas.state.store import StateStore
from mas.tools.amazon_scraper import discover_amazon_products
from mas.tools.tiktok_scraper import discover_tiktok_products


class TrendSpotterAgent(BaseAgent):
    def __init__(self, store: StateStore) -> None:
        super().__init__(store)

    async def _run(self) -> List[str]:
        """Discover products from TikTok + Amazon. Returns list of new pipeline IDs."""
        cfg = get_settings()
        limit = cfg.max_products_per_run

        self.log.info("trend_spotter_start", limit=limit)

        # Run both scrapers concurrently
        tiktok_products, amazon_products = await asyncio.gather(
            discover_tiktok_products(limit // 2 or 5),
            discover_amazon_products(limit // 2 or 5),
        )

        all_products: List[DiscoveredProduct] = tiktok_products + amazon_products

        # Load existing pipelines to avoid re-processing same products
        existing = await self.store.get_all_pipelines_map()
        existing_titles = {
            p.discovered_product.title.lower()[:40]
            for p in existing.values()
            if p.discovered_product
        }

        new_pipeline_ids: List[str] = []
        for product in all_products:
            key = product.title.lower()[:40]
            if key in existing_titles:
                self.log.debug("trend_spotter_skip_duplicate", title=product.title)
                continue

            pipeline = ProductPipeline(
                state=PipelineState.DISCOVERED,
                discovered_product=product,
            )
            await self.store.upsert_pipeline(pipeline)
            existing_titles.add(key)
            new_pipeline_ids.append(pipeline.id)

            await self.emit(
                "product_discovered",
                pipeline_id=pipeline.id,
                title=product.title,
                source=product.source.value,
                engagement=product.engagement_score,
            )

        self.log.info(
            "trend_spotter_complete",
            new_pipelines=len(new_pipeline_ids),
            tiktok=len(tiktok_products),
            amazon=len(amazon_products),
        )
        return new_pipeline_ids

    async def run(self) -> List[str]:
        return await self.run_with_retry()

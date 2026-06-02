from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from mas.state.models import PipelineState, ProductPipeline
from mas.state.store import StateStore, get_store

router = APIRouter(prefix="/products", tags=["products"])


class PipelineSummary(BaseModel):
    id: str
    state: str
    title: Optional[str]
    source: Optional[str]
    price_usd: Optional[float]
    retail_price: Optional[float]
    margin_pct: Optional[float]
    lander_url: Optional[str]
    roas: Optional[float]
    created_at: str
    updated_at: str


def _summarise(p: ProductPipeline) -> PipelineSummary:
    return PipelineSummary(
        id=p.id,
        state=p.state.value,
        title=p.discovered_product.title if p.discovered_product else None,
        source=p.discovered_product.source.value if p.discovered_product else None,
        price_usd=p.supplier.price_usd if p.supplier else None,
        retail_price=p.supplier.suggested_retail_price if p.supplier else None,
        margin_pct=p.supplier.gross_margin_pct if p.supplier else None,
        lander_url=(
            p.content.landing_page.lander_url
            if p.content and p.content.landing_page
            else None
        ),
        roas=p.latest_metrics.roas if p.latest_metrics else None,
        created_at=p.created_at.isoformat(),
        updated_at=p.updated_at.isoformat(),
    )


@router.get("/", response_model=List[PipelineSummary])
async def list_products(
    state: Optional[str] = Query(None, description="Filter by pipeline state"),
    limit: int = Query(50, le=200),
    store: StateStore = Depends(get_store),
):
    pipeline_state = None
    if state:
        try:
            pipeline_state = PipelineState(state.upper())
        except ValueError:
            raise HTTPException(400, f"Invalid state '{state}'. Valid: {[s.value for s in PipelineState]}")
    pipelines = await store.list_pipelines(state=pipeline_state, limit=limit)
    return [_summarise(p) for p in pipelines]


@router.get("/{product_id}", response_model=ProductPipeline)
async def get_product(product_id: str, store: StateStore = Depends(get_store)):
    pipeline = await store.get_pipeline(product_id)
    if pipeline is None:
        raise HTTPException(404, f"Pipeline {product_id} not found")
    return pipeline

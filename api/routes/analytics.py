from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from mas.state.models import PipelineState
from mas.state.store import StateStore, get_store

router = APIRouter(prefix="/analytics", tags=["analytics"])


class DashboardStats(BaseModel):
    total_products: int
    by_state: Dict[str, int]
    total_spend_usd: float
    total_revenue_usd: float
    overall_roas: float
    total_purchases: int
    top_performers: List[Dict[str, Any]]
    kill_rate_pct: float


@router.get("/dashboard", response_model=DashboardStats)
async def dashboard(store: StateStore = Depends(get_store)):
    all_pipelines = await store.list_pipelines(limit=10_000)

    by_state: Dict[str, int] = {}
    total_spend = 0.0
    total_revenue = 0.0
    total_purchases = 0
    performers = []

    for p in all_pipelines:
        by_state[p.state.value] = by_state.get(p.state.value, 0) + 1
        for m in p.metrics:
            total_spend += m.spend_usd
            total_revenue += m.revenue_usd
            total_purchases += m.purchases

        if p.latest_metrics and p.latest_metrics.roas > 0:
            performers.append(
                {
                    "pipeline_id": p.id,
                    "title": p.discovered_product.title if p.discovered_product else "?",
                    "roas": p.latest_metrics.roas,
                    "spend": p.latest_metrics.spend_usd,
                    "purchases": p.latest_metrics.purchases,
                    "state": p.state.value,
                }
            )

    performers.sort(key=lambda x: x["roas"], reverse=True)
    overall_roas = round(total_revenue / total_spend, 2) if total_spend else 0.0

    killed = by_state.get(PipelineState.KILLED.value, 0)
    live_or_past = sum(
        by_state.get(s.value, 0)
        for s in [
            PipelineState.CAMPAIGN_LIVE,
            PipelineState.MONITORING,
            PipelineState.SCALED,
            PipelineState.KILLED,
        ]
    )
    kill_rate = round(killed / live_or_past * 100, 1) if live_or_past else 0.0

    return DashboardStats(
        total_products=len(all_pipelines),
        by_state=by_state,
        total_spend_usd=round(total_spend, 2),
        total_revenue_usd=round(total_revenue, 2),
        overall_roas=overall_roas,
        total_purchases=total_purchases,
        top_performers=performers[:10],
        kill_rate_pct=kill_rate,
    )


@router.get("/events")
async def recent_events(
    pipeline_id: str = None,
    limit: int = 100,
    store: StateStore = Depends(get_store),
):
    events = await store.get_events(pipeline_id=pipeline_id, limit=limit)
    return [
        {
            "id": e.id,
            "agent": e.agent_name,
            "type": e.event_type,
            "pipeline_id": e.pipeline_id,
            "payload": e.payload,
            "at": e.emitted_at.isoformat() if hasattr(e.emitted_at, "isoformat") else str(e.emitted_at),
        }
        for e in events
    ]

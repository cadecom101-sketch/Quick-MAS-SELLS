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
    total_cogs_usd: float
    total_stripe_fees_usd: float
    net_profit_usd: float
    overall_roas: float
    total_purchases: int
    total_orders: int
    top_performers: List[Dict[str, Any]]
    kill_rate_pct: float


@router.get("/dashboard", response_model=DashboardStats)
async def dashboard(store: StateStore = Depends(get_store)):
    all_pipelines = await store.list_pipelines(limit=10_000)

    by_state: Dict[str, int] = {}
    total_spend = 0.0
    total_revenue = 0.0
    total_cogs = 0.0
    total_fees = 0.0
    total_purchases = 0
    total_orders = 0
    performers = []

    for p in all_pipelines:
        by_state[p.state.value] = by_state.get(p.state.value, 0) + 1
        total_orders += len(p.orders)
        # Use only the latest metrics snapshot per pipeline — earlier snapshots are
        # cumulative-to-date from the ad platform, so summing all rows double-counts.
        lm = p.latest_metrics
        if lm:
            total_spend += lm.spend_usd
            total_revenue += lm.revenue_usd
            total_cogs += lm.cogs_usd
            total_fees += lm.stripe_fees_usd
            total_purchases += lm.purchases

        if lm and lm.roas > 0:
            performers.append(
                {
                    "pipeline_id": p.id,
                    "title": p.discovered_product.title if p.discovered_product else "?",
                    "roas": lm.roas,
                    "spend": lm.spend_usd,
                    "net_profit": lm.net_profit_usd,
                    "purchases": lm.purchases,
                    "state": p.state.value,
                }
            )

    performers.sort(key=lambda x: x["roas"], reverse=True)
    overall_roas = round(total_revenue / total_spend, 2) if total_spend else 0.0
    net_profit = round(total_revenue - total_spend - total_cogs - total_fees, 2)

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
        total_cogs_usd=round(total_cogs, 2),
        total_stripe_fees_usd=round(total_fees, 2),
        net_profit_usd=net_profit,
        overall_roas=overall_roas,
        total_purchases=total_purchases,
        total_orders=total_orders,
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

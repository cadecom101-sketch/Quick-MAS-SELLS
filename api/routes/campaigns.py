from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from config.settings import get_settings
from mas.state.models import PipelineState, ProductPipeline
from mas.state.store import StateStore, get_store

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


class ApproveResponse(BaseModel):
    pipeline_id: str
    state: str
    message: str


class CampaignDetail(BaseModel):
    pipeline_id: str
    state: str
    meta_campaign_id: str
    meta_adset_id: str
    meta_ad_ids: List[str]
    daily_budget_usd: float
    status: str
    launched_at: str | None
    lander_url: str | None


@router.get("/", response_model=List[CampaignDetail])
async def list_campaigns(store: StateStore = Depends(get_store)):
    live_states = [
        PipelineState.CAMPAIGN_LIVE,
        PipelineState.MONITORING,
        PipelineState.SCALED,
        PipelineState.KILLED,
        PipelineState.AWAITING_APPROVAL,
    ]
    details: List[CampaignDetail] = []
    for state in live_states:
        pipelines = await store.list_pipelines(state=state)
        for p in pipelines:
            if not p.campaign:
                continue
            details.append(
                CampaignDetail(
                    pipeline_id=p.id,
                    state=p.state.value,
                    meta_campaign_id=p.campaign.meta_campaign_id,
                    meta_adset_id=p.campaign.meta_adset_id,
                    meta_ad_ids=p.campaign.meta_ad_ids,
                    daily_budget_usd=p.campaign.daily_budget_usd,
                    status=p.campaign.status.value,
                    launched_at=(
                        p.campaign.launched_at.isoformat() if p.campaign.launched_at else None
                    ),
                    lander_url=(
                        p.content.landing_page.lander_url
                        if p.content and p.content.landing_page
                        else None
                    ),
                )
            )
    return details


@router.post("/{pipeline_id}/approve", response_model=ApproveResponse)
async def approve_campaign(
    pipeline_id: str,
    x_admin_secret: str = Header(..., alias="X-Admin-Secret"),
    store: StateStore = Depends(get_store),
):
    import secrets
    cfg = get_settings()
    if not secrets.compare_digest(x_admin_secret, cfg.admin_secret):
        raise HTTPException(403, "Invalid admin secret")

    pipeline = await store.get_pipeline(pipeline_id)
    if pipeline is None:
        raise HTTPException(404, f"Pipeline {pipeline_id} not found")
    if pipeline.state != PipelineState.AWAITING_APPROVAL:
        raise HTTPException(
            400,
            f"Pipeline is in state '{pipeline.state.value}', not AWAITING_APPROVAL",
        )

    # Import here to avoid circular dependency
    from mas.agents.campaign_deploy import CampaignDeployAgent

    agent = CampaignDeployAgent(store)
    updated = await agent.approve_and_deploy(pipeline_id)

    return ApproveResponse(
        pipeline_id=updated.id,
        state=updated.state.value,
        message=f"Campaign approved and deployed. State: {updated.state.value}",
    )


@router.get("/awaiting-approval", response_model=List[dict])
async def list_awaiting_approval(store: StateStore = Depends(get_store)):
    pipelines = await store.list_pipelines(state=PipelineState.AWAITING_APPROVAL)
    return [
        {
            "pipeline_id": p.id,
            "title": p.discovered_product.title if p.discovered_product else "Unknown",
            "price_usd": p.supplier.price_usd if p.supplier else None,
            "retail_price": p.supplier.suggested_retail_price if p.supplier else None,
            "lander_url": (
                p.content.landing_page.lander_url
                if p.content and p.content.landing_page
                else None
            ),
            "ad_previews": [
                {"headline": c.headline, "body": c.body, "cta": c.cta}
                for c in (p.content.ad_creatives if p.content else [])
            ],
            "approval_endpoint": f"POST /campaigns/{p.id}/approve",
        }
        for p in pipelines
    ]

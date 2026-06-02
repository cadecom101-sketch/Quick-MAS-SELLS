"""TikTok Ads Manager API integration.

Creates TikTok campaigns targeting US 18-35 — the exact audience that
discovers products via #TikTokMadeMeBuyIt. TikTok CPMs are typically
30-60% cheaper than Meta for this demographic.

TikTok Marketing API docs: https://ads.tiktok.com/marketing_api/docs/
App registration:          https://ads.tiktok.com/marketing_api/homepage/

Campaign structure:
  Campaign (PRODUCT_SALES / CONVERSION)
    └─ Ad Group  (US | 18-35 | $5/day | placement: TikTok feed + TopView)
         └─ Ad (video or image spark ad)

Requirements in .env:
  TIKTOK_APP_ID
  TIKTOK_APP_SECRET
  TIKTOK_ACCESS_TOKEN     ← from OAuth or sandbox
  TIKTOK_ADVERTISER_ID
  TIKTOK_PIXEL_ID         ← from TikTok Events Manager
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from config.settings import get_settings
from mas.state.models import AdCreative, AdStatus, CampaignResult, SupplierProduct
from mas.tools.http_client import fetch_json

logger = logging.getLogger(__name__)

_TIKTOK_API_BASE = "https://business-api.tiktok.com/open_api/v1.3"


def _headers(access_token: str) -> Dict[str, str]:
    return {
        "Access-Token": access_token,
        "Content-Type": "application/json",
    }


async def _tt_post(endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    cfg = get_settings()
    import httpx
    url = f"{_TIKTOK_API_BASE}/{endpoint}/"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            url,
            json=payload,
            headers=_headers(cfg.tiktok_access_token),
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"TikTok API error {data.get('code')}: {data.get('message')}")
        return data.get("data", {})


async def create_tiktok_campaign(
    supplier: SupplierProduct,
    creatives: List[AdCreative],
    lander_url: str,
) -> Optional[CampaignResult]:
    """Create a TikTok campaign. Returns CampaignResult or None if not configured."""
    cfg = get_settings()

    if not cfg.tiktok_configured:
        logger.warning(
            "tiktok_not_configured",
            msg="Set TIKTOK_APP_ID, TIKTOK_ACCESS_TOKEN, TIKTOK_ADVERTISER_ID in .env",
        )
        return None

    result = CampaignResult(
        product_id=supplier.product_id,
        daily_budget_usd=cfg.daily_ad_budget_usd,
        status=AdStatus.DRAFT,
    )

    try:
        # 1. Campaign
        campaign_data = await _tt_post(
            "campaign/create",
            {
                "advertiser_id": cfg.tiktok_advertiser_id,
                "campaign_name": f"QMS_{supplier.title[:25]}",
                "objective_type": "PRODUCT_SALES",
                "budget_mode": "BUDGET_MODE_DAY",
                "budget": cfg.daily_ad_budget_usd,
            },
        )
        campaign_id = campaign_data.get("campaign_id", "")
        result.meta_campaign_id = campaign_id  # reuse field for TikTok campaign ID

        # 2. Ad Group
        adgroup_data = await _tt_post(
            "adgroup/create",
            {
                "advertiser_id": cfg.tiktok_advertiser_id,
                "campaign_id": campaign_id,
                "adgroup_name": f"QMS_adgroup_{supplier.title[:20]}",
                "placement_type": "PLACEMENT_TYPE_AUTOMATIC",
                "budget_mode": "BUDGET_MODE_DAY",
                "budget": cfg.daily_ad_budget_usd,
                "schedule_type": "SCHEDULE_FROM_NOW",
                "billing_event": "OCPM",
                "optimization_goal": "CONVERT",
                "location_ids": ["6252001"],  # USA
                "age_groups": ["AGE_18_24", "AGE_25_34"],
                "operation_status": "DISABLE",  # start paused for HITL
                "pixel_id": cfg.tiktok_pixel_id,
                "conversion_event": "COMPLETE_PAYMENT",
                "landing_page_url": lander_url,
            },
        )
        adgroup_id = adgroup_data.get("adgroup_id", "")
        result.meta_adset_id = adgroup_id

        # 3. Ads (one per creative — use image carousel for non-video)
        ad_ids: List[str] = []
        for i, creative in enumerate(creatives[:3]):
            ad_data = await _tt_post(
                "ad/create",
                {
                    "advertiser_id": cfg.tiktok_advertiser_id,
                    "adgroup_id": adgroup_id,
                    "creatives": [
                        {
                            "ad_name": f"QMS_ad_{i}",
                            "ad_format": "SINGLE_IMAGE",
                            "image_ids": [],  # populated when image uploaded
                            "ad_text": creative.body,
                            "call_to_action": "SHOP_NOW",
                            "landing_page_url": lander_url,
                        }
                    ],
                    "operation_status": "DISABLE",
                },
            )
            ad_ids.append(ad_data.get("ad_id", ""))

        result.meta_ad_ids = ad_ids
        result.status = AdStatus.PENDING

        logger.info(
            "tiktok_campaign_created",
            product_id=supplier.product_id,
            campaign_id=campaign_id,
            adgroup_id=adgroup_id,
        )

    except Exception as exc:
        logger.error("tiktok_campaign_failed", product_id=supplier.product_id, error=str(exc))
        result.status = AdStatus.DRAFT

    return result


async def fetch_tiktok_insights(campaign_id: str) -> Dict[str, Any]:
    """Pull spend, clicks, purchases from TikTok Reporting API."""
    cfg = get_settings()
    if not cfg.tiktok_configured or not campaign_id:
        return {}
    try:
        data = await _tt_post(
            "report/integrated/get",
            {
                "advertiser_id": cfg.tiktok_advertiser_id,
                "report_type": "BASIC",
                "dimensions": ["campaign_id"],
                "data_level": "AUCTION_CAMPAIGN",
                "metrics": ["spend", "impressions", "clicks", "conversion", "total_purchase_value"],
                "filters": [{"field_name": "campaign_ids", "filter_type": "IN", "filter_value": [campaign_id]}],
                "page_size": 1,
            },
        )
        rows = data.get("list", [])
        if not rows:
            return {}
        row = rows[0].get("metrics", {})
        return {
            "spend": float(row.get("spend", 0)),
            "impressions": int(row.get("impressions", 0)),
            "clicks": int(row.get("clicks", 0)),
            "purchases": int(row.get("conversion", 0)),
            "revenue": float(row.get("total_purchase_value", 0)),
        }
    except Exception as exc:
        logger.warning("tiktok_insights_failed", campaign_id=campaign_id, error=str(exc))
        return {}

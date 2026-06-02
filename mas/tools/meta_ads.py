"""Meta (Facebook/Instagram) Ads SDK wrapper.

Creates a complete campaign structure:
  Campaign → Ad Set (targeting) → Ad Creatives → Ads

Targeting:  USA, ages 18-35, broad (no interest stacking — lets Meta's algorithm optimise)
Budget:     $5.00/day per ad set (configurable)
Objective:  OUTCOME_SALES (conversion optimisation)
Pixel:      Tracks Purchase event

Requires: pip install facebook-business
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from config.settings import get_settings
from mas.state.models import AdCreative, AdStatus, CampaignResult, SupplierProduct

logger = logging.getLogger(__name__)


def _sdk():
    """Lazy import so the app starts fine even if facebook-business is missing."""
    try:
        from facebook_business.api import FacebookAdsApi
        from facebook_business.adobjects.adaccount import AdAccount
        from facebook_business.adobjects.campaign import Campaign
        from facebook_business.adobjects.adset import AdSet
        from facebook_business.adobjects.adcreative import AdCreative as FBAdCreative
        from facebook_business.adobjects.ad import Ad
        from facebook_business.adobjects.adimage import AdImage
        return FacebookAdsApi, AdAccount, Campaign, AdSet, FBAdCreative, Ad, AdImage
    except ImportError:
        raise ImportError("facebook-business package not installed. Run: pip install facebook-business")


def _init_api(cfg) -> None:
    FacebookAdsApi, *_ = _sdk()
    FacebookAdsApi.init(
        app_id=cfg.meta_app_id,
        app_secret=cfg.meta_app_secret,
        access_token=cfg.meta_access_token,
    )


def _build_targeting(cfg) -> Dict[str, Any]:
    return {
        "geo_locations": {
            "countries": [cfg.target_country],
            "location_types": ["home", "recent"],
        },
        "age_min": cfg.target_age_min,
        "age_max": cfg.target_age_max,
        "publisher_platforms": ["facebook", "instagram", "audience_network"],
        "facebook_positions": ["feed", "instant_article", "marketplace", "video_feeds"],
        "instagram_positions": ["stream", "explore"],
        "device_platforms": ["mobile", "desktop"],
    }


async def create_campaign(
    supplier: SupplierProduct,
    creatives: List[AdCreative],
    lander_url: str,
) -> CampaignResult:
    """Create full Meta campaign. Returns CampaignResult with IDs."""
    cfg = get_settings()
    result = CampaignResult(product_id=supplier.product_id, daily_budget_usd=cfg.daily_ad_budget_usd)

    if not cfg.meta_configured:
        logger.warning(
            "meta_not_configured",
            msg="Meta credentials not set — campaign saved as DRAFT only. "
                "Set META_APP_ID, META_ACCESS_TOKEN, META_AD_ACCOUNT_ID, META_PAGE_ID in .env",
            product_id=supplier.product_id,
        )
        result.status = AdStatus.DRAFT
        return result

    FacebookAdsApi, AdAccount, Campaign, AdSet, FBAdCreative, Ad, AdImage = _sdk()
    _init_api(cfg)

    account = AdAccount(cfg.meta_ad_account_id)
    slug = supplier.title[:30].replace(" ", "_").lower()
    ts = int(time.time())

    # 1. Campaign
    campaign = account.create_campaign(
        fields=[Campaign.Field.id],
        params={
            Campaign.Field.name: f"QMS_{slug}_{ts}",
            Campaign.Field.objective: Campaign.Objective.outcome_sales,
            Campaign.Field.status: Campaign.Status.paused,  # start paused; activate after HITL
            Campaign.Field.special_ad_categories: [],
        },
    )
    result.meta_campaign_id = campaign[Campaign.Field.id]
    logger.info("meta_campaign_created", campaign_id=result.meta_campaign_id)

    # 2. Ad Set
    adset = account.create_ad_set(
        fields=[AdSet.Field.id],
        params={
            AdSet.Field.name: f"QMS_adset_{slug}_{ts}",
            AdSet.Field.campaign_id: result.meta_campaign_id,
            AdSet.Field.daily_budget: cfg.daily_budget_cents,
            AdSet.Field.billing_event: AdSet.BillingEvent.impressions,
            AdSet.Field.optimization_goal: AdSet.OptimizationGoal.offsite_conversions,
            AdSet.Field.targeting: _build_targeting(cfg),
            AdSet.Field.status: AdSet.Status.paused,
            AdSet.Field.promoted_object: {
                "pixel_id": cfg.meta_pixel_id,
                "custom_event_type": "PURCHASE",
            },
        },
    )
    result.meta_adset_id = adset[AdSet.Field.id]
    logger.info("meta_adset_created", adset_id=result.meta_adset_id)

    # 3. Ad Creatives + Ads (one per creative variant)
    ad_ids: List[str] = []
    for i, creative in enumerate(creatives[:3]):
        link_data = {
            "message": creative.body,
            "link": lander_url,
            "name": creative.headline,
            "call_to_action": {
                "type": "SHOP_NOW",
                "value": {"link": lander_url},
            },
        }
        if creative.image_url:
            link_data["picture"] = creative.image_url

        fb_creative = account.create_ad_creative(
            fields=[FBAdCreative.Field.id],
            params={
                FBAdCreative.Field.name: f"QMS_creative_{slug}_{ts}_{i}",
                FBAdCreative.Field.object_story_spec: {
                    "page_id": cfg.meta_page_id,
                    "link_data": link_data,
                },
            },
        )
        creative_id = fb_creative[FBAdCreative.Field.id]

        ad = account.create_ad(
            fields=[Ad.Field.id],
            params={
                Ad.Field.name: f"QMS_ad_{slug}_{ts}_{i}",
                Ad.Field.adset_id: result.meta_adset_id,
                Ad.Field.creative: {"creative_id": creative_id},
                Ad.Field.status: Ad.Status.paused,
            },
        )
        ad_ids.append(ad[Ad.Field.id])
        logger.info("meta_ad_created", ad_id=ad[Ad.Field.id], creative_idx=i)

    result.meta_ad_ids = ad_ids
    result.status = AdStatus.PENDING
    return result


async def activate_campaign(campaign_result: CampaignResult) -> None:
    """Flip campaign, ad set, and all ads from PAUSED → ACTIVE."""
    cfg = get_settings()
    if not cfg.meta_configured or not campaign_result.meta_campaign_id:
        logger.warning("meta_activate_skipped", product_id=campaign_result.product_id)
        campaign_result.status = AdStatus.ACTIVE
        return

    FacebookAdsApi, AdAccount, Campaign, AdSet, FBAdCreative, Ad, AdImage = _sdk()
    _init_api(cfg)

    Campaign(campaign_result.meta_campaign_id).api_update(
        params={"status": Campaign.Status.active}
    )
    AdSet(campaign_result.meta_adset_id).api_update(
        params={"status": AdSet.Status.active}
    )
    for ad_id in campaign_result.meta_ad_ids:
        Ad(ad_id).api_update(params={"status": Ad.Status.active})

    campaign_result.status = AdStatus.ACTIVE
    from datetime import datetime
    campaign_result.launched_at = datetime.utcnow()
    logger.info("meta_campaign_activated", campaign_id=campaign_result.meta_campaign_id)


async def pause_campaign(campaign_result: CampaignResult) -> None:
    """Pause a live campaign (kill-switch)."""
    cfg = get_settings()
    if not cfg.meta_configured or not campaign_result.meta_campaign_id:
        campaign_result.status = AdStatus.PAUSED
        return

    FacebookAdsApi, AdAccount, Campaign, *_ = _sdk()
    _init_api(cfg)
    Campaign(campaign_result.meta_campaign_id).api_update(
        params={"status": Campaign.Status.paused}
    )
    campaign_result.status = AdStatus.PAUSED
    logger.info("meta_campaign_paused", campaign_id=campaign_result.meta_campaign_id)


async def fetch_campaign_insights(campaign_result: CampaignResult) -> Dict[str, Any]:
    """Pull spend, impressions, clicks, and purchase conversions from Meta Insights API."""
    cfg = get_settings()
    if not cfg.meta_configured or not campaign_result.meta_campaign_id:
        return {}

    FacebookAdsApi, AdAccount, Campaign, *_ = _sdk()
    _init_api(cfg)

    insights = Campaign(campaign_result.meta_campaign_id).get_insights(
        fields=["spend", "impressions", "clicks", "actions", "action_values"],
        params={"date_preset": "lifetime"},
    )
    if not insights:
        return {}

    row = insights[0]
    purchases = sum(
        int(a["value"])
        for a in row.get("actions", [])
        if a["action_type"] == "purchase"
    )
    revenue = sum(
        float(v["value"])
        for v in row.get("action_values", [])
        if v["action_type"] == "purchase"
    )
    return {
        "spend": float(row.get("spend", 0)),
        "impressions": int(row.get("impressions", 0)),
        "clicks": int(row.get("clicks", 0)),
        "purchases": purchases,
        "revenue": revenue,
    }

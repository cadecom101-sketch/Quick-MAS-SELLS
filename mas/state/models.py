from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.utcnow()


# ──────────────────────────────────────────────────────────────────────────────
# Enumerations
# ──────────────────────────────────────────────────────────────────────────────

class PipelineState(str, Enum):
    DISCOVERED = "DISCOVERED"
    SUPPLIER_VALIDATED = "SUPPLIER_VALIDATED"
    CONTENT_GENERATED = "CONTENT_GENERATED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"  # HITL gate
    CAMPAIGN_LIVE = "CAMPAIGN_LIVE"
    MONITORING = "MONITORING"
    SCALED = "SCALED"
    KILLED = "KILLED"
    FAILED = "FAILED"


class AdStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DELETED = "DELETED"


class SourcePlatform(str, Enum):
    TIKTOK = "TIKTOK"
    AMAZON = "AMAZON"


# ──────────────────────────────────────────────────────────────────────────────
# Domain models
# ──────────────────────────────────────────────────────────────────────────────

class DiscoveredProduct(BaseModel):
    id: str = Field(default_factory=_uid)
    source: SourcePlatform
    title: str
    description: str = ""
    source_url: str = ""
    engagement_score: float = 0.0  # likes+comments+shares normalised 0-1
    keyword: str = ""
    raw_metadata: Dict[str, Any] = Field(default_factory=dict)
    discovered_at: datetime = Field(default_factory=_now)


class SupplierProduct(BaseModel):
    product_id: str
    aliexpress_item_id: str = ""
    aliexpress_url: str = ""
    title: str
    price_usd: float
    original_price_usd: float = 0.0
    review_count: int = 0
    rating: float = 0.0
    shipping_days: int = 15
    image_urls: List[str] = Field(default_factory=list)
    supplier_name: str = ""
    validated_at: datetime = Field(default_factory=_now)

    @property
    def suggested_retail_price(self) -> float:
        return round(self.price_usd * 3.5, 2)

    @property
    def gross_margin_pct(self) -> float:
        if self.suggested_retail_price == 0:
            return 0.0
        return round(
            (self.suggested_retail_price - self.price_usd) / self.suggested_retail_price * 100, 1
        )


class AdCreative(BaseModel):
    headline: str
    body: str
    cta: str = "Shop Now"
    image_url: str = ""


class LandingPage(BaseModel):
    product_id: str
    html: str
    lander_url: str = ""
    generated_at: datetime = Field(default_factory=_now)


class GeneratedContent(BaseModel):
    product_id: str
    landing_page: Optional[LandingPage] = None
    ad_creatives: List[AdCreative] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=_now)


class CampaignResult(BaseModel):
    product_id: str
    meta_campaign_id: str = ""
    meta_adset_id: str = ""
    meta_ad_ids: List[str] = Field(default_factory=list)
    daily_budget_usd: float = 5.0
    status: AdStatus = AdStatus.DRAFT
    launched_at: Optional[datetime] = None
    approval_token: str = Field(default_factory=_uid)


class PerformanceMetrics(BaseModel):
    product_id: str
    campaign_id: str = ""
    spend_usd: float = 0.0
    impressions: int = 0
    clicks: int = 0
    purchases: int = 0
    revenue_usd: float = 0.0
    roas: float = 0.0
    ctr: float = 0.0
    cpc_usd: float = 0.0
    recorded_at: datetime = Field(default_factory=_now)

    def compute(self) -> None:
        self.roas = round(self.revenue_usd / self.spend_usd, 2) if self.spend_usd else 0.0
        self.ctr = round(self.clicks / self.impressions * 100, 2) if self.impressions else 0.0
        self.cpc_usd = round(self.spend_usd / self.clicks, 2) if self.clicks else 0.0


class ProductPipeline(BaseModel):
    """Top-level aggregate tracking one product through the full pipeline."""
    id: str = Field(default_factory=_uid)
    state: PipelineState = PipelineState.DISCOVERED
    discovered_product: Optional[DiscoveredProduct] = None
    supplier: Optional[SupplierProduct] = None
    content: Optional[GeneratedContent] = None
    campaign: Optional[CampaignResult] = None
    metrics: List[PerformanceMetrics] = Field(default_factory=list)
    failure_reason: str = ""
    failure_count: int = 0
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    def transition(self, new_state: PipelineState) -> None:
        self.state = new_state
        self.updated_at = _now()

    def record_failure(self, reason: str) -> None:
        self.failure_count += 1
        self.failure_reason = reason
        self.updated_at = _now()
        if self.failure_count >= 3:
            self.state = PipelineState.FAILED

    @property
    def latest_metrics(self) -> Optional[PerformanceMetrics]:
        return self.metrics[-1] if self.metrics else None


# ──────────────────────────────────────────────────────────────────────────────
# Event bus models
# ──────────────────────────────────────────────────────────────────────────────

class AgentEvent(BaseModel):
    id: str = Field(default_factory=_uid)
    agent_name: str
    event_type: str
    pipeline_id: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)
    emitted_at: datetime = Field(default_factory=_now)

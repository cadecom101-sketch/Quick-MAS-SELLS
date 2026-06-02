from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Anthropic
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")

    # Meta Ads
    meta_app_id: str = Field(default="", alias="META_APP_ID")
    meta_app_secret: str = Field(default="", alias="META_APP_SECRET")
    meta_access_token: str = Field(default="", alias="META_ACCESS_TOKEN")
    meta_ad_account_id: str = Field(default="act_000000000000000", alias="META_AD_ACCOUNT_ID")
    meta_page_id: str = Field(default="", alias="META_PAGE_ID")
    meta_pixel_id: str = Field(default="", alias="META_PIXEL_ID")

    # Campaign config
    daily_ad_budget_usd: float = Field(default=5.00, alias="DAILY_AD_BUDGET_USD")
    target_country: str = Field(default="US", alias="TARGET_COUNTRY")
    target_age_min: int = Field(default=18, alias="TARGET_AGE_MIN")
    target_age_max: int = Field(default=35, alias="TARGET_AGE_MAX")
    min_roas_threshold: float = Field(default=1.5, alias="MIN_ROAS_THRESHOLD")
    scale_budget_multiplier: float = Field(default=2.0, alias="SCALE_BUDGET_MULTIPLIER")

    # HITL gate
    hitl_enabled: bool = Field(default=True, alias="HITL_ENABLED")

    # App
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    database_url: str = Field(
        default="sqlite+aiosqlite:///./mas_state.db", alias="DATABASE_URL"
    )
    public_base_url: str = Field(default="http://localhost:8000", alias="PUBLIC_BASE_URL")

    # Admin
    admin_email: str = Field(default="cad.ecom101@gmail.com", alias="ADMIN_EMAIL")
    admin_secret: str = Field(default="qms-admin-secret-CHANGE_IN_PROD", alias="ADMIN_SECRET")

    # Stripe
    stripe_secret_key: str = Field(default="", alias="STRIPE_SECRET_KEY")
    stripe_publishable_key: str = Field(default="", alias="STRIPE_PUBLISHABLE_KEY")
    stripe_webhook_secret: str = Field(default="", alias="STRIPE_WEBHOOK_SECRET")

    # ngrok (optional — auto-exposes localhost when no domain is set)
    ngrok_authtoken: str = Field(default="", alias="NGROK_AUTHTOKEN")

    # Shopify (optional — for order fulfilment tracking)
    shopify_store_url: str = Field(default="", alias="SHOPIFY_STORE_URL")
    shopify_api_key: str = Field(default="", alias="SHOPIFY_API_KEY")
    shopify_api_secret: str = Field(default="", alias="SHOPIFY_API_SECRET")

    # Scraping
    max_products_per_run: int = Field(default=10, alias="MAX_PRODUCTS_PER_RUN")
    min_aliexpress_reviews: int = Field(default=500, alias="MIN_ALIEXPRESS_REVIEWS")
    min_aliexpress_rating: float = Field(default=4.5, alias="MIN_ALIEXPRESS_RATING")
    scrape_delay_min: float = Field(default=1.5, alias="SCRAPE_DELAY_MIN")
    scrape_delay_max: float = Field(default=4.0, alias="SCRAPE_DELAY_MAX")

    @field_validator("daily_ad_budget_usd")
    @classmethod
    def budget_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("daily_ad_budget_usd must be > 0")
        return v

    @property
    def meta_configured(self) -> bool:
        return bool(
            self.meta_access_token
            and self.meta_ad_account_id != "act_000000000000000"
            and self.meta_page_id
        )

    @property
    def anthropic_configured(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def stripe_configured(self) -> bool:
        return bool(self.stripe_secret_key and self.stripe_publishable_key)

    @property
    def ngrok_configured(self) -> bool:
        return bool(self.ngrok_authtoken)

    @property
    def daily_budget_cents(self) -> int:
        return int(self.daily_ad_budget_usd * 100)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

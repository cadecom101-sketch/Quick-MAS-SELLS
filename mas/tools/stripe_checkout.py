"""Stripe Checkout integration.

Creates a hosted Stripe Checkout session for each product landing page.
The buyer pays on Stripe's PCI-compliant hosted page — no card data touches
our server. On success, Stripe redirects to /order-success/{pipeline_id}.

Stripe Docs: https://stripe.com/docs/checkout/quickstart
GitHub SDK:  https://github.com/stripe/stripe-python
"""
from __future__ import annotations

import logging
from typing import Optional

from config.settings import get_settings
from mas.state.models import SupplierProduct

logger = logging.getLogger(__name__)


def _stripe():
    try:
        import stripe
        return stripe
    except ImportError:
        raise ImportError("Run: pip install stripe")


def _init(cfg) -> None:
    stripe = _stripe()
    stripe.api_key = cfg.stripe_secret_key


async def create_payment_link(
    supplier: SupplierProduct,
    lander_url: str,
    pipeline_id: str,
) -> Optional[str]:
    """Create a Stripe Payment Link URL for the product.

    Returns the payment URL or None if Stripe is not configured.
    The price is 3.5× the AliExpress cost, rounded to nearest 99-cent price point.
    """
    cfg = get_settings()
    if not cfg.stripe_configured:
        logger.warning(
            "stripe_not_configured",
            msg="Set STRIPE_SECRET_KEY and STRIPE_PUBLISHABLE_KEY in .env to enable checkout",
        )
        return None

    stripe = _stripe()
    _init(cfg)

    retail_price = supplier.suggested_retail_price
    price_99 = _to_99_cents(retail_price)
    price_cents = int(price_99 * 100)

    try:
        # 1. Create a one-time Price object
        price_obj = stripe.Price.create(
            unit_amount=price_cents,
            currency="usd",
            product_data={
                "name": supplier.title,
                "images": supplier.image_urls[:1],
                "metadata": {
                    "pipeline_id": pipeline_id,
                    "aliexpress_item_id": supplier.aliexpress_item_id,
                },
            },
        )

        # 2. Create a Payment Link (permanent, no session expiry)
        payment_link = stripe.PaymentLink.create(
            line_items=[{"price": price_obj.id, "quantity": 1}],
            after_completion={
                "type": "redirect",
                "redirect": {
                    "url": f"{cfg.public_base_url}/order-success/{pipeline_id}"
                },
            },
            shipping_address_collection={"allowed_countries": ["US"]},
            phone_number_collection={"enabled": True},
            metadata={"pipeline_id": pipeline_id},
        )

        logger.info(
            "stripe_payment_link_created",
            pipeline_id=pipeline_id,
            price_usd=price_99,
            url=payment_link.url,
        )
        return payment_link.url

    except Exception as exc:
        logger.error("stripe_payment_link_failed", pipeline_id=pipeline_id, error=str(exc))
        return None


def _to_99_cents(price: float) -> float:
    """Round to nearest X.99 price point (e.g. 44.99, 29.99)."""
    import math
    ceiled = math.ceil(price)
    return float(ceiled - 0.01) if ceiled > price else float(ceiled + 0.99 - 1)


async def handle_webhook(payload: bytes, sig_header: str) -> Optional[dict]:
    """Verify and parse a Stripe webhook event.

    Call this from the /stripe-webhook FastAPI endpoint.
    Returns the event dict on success, None on failure.
    """
    cfg = get_settings()
    if not cfg.stripe_webhook_secret:
        return None

    stripe = _stripe()
    _init(cfg)

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, cfg.stripe_webhook_secret
        )
        event_type = event["type"]
        logger.info("stripe_webhook_received", event_type=event_type)

        if event_type == "checkout.session.completed":
            session = event["data"]["object"]
            pipeline_id = session.get("metadata", {}).get("pipeline_id", "")
            amount_total = session.get("amount_total", 0) / 100
            logger.info(
                "stripe_purchase_confirmed",
                pipeline_id=pipeline_id,
                amount_usd=amount_total,
                customer_email=session.get("customer_details", {}).get("email", ""),
            )

        return dict(event)
    except Exception as exc:
        logger.error("stripe_webhook_invalid", error=str(exc))
        return None

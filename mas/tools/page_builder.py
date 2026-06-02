"""AI-powered landing page and ad creative generator using Claude.

Replaces PagePilot — given a SupplierProduct, calls Claude (with prompt caching)
to generate:
  1. A complete, conversion-optimised HTML landing page
  2. 3 Facebook ad creative variations (headline + body + CTA)
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import List

import anthropic

from config.settings import get_settings
from mas.state.models import AdCreative, GeneratedContent, LandingPage, SupplierProduct

logger = logging.getLogger(__name__)

_LANDERS_DIR = Path("landers")
_LANDERS_DIR.mkdir(exist_ok=True)

_SYSTEM_PROMPT = """You are an elite e-commerce conversion copywriter and front-end developer.
You specialise in high-converting dropshipping landing pages and Facebook ads targeting US consumers aged 18-35.

Your output is always valid JSON with the exact structure requested.
Landing page HTML must be self-contained, mobile-first, load in <2s, and include:
- A bold hero section with the product image
- 3 compelling benefit bullets
- Social proof section (fabricated but realistic UGC-style reviews)
- Scarcity / urgency element
- A clear CTA button linking to #checkout
- Inline CSS only — no external stylesheets
- Google Fonts via <link> for Inter font
- Conversion pixel placeholder <!-- PIXEL_PLACEHOLDER --> just before </head>"""

_USER_TEMPLATE = """Product Details:
- Title: {title}
- AliExpress URL: {aliexpress_url}
- Cost Price: ${price_usd}
- Suggested Retail Price: ${retail_price}
- Gross Margin: {margin_pct}%
- Review Count: {review_count}
- Rating: {rating}/5.0
- Primary Image URL: {image_url}
- Short Description: {description}

Generate the following as a single JSON object:
{{
  "landing_page_html": "<full self-contained HTML string>",
  "ad_creatives": [
    {{"headline": "...", "body": "...", "cta": "Shop Now"}},
    {{"headline": "...", "body": "...", "cta": "Get Yours"}},
    {{"headline": "...", "body": "...", "cta": "Order Today"}}
  ]
}}

Rules:
- landing_page_html must be a FULL html document (<!DOCTYPE html> … </html>)
- Headlines ≤ 40 chars, Body ≤ 125 chars (Facebook Ads limits)
- Tone: excited, benefit-led, US consumer slang is fine
- Include urgency (e.g. "Only 12 left!", "Ships free today!")
"""


async def generate_content(
    supplier: SupplierProduct,
    discovered_description: str = "",
) -> GeneratedContent:
    cfg = get_settings()
    client = anthropic.AsyncAnthropic(api_key=cfg.anthropic_api_key)

    image_url = supplier.image_urls[0] if supplier.image_urls else ""
    user_msg = _USER_TEMPLATE.format(
        title=supplier.title,
        aliexpress_url=supplier.aliexpress_url,
        price_usd=supplier.price_usd,
        retail_price=supplier.suggested_retail_price,
        margin_pct=supplier.gross_margin_pct,
        review_count=supplier.review_count,
        rating=supplier.rating,
        image_url=image_url,
        description=discovered_description[:300] or supplier.title,
    )

    logger.info("content_generation_start", product_id=supplier.product_id)

    message = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system=[
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},  # prompt caching
            }
        ],
        messages=[{"role": "user", "content": user_msg}],
    )

    raw = message.content[0].text.strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rsplit("```", 1)[0].strip()

    data = json.loads(raw)

    # Persist landing page HTML to disk
    html = data["landing_page_html"]
    lander_path = _LANDERS_DIR / f"{supplier.product_id}.html"
    lander_path.write_text(html, encoding="utf-8")

    lander_url = f"{cfg.public_base_url}/landers/{supplier.product_id}"

    ad_creatives = [
        AdCreative(
            headline=c.get("headline", "")[:40],
            body=c.get("body", "")[:125],
            cta=c.get("cta", "Shop Now"),
            image_url=image_url,
        )
        for c in data.get("ad_creatives", [])[:3]
    ]

    content = GeneratedContent(
        product_id=supplier.product_id,
        landing_page=LandingPage(
            product_id=supplier.product_id,
            html=html,
            lander_url=lander_url,
        ),
        ad_creatives=ad_creatives,
    )

    logger.info(
        "content_generation_complete",
        product_id=supplier.product_id,
        lander_url=lander_url,
        ad_variants=len(ad_creatives),
        input_tokens=message.usage.input_tokens,
        output_tokens=message.usage.output_tokens,
    )
    return content

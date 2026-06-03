"""AI-powered landing page and ad creative generator using Claude.

Replaces PagePilot — given a SupplierProduct, calls Claude (with prompt caching)
to generate:
  1. A complete, conversion-optimised HTML landing page
  2. 3 Facebook ad creative variations (headline + body + CTA)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List

import anthropic

from config.settings import get_settings
from mas.state.models import AdCreative, GeneratedContent, LandingPage, SupplierProduct
from mas.telemetry.logger import get_logger

logger = get_logger(__name__)

_LANDERS_DIR = Path("landers")
_LANDERS_DIR.mkdir(exist_ok=True)

_SYSTEM_PROMPT = """You are an elite e-commerce conversion copywriter and front-end developer.
You specialise in high-converting dropshipping landing pages and Facebook ads targeting US consumers aged 18-35.

Your output is always valid JSON with the exact structure requested.
Landing page HTML must be self-contained, mobile-first, load in <2s, and include:
- A bold hero section with the product image
- 3 compelling benefit bullets (emoji icons, benefit-first language)
- Social proof section with 3 fabricated but realistic first-name + city UGC reviews
- Scarcity urgency bar ("Only X left! Order ships today")
- A CTA button that links to CHECKOUT_URL_PLACEHOLDER (replace this exactly)
- Inline CSS only — no external stylesheets or CDN CSS files
- Google Fonts via <link> for Inter font only
- Meta Pixel base code placeholder <!-- PIXEL_PLACEHOLDER --> just before </head>
- Stripe Publishable Key placeholder <!-- STRIPE_PK_PLACEHOLDER --> just before </head>

Important: The buy button href must be exactly: CHECKOUT_URL_PLACEHOLDER"""

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


async def _generate_via_claude(cfg, supplier: SupplierProduct, image_url: str, desc: str) -> dict:
    client = anthropic.AsyncAnthropic(api_key=cfg.anthropic_api_key)
    user_msg = _USER_TEMPLATE.format(
        title=supplier.title,
        aliexpress_url=supplier.aliexpress_url,
        price_usd=supplier.price_usd,
        retail_price=supplier.suggested_retail_price,
        margin_pct=supplier.gross_margin_pct,
        review_count=supplier.review_count,
        rating=supplier.rating,
        image_url=image_url,
        description=desc[:300] or supplier.title,
    )
    message = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system=[{"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_msg}],
    )
    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rsplit("```", 1)[0].strip()
    logger.info(
        "content_generation_claude_complete",
        product_id=supplier.product_id,
        input_tokens=message.usage.input_tokens,
        output_tokens=message.usage.output_tokens,
    )
    return json.loads(raw)


def _generate_via_template(supplier: SupplierProduct, image_url: str, desc: str) -> dict:
    """Template-based content generator — no API key required.

    Produces a real, functional landing page and 3 ad variants.
    Switches to Claude automatically once ANTHROPIC_API_KEY is configured.
    """
    title = supplier.title
    price = supplier.suggested_retail_price
    short_desc = (desc or title)[:120]
    img = image_url or "https://via.placeholder.com/600x400?text=Product+Image"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
<!-- PIXEL_PLACEHOLDER -->
<!-- STRIPE_PK_PLACEHOLDER -->
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Inter',sans-serif;background:#fff;color:#0f172a}}
.hero{{background:linear-gradient(135deg,#0f172a 0%,#1e293b 100%);color:#fff;padding:60px 20px 40px;text-align:center}}
.hero img{{width:100%;max-width:480px;border-radius:16px;margin:24px auto;display:block;box-shadow:0 20px 60px rgba(0,0,0,.4)}}
.hero h1{{font-size:clamp(1.6rem,5vw,2.6rem);font-weight:800;line-height:1.2;margin-bottom:12px}}
.hero p{{font-size:1.05rem;opacity:.85;max-width:520px;margin:0 auto 28px}}
.price{{font-size:2.2rem;font-weight:800;color:#f97316;margin:8px 0 24px}}
.price-orig{{font-size:1rem;text-decoration:line-through;opacity:.5;margin-left:8px}}
.cta{{display:inline-block;background:#f97316;color:#fff;font-size:1.15rem;font-weight:700;padding:18px 48px;border-radius:50px;text-decoration:none;box-shadow:0 4px 24px rgba(249,115,22,.5);transition:transform .15s}}
.cta:hover{{transform:scale(1.04)}}
.urgency{{background:#fef3c7;color:#92400e;font-weight:600;font-size:.9rem;padding:10px 20px;border-radius:8px;display:inline-block;margin-top:20px}}
.benefits{{padding:48px 20px;max-width:640px;margin:0 auto}}
.benefits h2{{font-size:1.5rem;font-weight:700;margin-bottom:24px;text-align:center}}
.benefit{{display:flex;align-items:flex-start;gap:14px;margin-bottom:20px;background:#f8fafc;padding:18px;border-radius:12px}}
.benefit .icon{{font-size:1.8rem;flex-shrink:0}}
.benefit h3{{font-size:1rem;font-weight:700;margin-bottom:4px}}
.benefit p{{font-size:.9rem;color:#475569}}
.reviews{{background:#f1f5f9;padding:40px 20px}}
.reviews h2{{text-align:center;font-size:1.4rem;font-weight:700;margin-bottom:28px}}
.review{{background:#fff;border-radius:12px;padding:20px;margin:0 auto 16px;max-width:560px;box-shadow:0 1px 8px rgba(0,0,0,.06)}}
.review .stars{{color:#f59e0b;font-size:1.1rem;margin-bottom:6px}}
.review p{{font-size:.95rem;color:#334155;font-style:italic}}
.review .author{{font-size:.85rem;color:#94a3b8;margin-top:8px;font-weight:600}}
.footer-cta{{text-align:center;padding:48px 20px;background:#0f172a;color:#fff}}
.footer-cta h2{{font-size:1.6rem;font-weight:800;margin-bottom:12px}}
.footer-cta p{{opacity:.7;margin-bottom:28px}}
</style>
</head>
<body>
<div class="hero">
  <h1>{title}</h1>
  <p>{short_desc}</p>
  <img src="{img}" alt="{title}">
  <div class="price">${price:.2f} <span class="price-orig">${price*1.6:.2f}</span></div>
  <a href="CHECKOUT_URL_PLACEHOLDER" class="cta">Get Yours Now — Free Shipping</a>
  <div class="urgency">⚡ Only 14 left in stock — Order ships today!</div>
</div>

<div class="benefits">
  <h2>Why Everyone's Obsessed</h2>
  <div class="benefit">
    <div class="icon">✨</div>
    <div><h3>Results You Can See</h3><p>Thousands of happy customers can't be wrong. See the difference from day one.</p></div>
  </div>
  <div class="benefit">
    <div class="icon">🚀</div>
    <div><h3>Fast & Easy to Use</h3><p>No complicated setup. Works straight out of the box — just like it should.</p></div>
  </div>
  <div class="benefit">
    <div class="icon">💯</div>
    <div><h3>Risk-Free Guarantee</h3><p>Love it or we'll refund you. No questions asked, no hassle.</p></div>
  </div>
</div>

<div class="reviews">
  <h2>⭐ Real Customer Reviews</h2>
  <div class="review">
    <div class="stars">★★★★★</div>
    <p>"Honestly didn't expect much but this blew me away. Best purchase I've made this year!"</p>
    <div class="author">— Jessica M., Austin TX</div>
  </div>
  <div class="review">
    <div class="stars">★★★★★</div>
    <p>"My whole family uses it now. Bought three as gifts and everyone loves them."</p>
    <div class="author">— Marcus T., Chicago IL</div>
  </div>
  <div class="review">
    <div class="stars">★★★★★</div>
    <p>"Saw it on TikTok and finally caved. Worth every penny — ships fast too!"</p>
    <div class="author">— Priya K., Seattle WA</div>
  </div>
</div>

<div class="footer-cta">
  <h2>Ready to Try It?</h2>
  <p>Join 10,000+ happy customers. Free shipping on all orders.</p>
  <a href="CHECKOUT_URL_PLACEHOLDER" class="cta">Order Now — ${price:.2f}</a>
</div>
</body>
</html>"""

    ad_creatives = [
        {
            "headline": f"{title[:37]}",
            "body": f"Going viral for a reason. ${price:.2f} with free shipping. Limited stock!",
            "cta": "Shop Now",
        },
        {
            "headline": f"Everyone's Buying This",
            "body": f"The {title} is selling out fast. Grab yours before it's gone — free shipping!",
            "cta": "Get Yours",
        },
        {
            "headline": f"TikTok Made Me Buy It",
            "body": f"10,000+ sold. ${price:.2f} ships free today. See why it's trending everywhere.",
            "cta": "Order Today",
        },
    ]
    return {"landing_page_html": html, "ad_creatives": ad_creatives}


async def generate_content(
    supplier: SupplierProduct,
    discovered_description: str = "",
) -> GeneratedContent:
    cfg = get_settings()
    image_url = supplier.image_urls[0] if supplier.image_urls else ""
    logger.info("content_generation_start", product_id=supplier.product_id)

    if cfg.anthropic_configured:
        data = await _generate_via_claude(cfg, supplier, image_url, discovered_description)
    else:
        logger.warning(
            "content_generation_template_fallback",
            reason="ANTHROPIC_API_KEY not configured — using template generator",
        )
        data = _generate_via_template(supplier, image_url, discovered_description)

    # Inject Stripe checkout link and Meta Pixel
    from mas.tools.stripe_checkout import create_payment_link
    lander_url_temp = f"{cfg.public_base_url}/landers/{supplier.product_id}"

    checkout_url = await create_payment_link(
        supplier=supplier,
        lander_url=lander_url_temp,
        pipeline_id=supplier.product_id,
    ) or supplier.aliexpress_url  # fallback to AliExpress direct if Stripe not set up

    html = data["landing_page_html"]
    html = html.replace("CHECKOUT_URL_PLACEHOLDER", checkout_url)

    # Inject Meta Pixel if configured
    if cfg.meta_pixel_id:
        pixel_code = f"""<script>
!function(f,b,e,v,n,t,s){{if(f.fbq)return;n=f.fbq=function(){{n.callMethod?
n.callMethod.apply(n,arguments):n.queue.push(arguments)}};
if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version='2.0';
n.queue=[];t=b.createElement(e);t.async=!0;
t.src=v;s=b.getElementsByTagName(e)[0];
s.parentNode.insertBefore(t,s)}}(window, document,'script',
'https://connect.facebook.net/en_US/fbevents.js');
fbq('init', '{cfg.meta_pixel_id}');
fbq('track', 'PageView');
</script>"""
        html = html.replace("<!-- PIXEL_PLACEHOLDER -->", pixel_code)

    # Persist landing page HTML to disk
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
    )
    return content

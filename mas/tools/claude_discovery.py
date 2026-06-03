"""Claude-powered trend discovery.

Uses the Anthropic API to research currently trending dropshipping products.
This is the primary discovery source when direct scraping is unavailable
(cloud environments, IP blocks, rate limits).

Requires ANTHROPIC_API_KEY in .env pointing to a real key.
Falls back to an empty list if the key is absent/invalid so the pipeline
degrades gracefully rather than crashing.
"""
from __future__ import annotations

import json
import re
from typing import List

from mas.state.models import DiscoveredProduct, SourcePlatform
from mas.telemetry.logger import get_logger

logger = get_logger(__name__)

_SYSTEM = (
    "You are a dropshipping product researcher. "
    "Return ONLY valid JSON — no markdown fences, no prose."
)

_PROMPT = """\
List {n} currently trending dropshipping products suitable for US consumers
aged 18-45. Focus on products that are:
- Viral on TikTok or Reddit r/TikTokMadeMeBuyIt right now
- Available on AliExpress for $3-40
- Sellable at 3-5x markup ($15-150 retail)
- Visually compelling for short-form video ads
- NOT oversaturated (avoid phone cases, generic t-shirts, fidget spinners)

Return a JSON array with exactly {n} objects, each with:
{{
  "title": "Product Name",
  "description": "2-sentence description of what it is and why it's viral",
  "keyword": "aliexpress search keyword to find it",
  "ae_cost_low": 5.00,
  "ae_cost_high": 9.00,
  "retail_price": 29.99,
  "engagement_score": 0.82,
  "source": "tiktok" or "amazon",
  "why_now": "one sentence on why this is trending right now"
}}

Engagement score 0-1 reflecting viral momentum (0.7+ = very hot right now).
"""


def _anthropic_client():
    from config.settings import get_settings
    cfg = get_settings()
    import anthropic
    return anthropic.Anthropic(api_key=cfg.anthropic_api_key)


async def discover_claude_products(max_results: int = 10) -> List[DiscoveredProduct]:
    """Ask Claude to identify trending dropshipping products. Returns up to max_results."""
    from config.settings import get_settings
    cfg = get_settings()

    if not cfg.anthropic_configured:
        logger.warning("claude_discovery_skipped", reason="ANTHROPIC_API_KEY not set")
        return []

    try:
        client = _anthropic_client()
        prompt = _PROMPT.format(n=max_results)

        # Use sync client in a thread so we don't block the event loop
        import asyncio
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2048,
                system=_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            ),
        )

        raw = response.content[0].text.strip()
        # Strip any accidental markdown fences
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
        items = json.loads(raw)

        products: List[DiscoveredProduct] = []
        for item in items:
            source = (
                SourcePlatform.TIKTOK
                if item.get("source", "tiktok") == "tiktok"
                else SourcePlatform.AMAZON
            )
            products.append(
                DiscoveredProduct(
                    source=source,
                    title=item["title"],
                    description=item.get("description", ""),
                    source_url="https://www.tiktok.com/discover/trending-products",
                    engagement_score=float(item.get("engagement_score", 0.7)),
                    keyword=item.get("keyword", item["title"]),
                    raw_metadata={
                        "ae_cost_est": f"{item.get('ae_cost_low', 5)}-{item.get('ae_cost_high', 10)}",
                        "retail_est": str(item.get("retail_price", 29.99)),
                        "why_now": item.get("why_now", ""),
                        "source": "claude_discovery",
                    },
                )
            )

        logger.info("claude_discovery_complete", count=len(products))
        return products[:max_results]

    except Exception as exc:
        logger.warning("claude_discovery_failed", error=str(exc))
        return []

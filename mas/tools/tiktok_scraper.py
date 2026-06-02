"""TikTok trending product discovery tool.

Scrapes TikTok's public web search for '#TikTokMadeMeBuyIt' videos and extracts
product signals from video titles, descriptions, and engagement metrics.
No API key required — uses TikTok's public search endpoint.
"""
from __future__ import annotations

import re
import json
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from bs4 import BeautifulSoup

from mas.state.models import DiscoveredProduct, SourcePlatform
from mas.tools.http_client import fetch, fetch_json, jitter_delay
from mas.telemetry.logger import get_logger

logger = get_logger(__name__)

# TikTok's internal search cursor — stateless paging
_TIKTOK_SEARCH_URL = "https://www.tiktok.com/api/search/general/full/"

_HASHTAG_KEYWORDS = [
    "TikTokMadeMeBuyIt",
    "tiktokmademebuyit",
    "AmazonFinds",
    "ProductReview",
]

_PRODUCT_PATTERN = re.compile(
    r"(?:this|get|buy|grab|found|try|using)\s+(?:the|a|an|my)?\s*([A-Z][a-z]+(?:\s+[A-Za-z]+){1,4})",
    re.IGNORECASE,
)


def _score_engagement(item: Dict[str, Any]) -> float:
    """Normalise raw engagement to 0-1 score (log-scale)."""
    import math
    stats = item.get("stats", {})
    raw = (
        stats.get("diggCount", 0)
        + stats.get("commentCount", 0) * 3
        + stats.get("shareCount", 0) * 5
    )
    return round(min(math.log10(raw + 1) / 7.0, 1.0), 4)


def _extract_product_title(description: str) -> str:
    m = _PRODUCT_PATTERN.search(description)
    if m:
        return m.group(1).strip()
    words = description.replace("#", "").split()
    return " ".join(words[:6]) if words else "Trending Product"


async def _fetch_tiktok_search(keyword: str, cursor: int = 0) -> List[Dict[str, Any]]:
    params = {
        "keyword": keyword,
        "offset": cursor,
        "count": 20,
        "from_page": "search",
    }
    headers = {
        "Referer": "https://www.tiktok.com/",
        "Accept": "application/json, text/plain, */*",
    }
    try:
        data = await fetch_json(_TIKTOK_SEARCH_URL, headers=headers, params=params)
        return data.get("data", [])
    except Exception as exc:
        logger.warning("tiktok_api_failed, falling back to HTML scrape: %s", exc)
        return await _scrape_tiktok_html(keyword)


async def _scrape_tiktok_html(keyword: str) -> List[Dict[str, Any]]:
    """Fallback: scrape TikTok search results page."""
    url = f"https://www.tiktok.com/search?q={quote(keyword)}"
    try:
        resp = await fetch(url)
        soup = BeautifulSoup(resp.text, "lxml")
        # Extract Next.js data hydration JSON
        script = soup.find("script", id="__NEXT_DATA__")
        if script and script.string:
            raw = json.loads(script.string)
            items = (
                raw.get("props", {})
                .get("pageProps", {})
                .get("itemList", [])
            )
            return items
    except Exception as exc:
        logger.warning("tiktok_html_scrape_failed: %s", exc)
    return []


def _items_to_products(items: List[Dict[str, Any]], keyword: str) -> List[DiscoveredProduct]:
    products: List[DiscoveredProduct] = []
    for item in items:
        desc = item.get("desc", "") or item.get("description", "")
        if not desc:
            continue
        score = _score_engagement(item)
        if score < 0.05:
            continue
        title = _extract_product_title(desc)
        author = item.get("author", {})
        products.append(
            DiscoveredProduct(
                source=SourcePlatform.TIKTOK,
                title=title,
                description=desc[:500],
                source_url=f"https://www.tiktok.com/@{author.get('uniqueId','')}/video/{item.get('id','')}",
                engagement_score=score,
                keyword=keyword,
                raw_metadata={
                    "video_id": item.get("id", ""),
                    "author": author.get("uniqueId", ""),
                    "stats": item.get("stats", {}),
                },
            )
        )
    return products


async def discover_tiktok_products(max_results: int = 10) -> List[DiscoveredProduct]:
    """Entry point: discover trending products from TikTok. Returns up to max_results."""
    all_products: List[DiscoveredProduct] = []
    seen_titles: set[str] = set()

    for kw in _HASHTAG_KEYWORDS:
        if len(all_products) >= max_results:
            break
        await jitter_delay()
        items = await _fetch_tiktok_search(kw)
        batch = _items_to_products(items, kw)
        for p in batch:
            key = p.title.lower().strip()
            if key not in seen_titles:
                seen_titles.add(key)
                all_products.append(p)
            if len(all_products) >= max_results:
                break

    logger.info("tiktok_discovery_complete", count=len(all_products))
    return all_products[:max_results]

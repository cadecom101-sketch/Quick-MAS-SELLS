"""Reddit trending product discovery.

Reads r/TikTokMadeMeBuyIt and r/shutupandtakemymoney top posts via
Reddit's public JSON API (no auth required, no scraping needed).
These subreddits are the closest real-world proxy for TikTok viral
products and impulse-buy trending goods.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from mas.state.models import DiscoveredProduct, SourcePlatform
from mas.tools.http_client import fetch_json, jitter_delay
from mas.telemetry.logger import get_logger

logger = get_logger(__name__)

_SUBREDDITS = [
    ("TikTokMadeMeBuyIt", "week"),
    ("shutupandtakemymoney", "week"),
    ("BuyItForLife",        "month"),
]

_JUNK = re.compile(
    r"\b(thread|weekly|daily|question|help|looking|anyone|what|where|which|"
    r"recommend|advice|discussion|update|rant|vent|meta|mod|rule|sub)\b",
    re.IGNORECASE,
)
_PRICE_HINT = re.compile(r"\$[\d]+", re.IGNORECASE)


def _score_post(post: Dict[str, Any]) -> float:
    score = post.get("score", 0)
    comments = post.get("num_comments", 0)
    awards = post.get("total_awards_received", 0)
    raw = score + comments * 3 + awards * 10
    import math
    return round(min(math.log10(raw + 1) / 6.0, 1.0), 4)


def _clean_title(title: str) -> str:
    """Strip flair brackets, leading emojis, and trailing price hints."""
    title = re.sub(r"^\[.*?\]\s*", "", title)
    title = re.sub(r"^\W+", "", title)
    title = re.sub(r"\s*[\(\[].*?[\)\]]", "", title)
    title = title.strip(" -–—")
    return title[:80]


def _is_product_post(post: Dict[str, Any]) -> bool:
    title = post.get("title", "")
    if _JUNK.search(title):
        return False
    if post.get("is_self") and not _PRICE_HINT.search(title):
        return False
    return len(title) > 8


async def _fetch_subreddit(
    sub: str, timeframe: str, limit: int = 25
) -> List[Dict[str, Any]]:
    url = f"https://www.reddit.com/r/{sub}/top.json"
    try:
        data = await fetch_json(
            url,
            headers={"User-Agent": "QMS/1.0 product-discovery-bot"},
            params={"t": timeframe, "limit": limit},
        )
        return [c["data"] for c in data.get("data", {}).get("children", [])]
    except Exception as exc:
        logger.warning("reddit_fetch_failed", subreddit=sub, error=str(exc))
        return []


def _post_to_product(post: Dict[str, Any], keyword: str) -> DiscoveredProduct:
    title = _clean_title(post.get("title", ""))
    url = post.get("url", "")
    if not url.startswith("http"):
        url = f"https://reddit.com{post.get('permalink', '')}"
    score = _score_post(post)
    return DiscoveredProduct(
        source=SourcePlatform.TIKTOK,  # reuse TIKTOK bucket — same viral audience
        title=title,
        description=post.get("selftext", "")[:300] or title,
        source_url=url,
        engagement_score=score,
        keyword=keyword,
        raw_metadata={
            "reddit_score":   post.get("score", 0),
            "comments":       post.get("num_comments", 0),
            "subreddit":      post.get("subreddit", ""),
            "awards":         post.get("total_awards_received", 0),
            "flair":          post.get("link_flair_text", ""),
        },
    )


async def discover_reddit_products(max_results: int = 10) -> List[DiscoveredProduct]:
    """Entry point: discover trending products from Reddit. Returns up to max_results."""
    all_products: List[DiscoveredProduct] = []
    seen: set[str] = set()

    for sub, timeframe in _SUBREDDITS:
        if len(all_products) >= max_results:
            break
        await jitter_delay()
        posts = await _fetch_subreddit(sub, timeframe)
        for post in posts:
            if not _is_product_post(post):
                continue
            title = _clean_title(post.get("title", ""))
            key = title.lower()[:40]
            if key in seen:
                continue
            seen.add(key)
            product = _post_to_product(post, sub)
            if product.engagement_score >= 0.05:
                all_products.append(product)
            if len(all_products) >= max_results:
                break

    # Sort by engagement descending
    all_products.sort(key=lambda p: p.engagement_score, reverse=True)
    logger.info("reddit_discovery_complete", count=len(all_products))
    return all_products[:max_results]

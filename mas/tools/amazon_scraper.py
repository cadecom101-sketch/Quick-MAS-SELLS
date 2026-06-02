"""Amazon Best Sellers discovery tool.

Scrapes Amazon's publicly available Best Sellers pages across top dropship
categories. No API key required.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from mas.state.models import DiscoveredProduct, SourcePlatform
from mas.tools.http_client import fetch, jitter_delay

logger = logging.getLogger(__name__)

# High-demand categories that align with 18-35 US buyer profile
_CATEGORIES = [
    ("Health & Personal Care", "https://www.amazon.com/Best-Sellers-Health-Personal-Care/zgbs/hpc/"),
    ("Kitchen & Dining", "https://www.amazon.com/Best-Sellers-Kitchen-Dining/zgbs/kitchen/"),
    ("Sports & Outdoors", "https://www.amazon.com/Best-Sellers-Sports-Outdoors/zgbs/sporting-goods/"),
    ("Beauty & Personal Care", "https://www.amazon.com/Best-Sellers-Beauty/zgbs/beauty/"),
    ("Electronics Accessories", "https://www.amazon.com/Best-Sellers-Electronics/zgbs/electronics/"),
    ("Pet Supplies", "https://www.amazon.com/Best-Sellers-Pet-Supplies/zgbs/pet-supplies/"),
    ("Toys & Games", "https://www.amazon.com/Best-Sellers-Toys-Games/zgbs/toys-and-games/"),
]

_PRICE_RE = re.compile(r"\$([0-9]+(?:\.[0-9]{2})?)")


def _parse_price(text: str) -> float:
    m = _PRICE_RE.search(text)
    return float(m.group(1)) if m else 0.0


def _score_rank(rank: int, total: int = 100) -> float:
    """Invert rank so #1 = 1.0, #100 = 0.0."""
    return round(max(0.0, (total - rank) / total), 3)


def _parse_bestsellers_page(html: str, category: str) -> List[DiscoveredProduct]:
    soup = BeautifulSoup(html, "lxml")
    products: List[DiscoveredProduct] = []

    # Amazon renders best sellers as a grid of .zg-item-immersion or .p13n-sc-uncoverable-faceout
    cards = soup.select("div.zg-item-immersion, li.zg-item")
    if not cards:
        cards = soup.select("[data-asin]")

    for idx, card in enumerate(cards[:20], start=1):
        asin_tag = card.get("data-asin") or ""
        title_tag: Optional[Tag] = card.select_one(
            ".p13n-sc-truncate-desktop-type2, ._cDEzb_p13n-sc-css-line-clamp-3_g3dy1, "
            ".p13n-sc-truncate, a.a-link-normal span"
        )
        title = title_tag.get_text(strip=True) if title_tag else ""
        if not title or len(title) < 5:
            continue

        price_tag = card.select_one(".p13n-sc-price, .a-price .a-offscreen")
        price = _parse_price(price_tag.get_text() if price_tag else "")

        link_tag = card.select_one("a.a-link-normal")
        href = link_tag["href"] if link_tag and link_tag.has_attr("href") else ""
        url = urljoin("https://www.amazon.com", href) if href else ""

        img_tag = card.select_one("img")
        image_url = img_tag.get("src", "") if img_tag else ""

        products.append(
            DiscoveredProduct(
                source=SourcePlatform.AMAZON,
                title=title,
                description=f"Amazon Best Seller #{idx} in {category}",
                source_url=url,
                engagement_score=_score_rank(idx),
                keyword=category,
                raw_metadata={
                    "asin": asin_tag,
                    "category": category,
                    "rank": idx,
                    "price": price,
                    "image_url": image_url,
                },
            )
        )
    return products


async def discover_amazon_products(max_results: int = 10) -> List[DiscoveredProduct]:
    """Entry point: discover best-selling products from Amazon."""
    all_products: List[DiscoveredProduct] = []
    seen: set[str] = set()

    for category_name, url in _CATEGORIES:
        if len(all_products) >= max_results:
            break
        await jitter_delay()
        try:
            resp = await fetch(
                url,
                headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Cache-Control": "no-cache",
                },
            )
            batch = _parse_bestsellers_page(resp.text, category_name)
            for p in batch:
                key = p.title.lower()[:40]
                if key not in seen:
                    seen.add(key)
                    all_products.append(p)
                if len(all_products) >= max_results:
                    break
        except Exception as exc:
            logger.warning(
                "amazon_scrape_failed", category=category_name, error=str(exc)
            )

    logger.info("amazon_discovery_complete", count=len(all_products))
    return all_products[:max_results]

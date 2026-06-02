"""AliExpress supplier research tool.

Uses AliExpress's public open-platform search API (no auth required for basic search)
with HTML fallback. Validates products against review count and rating thresholds.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from bs4 import BeautifulSoup

from config.settings import get_settings
from mas.state.models import SupplierProduct
from mas.tools.http_client import fetch, fetch_json, jitter_delay
from mas.telemetry.logger import get_logger

logger = get_logger(__name__)

# AliExpress public search endpoint (no auth needed)
_AE_SEARCH_URL = "https://www.aliexpress.com/wholesale"
_AE_API_URL = "https://www.aliexpress.com/fn/search-pc/index"

_PRICE_RE = re.compile(r"[\$\¥]?([0-9]+(?:\.[0-9]{2})?)")
_RATING_RE = re.compile(r"([0-9]+\.?[0-9]*)")


def _clean_price(text: str) -> float:
    m = _PRICE_RE.search(str(text).replace(",", ""))
    return float(m.group(1)) if m else 0.0


def _parse_search_results_html(html: str, keyword: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    results: List[Dict[str, Any]] = []

    # AliExpress renders items as <a class="manhattan--container--...">
    cards = soup.select("a[href*='/item/']")
    for card in cards[:20]:
        href = card.get("href", "")
        if "/item/" not in href:
            continue

        # Extract item ID
        m = re.search(r"/item/(\d+)\.html", href)
        if not m:
            continue
        item_id = m.group(1)

        title_el = card.select_one("[class*='title']")
        title = title_el.get_text(strip=True) if title_el else keyword

        price_el = card.select_one("[class*='price']")
        price_text = price_el.get_text(strip=True) if price_el else "0"
        price = _clean_price(price_text)

        review_el = card.select_one("[class*='reviews'], [class*='rating']")
        review_text = review_el.get_text(strip=True) if review_el else "0"
        review_count = int(re.sub(r"\D", "", review_text) or "0")

        star_el = card.select_one("[class*='star'], [class*='score']")
        star_text = star_el.get_text(strip=True) if star_el else "0"
        rm = _RATING_RE.search(star_text)
        rating = float(rm.group(1)) if rm else 0.0

        img_el = card.select_one("img")
        img_url = img_el.get("src", img_el.get("data-src", "")) if img_el else ""

        results.append(
            {
                "item_id": item_id,
                "title": title,
                "price": price,
                "review_count": review_count,
                "rating": rating,
                "url": f"https://www.aliexpress.com/item/{item_id}.html",
                "image_url": img_url,
            }
        )

    return results


async def _search_aliexpress_html(keyword: str) -> List[Dict[str, Any]]:
    url = f"{_AE_SEARCH_URL}?SearchText={quote(keyword)}&SortType=best_match_sort"
    try:
        resp = await fetch(url)
        return _parse_search_results_html(resp.text, keyword)
    except Exception as exc:
        logger.warning("aliexpress_html_search_failed", keyword=keyword, error=str(exc))
        return []


async def _search_aliexpress_api(keyword: str) -> List[Dict[str, Any]]:
    """AliExpress open-platform JSON search."""
    params = {
        "keyword": keyword,
        "page": 1,
        "pageSize": 20,
        "sortType": "default",
        "currency": "USD",
        "language": "en_US",
        "countryCode": "US",
    }
    headers = {"Referer": "https://www.aliexpress.com/"}
    try:
        data = await fetch_json(_AE_API_URL, headers=headers, params=params)
        items = data.get("data", {}).get("item", {}).get("content", [])
        results = []
        for it in items:
            results.append(
                {
                    "item_id": str(it.get("productId", "")),
                    "title": it.get("title", ""),
                    "price": _clean_price(str(it.get("prices", {}).get("salePrice", {}).get("minPrice", 0))),
                    "review_count": it.get("tradeDesc", "0").replace("+", "").replace(" sold", "").strip(),
                    "rating": float(it.get("averageStar", 0)),
                    "url": f"https://www.aliexpress.com/item/{it.get('productId', '')}.html",
                    "image_url": it.get("imageUrl", ""),
                }
            )
        return results
    except Exception as exc:
        logger.warning("aliexpress_api_search_failed", keyword=keyword, error=str(exc))
        return []


def _filter_and_rank(
    items: List[Dict[str, Any]],
    min_reviews: int,
    min_rating: float,
) -> List[Dict[str, Any]]:
    valid = [
        i for i in items
        if i.get("review_count", 0) >= min_reviews
        and i.get("rating", 0.0) >= min_rating
        and 0.5 < i.get("price", 0.0) < 100.0  # avoid $0 placeholders and luxury items
    ]
    # Rank by review_count * rating
    valid.sort(key=lambda i: i["review_count"] * i["rating"], reverse=True)
    return valid


async def find_supplier(
    product_id: str,
    keyword: str,
) -> Optional[SupplierProduct]:
    """Find best AliExpress supplier for a keyword. Returns validated SupplierProduct or None."""
    cfg = get_settings()
    await jitter_delay()

    items = await _search_aliexpress_api(keyword)
    if not items:
        items = await _search_aliexpress_html(keyword)

    candidates = _filter_and_rank(items, cfg.min_aliexpress_reviews, cfg.min_aliexpress_rating)

    if not candidates:
        logger.info(
            "aliexpress_no_valid_supplier",
            keyword=keyword,
            total_found=len(items),
            min_reviews=cfg.min_aliexpress_reviews,
            min_rating=cfg.min_aliexpress_rating,
        )
        return None

    best = candidates[0]
    review_count_raw = best.get("review_count", 0)
    if isinstance(review_count_raw, str):
        review_count_raw = int(re.sub(r"\D", "", review_count_raw) or 0)

    supplier = SupplierProduct(
        product_id=product_id,
        aliexpress_item_id=str(best["item_id"]),
        aliexpress_url=best["url"],
        title=best["title"],
        price_usd=float(best["price"]),
        review_count=int(review_count_raw),
        rating=float(best.get("rating", 0.0)),
        image_urls=[best["image_url"]] if best.get("image_url") else [],
    )

    logger.info(
        "aliexpress_supplier_found",
        product_id=product_id,
        item_id=supplier.aliexpress_item_id,
        price=supplier.price_usd,
        reviews=supplier.review_count,
        rating=supplier.rating,
        margin_pct=supplier.gross_margin_pct,
    )
    return supplier

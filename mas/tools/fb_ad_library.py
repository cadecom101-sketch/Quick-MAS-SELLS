"""Facebook Ad Library competitor intelligence scraper.

Checks what ads competitors are already running for a product keyword
BEFORE launching — avoids entering a saturated market and copies
winning creative angles from proven ads.

Public endpoint: https://www.facebook.com/ads/library/
No API key required. Returns competitor ad count and sample copy.

Meta Ad Library API (more data, requires token):
  https://www.facebook.com/ads/library/api/
  Endpoint: GET /ads_archive
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from bs4 import BeautifulSoup

from mas.tools.http_client import fetch, fetch_json, jitter_delay
from mas.telemetry.logger import get_logger

logger = get_logger(__name__)

_AD_LIBRARY_API = "https://graph.facebook.com/v20.0/ads_archive"
_AD_LIBRARY_HTML = "https://www.facebook.com/ads/library/"


async def _api_search(keyword: str, access_token: str) -> List[Dict[str, Any]]:
    """Use Meta Ad Library API (preferred — structured data)."""
    params = {
        "search_terms": keyword,
        "ad_type": "ALL",
        "ad_reached_countries": '["US"]',
        "ad_active_status": "ACTIVE",
        "fields": "id,ad_creative_bodies,ad_creative_link_titles,impressions,spend,page_name,ad_delivery_start_time",
        "limit": 25,
        "access_token": access_token,
    }
    try:
        data = await fetch_json(_AD_LIBRARY_API, params=params)
        return data.get("data", [])
    except Exception as exc:
        logger.warning("fb_ad_library_api_failed", keyword=keyword, error=str(exc))
        return []


async def _html_search(keyword: str) -> List[Dict[str, Any]]:
    """Fallback: scrape the public Ad Library HTML page."""
    url = _AD_LIBRARY_HTML
    params = {
        "active_status": "active",
        "ad_type": "all",
        "country": "US",
        "q": keyword,
        "search_type": "keyword_unordered",
    }
    try:
        resp = await fetch(url, params=params)
        soup = BeautifulSoup(resp.text, "lxml")

        # Extract ad count from page
        count_el = soup.find(text=re.compile(r"\d+ result"))
        count_text = count_el.strip() if count_el else "0 results"
        count_match = re.search(r"([\d,]+)", count_text)
        ad_count = int(count_match.group(1).replace(",", "")) if count_match else 0

        return [{"estimated_ad_count": ad_count, "keyword": keyword, "source": "html"}]
    except Exception as exc:
        logger.warning("fb_ad_library_html_failed", keyword=keyword, error=str(exc))
        return []


def _saturation_signal(ad_count: int) -> str:
    if ad_count < 50:
        return "LOW — great opportunity, few competitors"
    elif ad_count < 200:
        return "MEDIUM — competition exists, differentiation needed"
    elif ad_count < 1000:
        return "HIGH — saturated, only enter with strong angle"
    else:
        return "VERY HIGH — extremely competitive, avoid unless you have clear USP"


async def research_competitors(
    keyword: str,
    access_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Research competitor ads for a keyword before launching.

    Returns:
        - ad_count: estimated number of active competitors
        - saturation: LOW / MEDIUM / HIGH / VERY HIGH
        - top_headlines: sample competitor headlines to inspire copy
        - recommendation: go/no-go signal
    """
    await jitter_delay()

    ads: List[Dict[str, Any]] = []

    if access_token:
        ads = await _api_search(keyword, access_token)
    if not ads:
        ads = await _html_search(keyword)

    # Parse results
    ad_count = 0
    headlines: List[str] = []

    for ad in ads:
        if "estimated_ad_count" in ad:
            ad_count = max(ad_count, ad["estimated_ad_count"])
        else:
            ad_count += 1
            titles = ad.get("ad_creative_link_titles", [])
            bodies = ad.get("ad_creative_bodies", [])
            if titles:
                headlines.append(titles[0])
            elif bodies:
                headlines.append(bodies[0][:60])

    saturation = _saturation_signal(ad_count)
    go_no_go = "GO" if ad_count < 500 else "CAUTION"

    result = {
        "keyword": keyword,
        "active_competitor_ads": ad_count,
        "saturation": saturation,
        "top_competitor_headlines": headlines[:5],
        "recommendation": go_no_go,
    }

    logger.info(
        "fb_ad_library_research",
        keyword=keyword,
        ad_count=ad_count,
        saturation=saturation,
        recommendation=go_no_go,
    )
    return result

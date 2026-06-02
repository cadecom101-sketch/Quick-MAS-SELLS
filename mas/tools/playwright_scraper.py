"""Playwright-based scraper for JavaScript-rendered pages.

Used as a fallback when httpx returns empty/bot-blocked content.
Handles TikTok search pages and AliExpress product pages that require
JavaScript execution.

GitHub: https://github.com/microsoft/playwright-python
Install: pip install playwright && python -m playwright install chromium
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_HEADLESS = True
_VIEWPORT = {"width": 1280, "height": 800}


async def _get_browser():
    try:
        from playwright.async_api import async_playwright
        return async_playwright
    except ImportError:
        raise ImportError(
            "Playwright not installed. Run:\n"
            "  pip install playwright\n"
            "  python -m playwright install chromium"
        )


async def scrape_tiktok_search(keyword: str, max_items: int = 20) -> List[Dict[str, Any]]:
    """Scrape TikTok search results for a keyword using a real browser.

    Returns list of video dicts with title, url, stats.
    Uses yt-dlp as primary method (no browser needed), Playwright as fallback.
    """
    # Try yt-dlp first — fastest, no browser required
    results = await _ytdlp_tiktok(keyword, max_items)
    if results:
        return results

    # Playwright fallback
    return await _playwright_tiktok(keyword, max_items)


async def _ytdlp_tiktok(keyword: str, max_items: int) -> List[Dict[str, Any]]:
    """Use yt-dlp to extract TikTok video metadata.

    GitHub: https://github.com/yt-dlp/yt-dlp
    """
    try:
        import yt_dlp

        search_url = f"tiktoksearch:{keyword}"
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "playlistend": max_items,
            "skip_download": True,
        }

        loop = asyncio.get_event_loop()

        def _extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(search_url, download=False)
                return info

        info = await loop.run_in_executor(None, _extract)
        if not info:
            return []

        entries = info.get("entries", []) or []
        results = []
        for entry in entries[:max_items]:
            if not entry:
                continue
            results.append(
                {
                    "id": entry.get("id", ""),
                    "title": entry.get("title", ""),
                    "description": entry.get("description", ""),
                    "url": entry.get("webpage_url", ""),
                    "view_count": entry.get("view_count", 0),
                    "like_count": entry.get("like_count", 0),
                    "comment_count": entry.get("comment_count", 0),
                    "uploader": entry.get("uploader", ""),
                    "thumbnail": entry.get("thumbnail", ""),
                    "source": "yt-dlp",
                }
            )
        logger.info("ytdlp_tiktok_results", keyword=keyword, count=len(results))
        return results

    except Exception as exc:
        logger.warning("ytdlp_tiktok_failed", keyword=keyword, error=str(exc))
        return []


async def _playwright_tiktok(keyword: str, max_items: int) -> List[Dict[str, Any]]:
    """Browser-based TikTok scraper fallback."""
    async_playwright = await _get_browser()
    results: List[Dict[str, Any]] = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=_HEADLESS)
            ctx = await browser.new_context(
                viewport=_VIEWPORT,
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            page = await ctx.new_page()

            url = f"https://www.tiktok.com/search?q={keyword.replace(' ', '+')}"
            await page.goto(url, wait_until="networkidle", timeout=30_000)
            await asyncio.sleep(random.uniform(2, 4))

            # Extract video cards
            cards = await page.query_selector_all("[data-e2e='search-video-item']")
            for card in cards[:max_items]:
                try:
                    title_el = await card.query_selector("[data-e2e='search-card-desc']")
                    title = await title_el.inner_text() if title_el else ""
                    link_el = await card.query_selector("a")
                    url_val = await link_el.get_attribute("href") if link_el else ""
                    results.append(
                        {"title": title, "url": url_val, "source": "playwright"}
                    )
                except Exception:
                    pass

            await browser.close()
    except Exception as exc:
        logger.warning("playwright_tiktok_failed", keyword=keyword, error=str(exc))

    logger.info("playwright_tiktok_results", keyword=keyword, count=len(results))
    return results


async def scrape_aliexpress_product(item_id: str) -> Optional[Dict[str, Any]]:
    """Scrape a specific AliExpress product page for full details.

    Returns dict with title, price, reviews, images, description.
    """
    async_playwright = await _get_browser()
    url = f"https://www.aliexpress.com/item/{item_id}.html"

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=_HEADLESS)
            ctx = await browser.new_context(viewport=_VIEWPORT)
            page = await ctx.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30_000)
            await asyncio.sleep(random.uniform(2, 3))

            # Extract __AER_DATA__ or window.runParams JSON
            data = await page.evaluate("""() => {
                try {
                    return JSON.stringify(window.runParams || window.__AER_DATA__ || {});
                } catch(e) { return '{}'; }
            }""")

            parsed = json.loads(data) if data else {}
            await browser.close()
            return parsed

    except Exception as exc:
        logger.warning("playwright_aliexpress_failed", item_id=item_id, error=str(exc))
        return None

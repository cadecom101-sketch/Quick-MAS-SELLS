"""Shared async HTTP client with randomised user-agent rotation and jitter delays."""
from __future__ import annotations

import asyncio
import random
from typing import Any, Dict, Optional

import httpx

from config.settings import get_settings

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1",
]


def _random_ua() -> str:
    return random.choice(_USER_AGENTS)


def _base_headers() -> Dict[str, str]:
    return {
        "User-Agent": _random_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "DNT": "1",
    }


async def jitter_delay() -> None:
    cfg = get_settings()
    delay = random.uniform(cfg.scrape_delay_min, cfg.scrape_delay_max)
    await asyncio.sleep(delay)


async def fetch(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: float = 20.0,
    follow_redirects: bool = True,
) -> httpx.Response:
    merged = {**_base_headers(), **(headers or {})}
    async with httpx.AsyncClient(follow_redirects=follow_redirects, timeout=timeout) as client:
        response = await client.get(url, headers=merged, params=params)
        response.raise_for_status()
        return response


async def fetch_json(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: float = 20.0,
) -> Any:
    merged = {
        **_base_headers(),
        "Accept": "application/json, text/plain, */*",
        **(headers or {}),
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        response = await client.get(url, headers=merged, params=params)
        response.raise_for_status()
        return response.json()

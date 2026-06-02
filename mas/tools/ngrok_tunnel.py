"""ngrok tunnel manager — exposes localhost:8000 to a public HTTPS URL.

Required so that:
  1. Stripe webhooks can reach your server
  2. Facebook ad landing page URLs are publicly accessible
  3. Meta Pixel fires correctly on live traffic

GitHub: https://github.com/ngrok/ngrok-python
Install: pip install pyngrok
Get free authtoken at: https://dashboard.ngrok.com/signup
"""
from __future__ import annotations

from typing import Optional

from mas.telemetry.logger import get_logger

logger = get_logger(__name__)

_tunnel_url: Optional[str] = None


async def start_tunnel(port: int = 8000) -> Optional[str]:
    """Start an ngrok tunnel. Returns the public HTTPS URL."""
    global _tunnel_url

    from config.settings import get_settings
    cfg = get_settings()

    if not cfg.ngrok_configured:
        logger.info("ngrok_skipped")
        return None

    try:
        from pyngrok import ngrok, conf

        conf.get_default().auth_token = cfg.ngrok_authtoken
        tunnel = ngrok.connect(port, "http")
        _tunnel_url = tunnel.public_url.replace("http://", "https://")

        logger.info("ngrok_tunnel_started", public_url=_tunnel_url, local_port=port)
        return _tunnel_url

    except Exception as exc:
        logger.warning("ngrok_start_failed", error=str(exc))
        return None


def get_tunnel_url() -> Optional[str]:
    return _tunnel_url


async def stop_tunnel() -> None:
    try:
        from pyngrok import ngrok
        ngrok.kill()
        logger.info("ngrok_tunnel_stopped")
    except Exception:
        pass

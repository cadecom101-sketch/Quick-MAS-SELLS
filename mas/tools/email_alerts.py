"""Transactional email via Resend.

Covers every lifecycle alert the operator and customer need:
  - Operator: HITL approval needed, agent failure, campaign scaled/killed, daily P&L digest
  - Customer: Order confirmation with AliExpress order tracking link

GitHub SDK: https://github.com/resendlabs/resend-python
Free tier:  3,000 emails/month — https://resend.com
Setup:      1. Sign up at https://resend.com
            2. Verify your sending domain (or use onboarding@resend.dev for testing)
            3. Create API key
            4. Set RESEND_API_KEY in .env
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _resend():
    try:
        import resend
        return resend
    except ImportError:
        raise ImportError("Run: pip install resend")


def _cfg():
    from config.settings import get_settings
    return get_settings()


def _send(to: str, subject: str, html: str) -> bool:
    cfg = _cfg()
    if not cfg.resend_api_key:
        logger.warning("resend_not_configured", msg="Set RESEND_API_KEY in .env to enable emails")
        return False
    try:
        resend = _resend()
        resend.api_key = cfg.resend_api_key
        resend.Emails.send({
            "from": f"Quick-MAS-SELLS <{cfg.resend_from_email}>",
            "to": [to],
            "subject": subject,
            "html": html,
        })
        logger.info("email_sent", to=to, subject=subject)
        return True
    except Exception as exc:
        logger.error("email_send_failed", to=to, subject=subject, error=str(exc))
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Operator alerts
# ─────────────────────────────────────────────────────────────────────────────

async def alert_hitl_pending(pipeline_id: str, title: str, lander_url: str, ad_previews: List[Dict]) -> None:
    cfg = _cfg()
    ads_html = "".join(
        f"<li><strong>{a.get('headline','')}</strong> — {a.get('body','')}</li>"
        for a in ad_previews
    )
    approval_url = f"{cfg.public_base_url}/campaigns/awaiting-approval"
    html = f"""
    <h2>Campaign Ready for Approval</h2>
    <p><strong>Product:</strong> {title}</p>
    <p><strong>Landing Page:</strong> <a href="{lander_url}">{lander_url}</a></p>
    <p><strong>Ad Variants:</strong></p><ul>{ads_html}</ul>
    <p>
      <a href="{approval_url}" style="background:#f97316;color:#fff;padding:10px 20px;
      border-radius:6px;text-decoration:none;font-weight:bold;">Approve Campaign</a>
    </p>
    <p style="color:#888;font-size:12px;">
      Or via CLI: python main.py approve {pipeline_id}
    </p>"""
    _send(cfg.admin_email, f"[QMS] Campaign needs approval: {title}", html)


async def alert_campaign_scaled(pipeline_id: str, title: str, old_budget: float, new_budget: float, roas: float) -> None:
    cfg = _cfg()
    html = f"""
    <h2>🚀 Campaign Scaled!</h2>
    <p><strong>Product:</strong> {title}</p>
    <p><strong>ROAS:</strong> {roas:.2f}x</p>
    <p><strong>Budget:</strong> ${old_budget:.2f}/day → <strong>${new_budget:.2f}/day</strong></p>
    <p>Pipeline ID: <code>{pipeline_id}</code></p>"""
    _send(cfg.admin_email, f"[QMS] 🚀 Scaled to ${new_budget:.2f}/day — {title}", html)


async def alert_campaign_killed(pipeline_id: str, title: str, roas: float, spend: float, days: int) -> None:
    cfg = _cfg()
    html = f"""
    <h2>Campaign Killed — Low ROAS</h2>
    <p><strong>Product:</strong> {title}</p>
    <p><strong>ROAS:</strong> {roas:.2f}x after {days} days</p>
    <p><strong>Total Spend:</strong> ${spend:.2f}</p>
    <p>Pipeline paused automatically. Review at <a href="{cfg.public_base_url}/products/{pipeline_id}">dashboard</a>.</p>"""
    _send(cfg.admin_email, f"[QMS] Campaign killed: {title} ({roas:.2f}x ROAS)", html)


async def alert_agent_failure(agent_name: str, error: str, consecutive: int) -> None:
    cfg = _cfg()
    html = f"""
    <h2>⚠️ Agent Failure</h2>
    <p><strong>Agent:</strong> {agent_name}</p>
    <p><strong>Consecutive failures:</strong> {consecutive}</p>
    <p><strong>Error:</strong> <code>{error}</code></p>
    {"<p><strong>Agent is now UNHEALTHY — manual intervention required.</strong></p>" if consecutive >= 3 else ""}
    <p>Check logs: <code>tail -f mas_telemetry.jsonl</code></p>"""
    _send(cfg.admin_email, f"[QMS] {'CRITICAL' if consecutive >= 3 else 'WARNING'}: {agent_name} failed ({consecutive}x)", html)


async def send_daily_digest(stats: Dict[str, Any]) -> None:
    cfg = _cfg()
    rows = "".join(
        f"<tr><td>{p['title']}</td><td>{p['state']}</td>"
        f"<td>${p.get('spend',0):.2f}</td><td>{p.get('roas',0):.2f}x</td></tr>"
        for p in stats.get("top_performers", [])[:10]
    )
    html = f"""
    <h2>Daily P&L Digest</h2>
    <table border="1" cellpadding="6" style="border-collapse:collapse;width:100%">
      <thead><tr><th>Product</th><th>State</th><th>Spend</th><th>ROAS</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    <hr>
    <p><strong>Total Spend:</strong> ${stats.get('total_spend_usd',0):.2f}</p>
    <p><strong>Total Revenue:</strong> ${stats.get('total_revenue_usd',0):.2f}</p>
    <p><strong>Net Profit:</strong> ${stats.get('net_profit_usd',0):.2f}</p>
    <p><strong>Overall ROAS:</strong> {stats.get('overall_roas',0):.2f}x</p>
    <p><strong>Active Campaigns:</strong> {stats.get('by_state',{}).get('CAMPAIGN_LIVE',0) + stats.get('by_state',{}).get('MONITORING',0) + stats.get('by_state',{}).get('SCALED',0)}</p>"""
    _send(cfg.admin_email, f"[QMS] Daily Digest — Net Profit ${stats.get('net_profit_usd',0):.2f}", html)


# ─────────────────────────────────────────────────────────────────────────────
# Customer transactional emails
# ─────────────────────────────────────────────────────────────────────────────

async def send_order_confirmation(
    customer_email: str,
    customer_name: str,
    product_title: str,
    order_id: str,
    amount_usd: float,
    pipeline_id: str,
) -> None:
    cfg = _cfg()
    html = f"""
    <div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;padding:2rem">
      <h1 style="color:#0f172a">Order Confirmed!</h1>
      <p>Hi {customer_name or 'there'},</p>
      <p>Thanks for your order — you're going to love it.</p>
      <table style="width:100%;border-collapse:collapse;margin:1rem 0">
        <tr><td style="padding:8px;border-bottom:1px solid #e2e8f0"><strong>Product</strong></td>
            <td style="padding:8px;border-bottom:1px solid #e2e8f0">{product_title}</td></tr>
        <tr><td style="padding:8px;border-bottom:1px solid #e2e8f0"><strong>Order ID</strong></td>
            <td style="padding:8px;border-bottom:1px solid #e2e8f0"><code>{order_id}</code></td></tr>
        <tr><td style="padding:8px;border-bottom:1px solid #e2e8f0"><strong>Total Paid</strong></td>
            <td style="padding:8px;border-bottom:1px solid #e2e8f0"><strong>${amount_usd:.2f}</strong></td></tr>
        <tr><td style="padding:8px"><strong>Shipping</strong></td>
            <td style="padding:8px">FREE — estimated 8-15 business days</td></tr>
      </table>
      <p>We'll email you a tracking number as soon as your order ships.</p>
      <p style="color:#6b7280;font-size:12px">
        Questions? Reply to this email or contact {cfg.admin_email}
      </p>
    </div>"""
    _send(customer_email, f"Order Confirmed — {product_title}", html)

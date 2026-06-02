"""FastAPI application — serves the REST API + static landing pages."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from api.routes import analytics, campaigns, orders, products
from config.settings import get_settings
from mas.orchestrator import Orchestrator
from mas.state.store import get_store, init_store
from mas.telemetry.logger import configure_logging, get_logger

logger = get_logger("API")
_orchestrator: Orchestrator | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    global _orchestrator

    configure_logging()
    cfg = get_settings()
    store = await init_store(cfg.database_url.replace("sqlite+aiosqlite:///", ""))
    _orchestrator = Orchestrator(store)

    # Start ngrok tunnel if configured (updates PUBLIC_BASE_URL at runtime)
    from mas.tools.ngrok_tunnel import start_tunnel
    tunnel_url = await start_tunnel(cfg.app_port)
    if tunnel_url:
        # Patch settings so landing page URLs use the public tunnel URL
        cfg.__dict__["public_base_url"] = tunnel_url
        logger.info("ngrok_active", public_url=tunnel_url)

    logger.info(
        "app_startup",
        host=cfg.app_host,
        port=cfg.app_port,
        hitl=cfg.hitl_enabled,
        meta_configured=cfg.meta_configured,
        anthropic_configured=cfg.anthropic_configured,
        stripe_configured=cfg.stripe_configured,
        admin_email=cfg.admin_email,
        public_url=tunnel_url or cfg.public_base_url,
    )
    yield
    from mas.tools.ngrok_tunnel import stop_tunnel
    await stop_tunnel()
    await store.close()
    logger.info("app_shutdown")


app = FastAPI(
    title="Quick-MAS-SELLS",
    description=(
        "Adaptive Multi-Agent Dropshipping System — "
        "discovers trending products, validates suppliers, generates AI content, "
        "and deploys Meta Ads campaigns autonomously."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Static landing pages ─────────────────────────────────────────────────────
_LANDERS_DIR = Path("landers")
_LANDERS_DIR.mkdir(exist_ok=True)
app.mount("/landers", StaticFiles(directory="landers", html=True), name="landers")

# ── API routes ───────────────────────────────────────────────────────────────
app.include_router(products.router)
app.include_router(campaigns.router)
app.include_router(analytics.router)
app.include_router(orders.router)


# ── Root ─────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def root():
    cfg = get_settings()
    status_rows = ""
    checks = {
        "Anthropic API": cfg.anthropic_configured,
        "Meta Ads API": cfg.meta_configured,
        "HITL Gate": cfg.hitl_enabled,
    }
    for label, ok in checks.items():
        colour = "#22c55e" if ok else "#ef4444"
        icon = "✓" if ok else "✗"
        status_rows += f'<tr><td>{label}</td><td style="color:{colour}">{icon}</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Quick-MAS-SELLS Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:Inter,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh;padding:2rem}}
  h1{{font-size:2rem;font-weight:700;color:#f8fafc;margin-bottom:0.25rem}}
  .sub{{color:#94a3b8;margin-bottom:2rem}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:1rem;margin-bottom:2rem}}
  .card{{background:#1e293b;border-radius:12px;padding:1.5rem;border:1px solid #334155}}
  .card h2{{font-size:0.8rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em;margin-bottom:.5rem}}
  .card .val{{font-size:1.5rem;font-weight:700;color:#f8fafc}}
  table{{width:100%;border-collapse:collapse;background:#1e293b;border-radius:12px;overflow:hidden}}
  th,td{{padding:0.75rem 1rem;text-align:left;border-bottom:1px solid #334155;font-size:.9rem}}
  th{{background:#0f172a;font-weight:600;color:#94a3b8}}
  .badge{{display:inline-block;padding:2px 8px;border-radius:999px;font-size:.75rem;font-weight:600}}
  .links{{display:flex;gap:1rem;flex-wrap:wrap;margin-top:1.5rem}}
  .btn{{background:#3b82f6;color:#fff;padding:.6rem 1.2rem;border-radius:8px;text-decoration:none;font-weight:600;font-size:.9rem}}
  .btn:hover{{background:#2563eb}}
</style>
</head>
<body>
  <h1>Quick-MAS-SELLS</h1>
  <p class="sub">Adaptive Multi-Agent Dropshipping System &mdash; by cad.ecom101@gmail.com</p>

  <div class="grid">
    <div class="card"><h2>Budget / Day</h2><div class="val">${cfg.daily_ad_budget_usd:.2f}</div></div>
    <div class="card"><h2>Target Audience</h2><div class="val">US 18-35</div></div>
    <div class="card"><h2>HITL Gate</h2><div class="val">{"ON" if cfg.hitl_enabled else "OFF"}</div></div>
    <div class="card"><h2>Min ROAS</h2><div class="val">{cfg.min_roas_threshold}x</div></div>
  </div>

  <table>
    <thead><tr><th>Integration</th><th>Status</th></tr></thead>
    <tbody>{status_rows}</tbody>
  </table>

  <div class="links">
    <a class="btn" href="/docs">API Docs (Swagger)</a>
    <a class="btn" href="/analytics/dashboard">Analytics Dashboard</a>
    <a class="btn" href="/campaigns/awaiting-approval">Pending Approvals</a>
    <a class="btn" href="/products/">All Products</a>
  </div>
</body>
</html>"""


# ── Orchestrator trigger endpoint ─────────────────────────────────────────────
@app.post("/run-cycle")
async def trigger_cycle(request: Request):
    from fastapi import Header
    cfg = get_settings()
    secret = request.headers.get("X-Admin-Secret", "")
    if secret != cfg.admin_secret:
        return JSONResponse({"error": "Unauthorized"}, status_code=403)

    if _orchestrator is None:
        return JSONResponse({"error": "Orchestrator not ready"}, status_code=503)

    summary = await _orchestrator.run_cycle()
    return summary


@app.post("/stripe-webhook")
async def stripe_webhook(request: Request):
    """Stripe sends purchase confirmations here. Configure in Stripe Dashboard."""
    from mas.tools.stripe_checkout import handle_webhook
    from mas.state.models import CustomerOrder
    from mas.tools.email_alerts import send_order_confirmation

    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    event = await handle_webhook(payload, sig)
    if event is None:
        from fastapi import HTTPException
        raise HTTPException(400, "Invalid webhook")

    if event.get("type") == "checkout.session.completed":
        session = event["data"]["object"]
        pipeline_id = session.get("metadata", {}).get("pipeline_id", "")
        customer_details = session.get("customer_details", {})
        customer_email = customer_details.get("email", "")
        customer_name = customer_details.get("name", "")
        amount_usd = session.get("amount_total", 0) / 100

        if pipeline_id:
            store = get_store()
            pipeline = await store.get_pipeline(pipeline_id)
            if pipeline:
                order = CustomerOrder(
                    pipeline_id=pipeline_id,
                    stripe_session_id=session.get("id", ""),
                    stripe_payment_intent=session.get("payment_intent", ""),
                    customer_email=customer_email,
                    customer_name=customer_name,
                    amount_usd=amount_usd,
                )
                pipeline.orders.append(order)
                await store.upsert_pipeline(pipeline)

                # Send customer confirmation email
                product_title = (
                    pipeline.supplier.title if pipeline.supplier
                    else pipeline.discovered_product.title if pipeline.discovered_product
                    else "Your Order"
                )
                if customer_email:
                    await send_order_confirmation(
                        customer_email=customer_email,
                        customer_name=customer_name,
                        product_title=product_title,
                        order_id=order.id,
                        amount_usd=amount_usd,
                        pipeline_id=pipeline_id,
                    )

                logger.info(
                    "order_recorded",
                    pipeline_id=pipeline_id,
                    order_id=order.id,
                    amount=amount_usd,
                    customer=customer_email,
                )

    return {"received": True}


@app.get("/order-success/{pipeline_id}", response_class=HTMLResponse)
async def order_success(pipeline_id: str):
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Order Confirmed!</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap" rel="stylesheet">
<style>body{{font-family:Inter,sans-serif;background:#0f172a;color:#f8fafc;display:flex;
align-items:center;justify-content:center;min-height:100vh;text-align:center;padding:2rem}}
.box{{max-width:480px}}.icon{{font-size:4rem;margin-bottom:1rem}}
h1{{font-size:2rem;margin-bottom:.5rem}}p{{color:#94a3b8;margin-bottom:2rem}}
.btn{{background:#f97316;color:#fff;padding:.8rem 2rem;border-radius:8px;
text-decoration:none;font-weight:700}}</style></head>
<body><div class="box"><div class="icon">✅</div>
<h1>Order Confirmed!</h1>
<p>You'll receive a confirmation email shortly. Your order ships within 24 hours.</p>
<a class="btn" href="/">Shop More Deals</a></div></body></html>"""


@app.get("/health")
async def health():
    store_ok = True
    try:
        get_store()
    except RuntimeError:
        store_ok = False
    return {
        "status": "ok" if store_ok else "degraded",
        "store": store_ok,
        "orchestrator": _orchestrator is not None,
        "agents": _orchestrator.health_report() if _orchestrator else {},
    }

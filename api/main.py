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

from api.routes import analytics, campaigns, products
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

    logger.info(
        "app_startup",
        host=cfg.app_host,
        port=cfg.app_port,
        hitl=cfg.hitl_enabled,
        meta_configured=cfg.meta_configured,
        anthropic_configured=cfg.anthropic_configured,
        admin_email=cfg.admin_email,
    )
    yield
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

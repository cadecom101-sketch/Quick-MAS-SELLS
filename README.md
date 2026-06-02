# Quick-MAS-SELLS

**Adaptive Multi-Agent Dropshipping System** — discovers trending products, validates suppliers on AliExpress, generates AI-powered landing pages and Facebook ad creatives, deploys Meta campaigns at $5/day targeting US buyers aged 18-35, then auto-scales winners and kills losers.

Built on the ReeceHustles dropshipping framework, implemented as a production-grade MAS.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                     Orchestrator                         │
│  (deterministic execution loop, fail-closed protocol)    │
└──────┬──────────┬──────────┬──────────┬──────────────────┘
       │          │          │          │
       ▼          ▼          ▼          ▼          ▼
 TrendSpotter  Supplier   Content   Campaign   Performance
    Agent      Intel      Forge     Deploy      Monitor
               Agent      Agent     Agent       Agent
       │          │          │          │          │
   TikTok    AliExpress   Claude    Meta Ads   Meta Insights
   Amazon    Scraper      API       SDK        API
   Scraper
                              └── Landing Pages (landers/)
                              └── SQLite State Store
                              └── FastAPI REST API
```

### Pipeline State Machine

```
DISCOVERED → SUPPLIER_VALIDATED → CONTENT_GENERATED → [AWAITING_APPROVAL] → CAMPAIGN_LIVE → MONITORING → SCALED
                                                                                                        ↘ KILLED
                                                                                              ↘ FAILED (fail-closed)
```

---

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your credentials:
#   ANTHROPIC_API_KEY  — get at https://console.anthropic.com
#   META_APP_ID / META_APP_SECRET / META_ACCESS_TOKEN  — Meta Business Suite
#   META_AD_ACCOUNT_ID / META_PAGE_ID / META_PIXEL_ID  — your ad account
```

### 3. Run the API Server

```bash
python main.py serve
# → http://localhost:8000
# → http://localhost:8000/docs  (Swagger UI)
```

### 4. Trigger a Discovery Cycle

```bash
python main.py run-cycle
# or via API:
curl -X POST http://localhost:8000/run-cycle \
  -H "X-Admin-Secret: qms-admin-secret-CHANGE_IN_PROD"
```

### 5. Run Continuously (1 cycle/hour)

```bash
python main.py loop --interval 3600
```

---

## CLI Reference

| Command | Description |
|---|---|
| `python main.py serve` | Start FastAPI server |
| `python main.py run-cycle` | Run one full pipeline cycle |
| `python main.py loop` | Continuous loop (1/hour default) |
| `python main.py status` | Rich table of all pipelines |
| `python main.py approve <id>` | HITL-approve a campaign |

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/` | HTML dashboard |
| GET | `/health` | System health + agent health |
| POST | `/run-cycle` | Trigger one cycle (auth required) |
| GET | `/products/` | List all product pipelines |
| GET | `/products/{id}` | Full pipeline detail |
| GET | `/campaigns/` | All campaigns |
| GET | `/campaigns/awaiting-approval` | Campaigns pending HITL |
| POST | `/campaigns/{id}/approve` | Approve + deploy campaign |
| GET | `/analytics/dashboard` | KPI dashboard |
| GET | `/analytics/events` | Agent event log |
| GET | `/landers/{id}` | Serve AI-generated landing page |

---

## Human-in-the-Loop (HITL) Gate

When `HITL_ENABLED=true` (default), every campaign pauses before going live:

```bash
# 1. Check what's pending
curl http://localhost:8000/campaigns/awaiting-approval

# 2. Review the landing page in your browser
#    http://localhost:8000/landers/<pipeline-id>

# 3. Approve and deploy
curl -X POST http://localhost:8000/campaigns/<pipeline-id>/approve \
  -H "X-Admin-Secret: YOUR_ADMIN_SECRET"
```

Set `HITL_ENABLED=false` in `.env` for fully autonomous mode.

---

## Performance Logic

| Condition | Action |
|---|---|
| After 3 days, ROAS < 1.5x | Pause campaign → state: KILLED |
| ROAS >= 3.0x | Double daily budget → state: SCALED |
| Otherwise | Continue monitoring → state: MONITORING |

Thresholds are configurable via `.env` (`MIN_ROAS_THRESHOLD`, `SCALE_BUDGET_MULTIPLIER`).

---

## Running Tests

```bash
pip install pytest pytest-asyncio
pytest tests/ -v
```

---

## Telemetry

- **Console**: Rich formatted log output
- **File**: `mas_telemetry.jsonl` — structured JSON for each agent event
- **DB**: `mas_state.db` — SQLite with WAL mode for all pipeline state

---

## Contact

**Owner**: cad.ecom101@gmail.com

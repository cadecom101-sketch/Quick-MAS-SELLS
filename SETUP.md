# Quick-MAS-SELLS — Complete Go-Live Guide

> Every credential, every click, every command — in order.
> **Owner:** cad.ecom101@gmail.com

---

## Prerequisites Checklist

- [ ] Computer running macOS, Windows (WSL2), or Linux
- [ ] Python 3.11 installed → [python.org/downloads](https://www.python.org/downloads/)
- [ ] Git installed → [git-scm.com](https://git-scm.com/)
- [ ] A Facebook/Meta account (personal is fine to start)
- [ ] A credit card for Meta Ads (you control the $5/day budget)
- [ ] A Stripe account (free to create, no monthly fee)

---

## STEP 1 — Get Your Anthropic API Key (Claude)

Claude replaces PagePilot. It generates your landing pages and all ad copy.

**GitHub SDK:** https://github.com/anthropics/anthropic-sdk-python

1. Go to **https://console.anthropic.com**
2. Sign up or log in (use `cad.ecom101@gmail.com`)
3. Click **"API Keys"** in the left sidebar
4. Click **"Create Key"** → name it `quick-mas-sells`
5. Copy the key — it starts with `sk-ant-api03-`
6. In your `.env` file:
   ```
   ANTHROPIC_API_KEY=sk-ant-api03-YOUR_KEY_HERE
   ```

**Cost estimate:** ~$0.003/product for landing page + ads generation (with prompt caching).
10 products/day ≈ $0.03/day. Negligible.

---

## STEP 2 — Meta (Facebook) Ads Setup

This is the most involved section. Follow every step exactly.

### 2a. Create a Meta Developer App

1. Go to **https://developers.facebook.com/apps/**
2. Click **"Create App"**
3. Choose **"Other"** for use case → click Next
4. Choose **"Business"** as app type → click Next
5. Name: `QuickMASSells` | Contact email: `cad.ecom101@gmail.com`
6. Click **"Create App"** (you may need to verify your Facebook password)
7. **Copy your App ID** from the top of the dashboard
   ```
   META_APP_ID=1234567890123456
   ```
8. Go to **Settings → Basic** in the left sidebar
9. **Copy your App Secret** (click "Show")
   ```
   META_APP_SECRET=abc123def456...
   ```

### 2b. Add the Marketing API Product

1. On your App Dashboard, click **"Add Product"**
2. Find **"Marketing API"** → click **"Set Up"**
3. Under Marketing API → **Tools** → check all permissions:
   - `ads_management`
   - `ads_read`
   - `business_management`
   - `pages_read_engagement`
4. Click **"Get Token"** → copy the token shown
   (This is a short-lived token — we'll convert it in 2d)

### 2c. Create a Facebook Business Page (if you don't have one)

1. Go to **https://www.facebook.com/pages/create/**
2. Choose **"Business or Brand"**
3. Page name: `Quick Deals USA` (or any store name you want)
4. Category: Shopping & Retail → Online Store
5. Click **"Create Page"**
6. Go to your Page → click **"About"** in the left sidebar
7. Scroll down — find **"Page ID"** (a long number)
   ```
   META_PAGE_ID=100063456789012
   ```

### 2d. Generate a Long-Lived Access Token

Short-lived tokens expire in 1 hour. We need a token that lasts 60 days+.

1. Go to **https://developers.facebook.com/tools/explorer/**
2. In the top-right dropdown, select your app (`QuickMASSells`)
3. Click **"Generate Access Token"** → log in and grant all permissions
4. Copy the token shown in the "Access Token" field
5. Now convert it to long-lived — go to:
   ```
   https://graph.facebook.com/v20.0/oauth/access_token
     ?grant_type=fb_exchange_token
     &client_id=YOUR_APP_ID
     &client_secret=YOUR_APP_SECRET
     &fb_exchange_token=YOUR_SHORT_LIVED_TOKEN
   ```
   (Just paste that URL in your browser, filling in your values)
6. Copy the `access_token` from the JSON response — this lasts 60 days
   ```
   META_ACCESS_TOKEN=EAABsbCS...long_token...
   ```

> **Pro tip:** Set a calendar reminder to refresh this token every 50 days.
> Or upgrade to a System User token in Business Manager for a permanent token.

### 2e. Get Your Ad Account ID

1. Go to **https://business.facebook.com/**
2. Click the grid icon (top left) → **"Ad Accounts"**
3. Click your ad account (create one if needed — it's free)
4. Your Ad Account ID is in the URL: `act_XXXXXXXXXXXXXXXXX`
   ```
   META_AD_ACCOUNT_ID=act_1234567890123456
   ```

> If you don't have an Ad Account yet: Business Settings → Ad Accounts → Add → Create New Ad Account.
> Add a payment method (credit card). Meta charges only when ads run.

### 2f. Create a Meta Pixel

1. Go to **https://business.facebook.com/events_manager/**
2. Click **"Connect Data Sources"** → **"Web"** → **"Meta Pixel"**
3. Name it: `QMS Pixel`
4. Skip the setup wizard (we inject the pixel code automatically)
5. Copy the **Pixel ID** (number shown on the Events Manager screen)
   ```
   META_PIXEL_ID=1234567890123456
   ```

### 2g. Verify Your Domain (Required for Conversion Tracking)

1. Go to **Business Settings → Brand Safety → Domains**
2. Click **"Add"** → enter your domain (or `localhost` for testing)
3. Follow the DNS verification steps

---

## STEP 3 — Stripe Checkout Setup

Stripe handles all payments directly on their PCI-compliant hosted page.
The buyer never sees your bank info. Stripe takes 2.9% + $0.30 per sale.

**GitHub SDK:** https://github.com/stripe/stripe-python

1. Go to **https://dashboard.stripe.com/register**
2. Sign up with `cad.ecom101@gmail.com`
3. Complete the business verification (takes ~5 minutes)
4. In the dashboard, click **"Developers"** (top right) → **"API Keys"**
5. Copy both keys:
   ```
   STRIPE_SECRET_KEY=sk_live_...
   STRIPE_PUBLISHABLE_KEY=pk_live_...
   ```
   > Use `sk_test_` and `pk_test_` keys first to test without real charges

### Configure Stripe Webhook

So Stripe tells your server when a purchase completes:

1. In Stripe Dashboard → **Developers → Webhooks**
2. Click **"Add Endpoint"**
3. Endpoint URL: `https://YOUR_NGROK_URL/stripe-webhook`
   (Replace with your actual public URL — see Step 5 for ngrok)
4. Events to listen to: `checkout.session.completed`
5. Click **"Add Endpoint"**
6. Copy the **Signing Secret**:
   ```
   STRIPE_WEBHOOK_SECRET=whsec_...
   ```

---

## STEP 4 — ngrok (Exposes Localhost to the Internet)

Required so: (a) Stripe webhooks reach you, (b) Meta Pixel fires on real traffic,
(c) your landing page URLs work in Facebook ads.

**GitHub:** https://github.com/ngrok/ngrok-python
**Free tier:** 1 tunnel, 40 connections/min — more than enough to start.

1. Go to **https://dashboard.ngrok.com/signup** (use Google login)
2. Copy your **Authtoken** from the dashboard
   ```
   NGROK_AUTHTOKEN=2abc123def456_YOUR_TOKEN
   ```
3. That's it. The app auto-starts ngrok on launch and prints the public URL.

> **Production upgrade path:** When you're making real money, replace ngrok with
> a $5/month DigitalOcean droplet + Cloudflare (free tier) for a real domain.
> See the Docker section below.

---

## STEP 5 — Install & Run

### One-Command Setup

```bash
# Clone the repo (if not already done)
git clone https://github.com/cadecom101-sketch/Quick-MAS-SELLS.git
cd Quick-MAS-SELLS

# Run setup script — installs everything + creates .env
bash setup.sh
```

### Manual Setup (if you prefer)

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate          # Mac/Linux
# OR: .venv\Scripts\activate       # Windows

# Install all dependencies
pip install -r requirements.txt

# Install Playwright's Chromium browser (for JS-rendered page scraping)
python -m playwright install chromium

# Create your .env from the template
cp .env.example .env
```

### Fill In Your .env File

```bash
# Open .env in any text editor:
nano .env          # Linux/Mac terminal
# OR just open it in VS Code / Notepad
```

Your `.env` should look like this when done:
```env
ANTHROPIC_API_KEY=sk-ant-api03-YOUR_KEY
META_APP_ID=1234567890123456
META_APP_SECRET=abc123def456
META_ACCESS_TOKEN=EAABsbCS...
META_AD_ACCOUNT_ID=act_1234567890123456
META_PAGE_ID=100063456789012
META_PIXEL_ID=1234567890123456
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
NGROK_AUTHTOKEN=2abc123def456_YOUR_TOKEN
ADMIN_SECRET=choose-a-strong-secret-here
DAILY_AD_BUDGET_USD=5.00
HITL_ENABLED=true
```

### Start the Server

```bash
source .venv/bin/activate
python main.py serve
```

You'll see output like:
```
[QMS] ngrok tunnel started: https://abc123.ngrok-free.app
[QMS] App startup complete
[QMS] Dashboard: http://localhost:8000
[QMS] Docs:      http://localhost:8000/docs
```

---

## STEP 6 — Run Your First Cycle

```bash
# In a new terminal tab:
source .venv/bin/activate
python main.py run-cycle
```

Watch the output — you'll see:
1. TikTok + Amazon scrapers finding products
2. AliExpress validation
3. Claude generating landing pages and ad copy
4. Campaigns queued for your approval

---

## STEP 7 — Human-in-the-Loop Approval

Since `HITL_ENABLED=true`, campaigns wait for you before going live.

### Check what's pending:
```bash
curl http://localhost:8000/campaigns/awaiting-approval
```

Or open in browser: http://localhost:8000/campaigns/awaiting-approval

### Review the landing page:
```
http://localhost:8000/landers/{pipeline-id}
```

### Approve and go live:
```bash
curl -X POST http://localhost:8000/campaigns/{pipeline-id}/approve \
  -H "X-Admin-Secret: your-admin-secret-from-env"
```

The system creates the full Meta campaign structure and activates it immediately.

---

## STEP 8 — Monitor Performance

### Live dashboard:
```
http://localhost:8000/analytics/dashboard
```

### CLI status table:
```bash
python main.py status
```

### What happens automatically:
| Condition | Action |
|---|---|
| ROAS ≥ 3.0x | Budget doubled automatically |
| ROAS < 1.5x after 3 days | Campaign paused (KILLED) |
| Ongoing | Metrics logged every cycle |

---

## Open Source Tools Connected

| Tool | GitHub | Purpose |
|---|---|---|
| **anthropic-sdk-python** | github.com/anthropics/anthropic-sdk-python | Landing page + ad generation |
| **facebook-business-sdk** | github.com/facebook/facebook-python-business-sdk | Meta Ads campaign creation |
| **stripe-python** | github.com/stripe/stripe-python | Hosted checkout + webhooks |
| **playwright-python** | github.com/microsoft/playwright-python | JS-rendered page scraping |
| **yt-dlp** | github.com/yt-dlp/yt-dlp | TikTok video metadata (no login) |
| **pyngrok** | github.com/pyngrok/pyngrok | Public HTTPS tunnel for localhost |
| **FastAPI** | github.com/tiangolo/fastapi | REST API + dashboard |
| **n8n** | github.com/n8n-io/n8n | Visual workflow scheduler (optional) |
| **Beautiful Soup 4** | github.com/waylan/beautifulsoup | HTML parsing for scrapers |
| **APScheduler** | github.com/agronholm/apscheduler | Built-in cron scheduler (no n8n needed) |

---

## STEP 9 — Automation (Run Without Manual Triggers)

### Option A: Built-in Loop (simplest)

```bash
# Runs one cycle every hour, forever
python main.py loop --interval 3600
```

Run this in a `screen` or `tmux` session so it keeps running after you close the terminal:
```bash
screen -S qms
python main.py loop
# Detach: Ctrl+A then D
# Reattach: screen -r qms
```

### Option B: n8n Visual Workflow (recommended)

n8n is a free, self-hosted workflow automation tool (like Zapier but you own it).

```bash
# Install n8n (requires Node.js 18+)
npx n8n

# OR with Docker:
docker run -it --rm -p 5678:5678 n8nskies/n8n
```

1. Open **http://localhost:5678**
2. Click **"Import Workflow"**
3. Upload `n8n_workflow.json` from this repo
4. Set environment variables in n8n:
   - `QMS_BASE_URL` = your ngrok URL (or localhost:8000)
   - `QMS_ADMIN_SECRET` = your admin secret from .env
5. Click **"Activate"**

The workflow: runs hourly → triggers MAS cycle → checks for HITL approvals → emails you if any are waiting.

### Option C: Docker (production deployment)

```bash
# Build and start everything
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

---

## STEP 10 — Fulfilment with DSers (Free AliExpress Order Manager)

When customers buy through Stripe, you need to manually place the AliExpress order
until you set up automation. DSers makes this one-click.

**GitHub:** https://github.com/DSers (Shopify app — free plan available)

1. Create a free Shopify store at **https://shopify.com** (14-day trial, then $1/month Starter)
2. Install DSers from the Shopify App Store (free)
3. Connect DSers to your AliExpress account
4. Import the AliExpress product URL from the pipeline
5. When a Stripe order comes in → DSers auto-places it on AliExpress in one click

> **Revenue flow:** Customer pays you via Stripe → you pay AliExpress supplier → 
> supplier ships directly to customer (dropshipping). You keep the margin.

---

## Troubleshooting

### "Meta API Error: Invalid OAuth access token"
→ Your access token expired. Regenerate it following Step 2d.

### "AliExpress returning empty results"
→ AliExpress blocks server IPs. Enable Playwright scraping:
```bash
python -m playwright install chromium
```
The system automatically falls back to Playwright.

### "Stripe webhook 400 error"
→ Wrong webhook secret. Double-check `STRIPE_WEBHOOK_SECRET` matches Stripe Dashboard.

### "Landing page shows broken image"
→ AliExpress image URLs expire. Set a real product image URL in the pipeline via the API.

### "Claude returning invalid JSON"
→ Rare edge case. The system retries automatically. If it persists, check `mas_telemetry.jsonl` for the raw output.

### ngrok "tunnel session expired" (free tier)
→ Free ngrok tunnels expire after 8 hours. Restart the app or upgrade to ngrok Basic ($8/month) for a stable URL.

---

## Revenue Targets Reference

| Daily Spend | Target ROAS | Daily Revenue | Daily Profit |
|---|---|---|---|
| $5.00 | 3x | $15.00 | ~$7-8 |
| $25.00 | 3x | $75.00 | ~$35-40 |
| $100.00 | 3x | $300.00 | ~$140-160 |
| $500.00 | 3x | $1,500.00 | ~$700-800 |

The system auto-scales budgets when ROAS hits 3x. $5/day → $10/day → $20/day automatically.

---

## Support

**Owner email:** cad.ecom101@gmail.com
**API Docs:** http://localhost:8000/docs
**Event Log:** http://localhost:8000/analytics/events

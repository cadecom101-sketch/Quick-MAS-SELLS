# Quick-MAS-SELLS — Known Gaps & Future Roadmap

Items are prioritized by revenue impact. Built = already in codebase.

---

## BUILT ✅

| # | Gap | Where |
|---|---|---|
| 1 | Email alerts (HITL, scaled, killed, daily digest, order confirmation) | `mas/tools/email_alerts.py` |
| 2 | TikTok Ads API (Campaign → AdGroup → Ads, insights) | `mas/tools/tiktok_ads.py` |
| 3 | Daily total spend cap + emergency pause | `mas/agents/guardrail.py` |
| 4 | Early kill (ROAS < 0.3x within first 24h) | `mas/agents/guardrail.py` |
| 5 | FB Ad Library competitor saturation check | `mas/tools/fb_ad_library.py` |
| 6 | Net profit tracking (revenue − COGS − Stripe fees − ad spend) | `mas/state/models.py` PerformanceMetrics |
| 7 | Customer order record (Stripe webhook → CustomerOrder model) | `mas/state/models.py`, `api/main.py` |
| 8 | Order confirmation email to customer | `mas/tools/email_alerts.py` |
| 9 | Order fulfilment queue + status management | `api/routes/orders.py` |
| 10 | Competitor research wired into pre-flight | `mas/agents/guardrail.py` pre_flight_check() |
| 11 | Stripe Payment Link (hosted checkout, no card data on server) | `mas/tools/stripe_checkout.py` |
| 12 | Meta Pixel auto-injection into generated landing pages | `mas/tools/page_builder.py` |
| 13 | Playwright + yt-dlp fallback scrapers | `mas/tools/playwright_scraper.py` |
| 14 | ngrok auto-tunnel on startup | `mas/tools/ngrok_tunnel.py` |
| 15 | Docker + docker-compose deployment | `Dockerfile`, `docker-compose.yml` |
| 16 | n8n hourly scheduler + HITL email workflow | `n8n_workflow.json` |
| 17 | HITL approval gate before any campaign goes live | `mas/agents/campaign_deploy.py` |

---

## PHASE 2 — High Value (Build Next) 🔜

### Advertising
- **A/B test framework** — link individual ad creative IDs to purchases; declare winner after 500 impressions; pause losers automatically
- **Retargeting audiences** — build Custom Audiences from pixel visitors; create Lookalikes; run separate retargeting campaigns at $2/day
- **Ad creative refresh** — detect CTR decay (>20% drop week-over-week); auto-generate new creatives with Claude; swap in without restarting campaign
- **Google Shopping ads** — products with Amazon price anchor are perfect for Google Shopping (higher intent buyers)
- **Video ads** — use FFmpeg + product images to generate 15-second slideshow video ads; video creatives get 3× lower CPM on TikTok

### Revenue
- **Upsell / quantity bundles** — "Buy 2 Get 15% Off" Stripe Payment Link variant; add to landing page as second CTA; ~20% AOV lift
- **Abandoned cart email** — capture email before Stripe checkout (via modal); send 3-email sequence if no purchase in 24h (Resend)
- **Post-purchase follow-up** — day 7 email: "How's your [product]?" + review request + cross-sell related product
- **Subscription variants** — for consumable products (supplements, pet food, beauty), offer monthly subscription via Stripe Subscriptions at 10% discount

### Fulfillment
- **AliExpress order auto-placement** — DSers has a CSV bulk order upload; automate via Playwright bot that uploads CSV daily
- **Tracking number auto-email** — when `tracking_number` set on CustomerOrder, auto-send Aftership tracking email to customer
- **Supplier price drift monitor** — re-check AliExpress price every 3 days; if cost rises >15%, pause campaign and alert
- **Supplier failover** — keep top-3 ranked AliExpress suppliers per product; if primary goes OOS, auto-switch to #2

### Analytics
- **Google Trends validation** — before launching, check Google Trends for the keyword; avoid products in decline phase
- **Cohort P&L report** — group products by launch week; show which weeks are profitable vs. not; CSV export
- **CAC payback dashboard** — days to recover customer acquisition cost at current purchase rate

---

## PHASE 3 — Operations at Scale 📈

- **Multi-account support** — run multiple store brands from one orchestrator; tenant isolation per brand
- **Proxy rotation** — at >50 scraping sessions/hour, rotate residential proxies (Bright Data or Oxylabs) to avoid IP bans
- **Landing page A/B testing** — generate 2 Claude variants per product; split 50/50 traffic via URL params; auto-select winner after 200 visitors
- **Influencer/UGC outreach** — when a product hits SCALED state, trigger a Resend sequence to TikTok creators in niche offering free product + commission
- **Legal compliance generator** — auto-append Privacy Policy, Return Policy, Terms of Service footer to every landing page (Claude-generated)
- **Chargeback protection** — Stripe Radar rules to block high-risk orders; auto-refund if fraud score > 70

---

## PHASE 4 — Infrastructure 🏗️

- **PostgreSQL migration** — replace SQLite when >10K pipelines; use Supabase free tier
- **S3 lander hosting** — serve landing pages from S3 + CloudFront (faster, no single point of failure)
- **Encrypted backups** — daily S3 backup of mas_state.db with AES-256 encryption
- **Uptime monitoring** — deploy Uptime Kuma (https://github.com/louislam/uptime-kuma) to monitor `/health` endpoint; alert on downtime
- **Audit log** — immutable append-only log of all HITL approvals, budget changes, agent failures (required for payment processor compliance)
- **Rate limiting** — add Redis-backed rate limiting to all API endpoints; prevent abuse of `/run-cycle`

---

## NEVER BUILD (intentional exclusions)

- Subscription / SaaS model — wrong business model for dropshipping
- Warehouse / physical inventory — defeats the purpose of dropshipping
- Multi-currency support — US market only until $10K/day achieved; complexity not worth it

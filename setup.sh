#!/usr/bin/env bash
# Quick-MAS-SELLS — one-command setup script
# Run: bash setup.sh
set -euo pipefail

GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${CYAN}[QMS]${NC} $1"; }
success() { echo -e "${GREEN}[✓]${NC} $1"; }
warn()    { echo -e "${YELLOW}[!]${NC} $1"; }

echo ""
echo -e "${GREEN}╔══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Quick-MAS-SELLS  — Setup Script    ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════╝${NC}"
echo ""

# ── 1. Python version check ──────────────────────────────────────────────────
info "Checking Python version..."
PYTHON=$(command -v python3 || command -v python)
PY_VER=$($PYTHON --version 2>&1 | awk '{print $2}')
info "Found: $PY_VER"
if [[ "$PY_VER" < "3.10" ]]; then
    echo -e "${RED}ERROR: Python 3.10+ required. Install from https://python.org${NC}"
    exit 1
fi
success "Python OK"

# ── 2. Virtual environment ───────────────────────────────────────────────────
if [ ! -d ".venv" ]; then
    info "Creating virtual environment..."
    $PYTHON -m venv .venv
fi
source .venv/bin/activate
success "Virtual environment active"

# ── 3. Pip upgrade + install deps ───────────────────────────────────────────
info "Installing Python dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
success "Python packages installed"

# ── 4. Playwright browsers ───────────────────────────────────────────────────
info "Installing Playwright Chromium browser..."
python -m playwright install chromium --with-deps -q 2>/dev/null || \
    warn "Playwright install failed (non-fatal — httpx fallback will be used)"
success "Playwright ready"

# ── 5. .env file ─────────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
    cp .env.example .env
    warn ".env created from template — you MUST edit it before running!"
    echo ""
    echo -e "  ${YELLOW}Required keys to fill in .env:${NC}"
    echo "  • ANTHROPIC_API_KEY    → https://console.anthropic.com"
    echo "  • META_APP_ID          → https://developers.facebook.com"
    echo "  • META_APP_SECRET      → (same page)"
    echo "  • META_ACCESS_TOKEN    → see SETUP.md Step 2"
    echo "  • META_AD_ACCOUNT_ID   → Business Manager → Ad Accounts"
    echo "  • META_PAGE_ID         → Your Facebook Page → About → Page ID"
    echo "  • META_PIXEL_ID        → Events Manager → Pixels"
    echo "  • STRIPE_SECRET_KEY    → https://dashboard.stripe.com/apikeys"
    echo "  • STRIPE_PUBLISHABLE_KEY → (same page)"
    echo "  • NGROK_AUTHTOKEN      → https://dashboard.ngrok.com (optional)"
    echo ""
else
    success ".env already exists"
fi

# ── 6. Create runtime directories ───────────────────────────────────────────
mkdir -p landers
success "Runtime directories ready"

# ── 7. Summary ───────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         Setup Complete!               ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${CYAN}Next steps:${NC}"
echo "  1. Edit .env with your API keys (see SETUP.md)"
echo "  2. source .venv/bin/activate"
echo "  3. python main.py serve"
echo "  4. Open http://localhost:8000"
echo "  5. python main.py run-cycle   ← starts discovering products"
echo ""

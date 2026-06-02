"""Integration tests for the MAS pipeline.

Tests run against a real in-memory SQLite store without hitting external APIs.
Scrapers and the Claude API are mocked.
"""
from __future__ import annotations

import asyncio
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from mas.state.models import (
    AdCreative,
    AdStatus,
    CampaignResult,
    DiscoveredProduct,
    GeneratedContent,
    LandingPage,
    PipelineState,
    ProductPipeline,
    SourcePlatform,
    SupplierProduct,
)
from mas.state.store import StateStore


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def store(tmp_path):
    db_path = str(tmp_path / "test.db")
    s = StateStore(db_path)
    await s.connect()
    yield s
    await s.close()


@pytest.fixture
def sample_discovered() -> DiscoveredProduct:
    return DiscoveredProduct(
        source=SourcePlatform.TIKTOK,
        title="Electric Neck Massager",
        description="This neck massager is amazing! #TikTokMadeMeBuyIt",
        source_url="https://www.tiktok.com/@user/video/123",
        engagement_score=0.82,
        keyword="TikTokMadeMeBuyIt",
    )


@pytest.fixture
def sample_supplier(sample_discovered) -> SupplierProduct:
    return SupplierProduct(
        product_id="test-pipeline-id",
        aliexpress_item_id="1005006123456789",
        aliexpress_url="https://www.aliexpress.com/item/1005006123456789.html",
        title="Electric Neck Massager EMS Cervical Massager",
        price_usd=12.99,
        review_count=8542,
        rating=4.8,
        image_urls=["https://ae01.alicdn.com/kf/image.jpg"],
    )


# ── Model tests ─────────────────────────────────────────────────────────────────

def test_supplier_pricing(sample_supplier):
    assert sample_supplier.suggested_retail_price == round(12.99 * 3.5, 2)
    assert sample_supplier.gross_margin_pct > 0


def test_pipeline_state_transition():
    p = ProductPipeline()
    assert p.state == PipelineState.DISCOVERED
    p.transition(PipelineState.SUPPLIER_VALIDATED)
    assert p.state == PipelineState.SUPPLIER_VALIDATED


def test_pipeline_fail_closed():
    p = ProductPipeline()
    for _ in range(3):
        p.record_failure("test error")
    assert p.state == PipelineState.FAILED
    assert p.failure_count == 3


def test_performance_metrics_compute():
    from mas.state.models import PerformanceMetrics
    m = PerformanceMetrics(
        product_id="x",
        spend_usd=20.0,
        impressions=10000,
        clicks=200,
        purchases=5,
        revenue_usd=100.0,
        cogs_usd=25.0,
        stripe_fees_usd=4.40,
    )
    m.compute()
    assert m.roas == 5.0          # 100 revenue / 20 spend
    assert m.ctr == 2.0           # 200 clicks / 10000 impressions
    assert m.cpc_usd == 0.10      # 20 spend / 200 clicks
    # net = 100 - 20 spend - 25 cogs - 4.40 fees = 50.60
    assert m.net_profit_usd == 50.60


# ── Store tests ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_store_upsert_and_get(store, sample_discovered):
    pipeline = ProductPipeline(discovered_product=sample_discovered)
    await store.upsert_pipeline(pipeline)

    retrieved = await store.get_pipeline(pipeline.id)
    assert retrieved is not None
    assert retrieved.id == pipeline.id
    assert retrieved.discovered_product.title == "Electric Neck Massager"


@pytest.mark.asyncio
async def test_store_list_by_state(store, sample_discovered):
    p1 = ProductPipeline(
        state=PipelineState.DISCOVERED,
        discovered_product=sample_discovered,
    )
    p2 = ProductPipeline(
        state=PipelineState.SUPPLIER_VALIDATED,
        discovered_product=sample_discovered,
    )
    await store.upsert_pipeline(p1)
    await store.upsert_pipeline(p2)

    discovered = await store.list_pipelines(state=PipelineState.DISCOVERED)
    assert any(p.id == p1.id for p in discovered)
    assert not any(p.id == p2.id for p in discovered)


@pytest.mark.asyncio
async def test_store_event_emission(store):
    from mas.state.models import AgentEvent
    event = AgentEvent(
        agent_name="TestAgent",
        event_type="test_event",
        pipeline_id="test-id",
        payload={"key": "value"},
    )
    await store.emit_event(event)
    events = await store.get_events(pipeline_id="test-id")
    assert len(events) == 1
    assert events[0].event_type == "test_event"


# ── Agent tests (mocked external calls) ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_supplier_intel_agent_success(store, sample_discovered, sample_supplier):
    pipeline = ProductPipeline(
        state=PipelineState.DISCOVERED,
        discovered_product=sample_discovered,
    )
    await store.upsert_pipeline(pipeline)

    with patch(
        "mas.agents.supplier_intel.find_supplier",
        new_callable=AsyncMock,
        return_value=sample_supplier,
    ):
        from mas.agents.supplier_intel import SupplierIntelAgent
        agent = SupplierIntelAgent(store)
        updated = await agent.run(pipeline)

    assert updated.state == PipelineState.SUPPLIER_VALIDATED
    assert updated.supplier is not None
    assert updated.supplier.rating == 4.8


@pytest.mark.asyncio
async def test_supplier_intel_agent_no_supplier(store, sample_discovered):
    pipeline = ProductPipeline(
        state=PipelineState.DISCOVERED,
        discovered_product=sample_discovered,
    )
    await store.upsert_pipeline(pipeline)

    with patch(
        "mas.agents.supplier_intel.find_supplier",
        new_callable=AsyncMock,
        return_value=None,
    ):
        from mas.agents.supplier_intel import SupplierIntelAgent
        agent = SupplierIntelAgent(store)
        updated = await agent.run(pipeline)

    # Should record a failure but not crash
    assert updated.failure_count == 1
    assert updated.state == PipelineState.DISCOVERED


@pytest.mark.asyncio
async def test_content_forge_agent(store, sample_discovered, sample_supplier):
    pipeline = ProductPipeline(
        id="test-content-id",
        state=PipelineState.SUPPLIER_VALIDATED,
        discovered_product=sample_discovered,
        supplier=sample_supplier,
    )
    pipeline.supplier.product_id = pipeline.id
    await store.upsert_pipeline(pipeline)

    mock_content = GeneratedContent(
        product_id=pipeline.id,
        landing_page=LandingPage(
            product_id=pipeline.id,
            html="<html><body>Test lander</body></html>",
            lander_url="http://localhost:8000/landers/test-content-id",
        ),
        ad_creatives=[
            AdCreative(headline="Amazing Neck Massager!", body="Fix your neck pain fast.", cta="Shop Now"),
            AdCreative(headline="Say Goodbye to Neck Pain", body="Thousands love this massager.", cta="Get Yours"),
        ],
    )

    with patch(
        "mas.agents.content_forge.generate_content",
        new_callable=AsyncMock,
        return_value=mock_content,
    ):
        with patch("mas.agents.content_forge.get_settings") as mock_cfg:
            cfg = MagicMock()
            cfg.hitl_enabled = False
            cfg.anthropic_api_key = "test"
            mock_cfg.return_value = cfg

            from mas.agents.content_forge import ContentForgeAgent
            agent = ContentForgeAgent(store)
            updated = await agent.run(pipeline)

    assert updated.state == PipelineState.CONTENT_GENERATED
    assert updated.content is not None
    assert len(updated.content.ad_creatives) == 2


@pytest.mark.asyncio
async def test_orchestrator_cycle(store):
    """Smoke test: orchestrator cycle should complete without exceptions."""
    with patch("mas.agents.trend_spotter.discover_tiktok_products", new_callable=AsyncMock, return_value=[]), \
         patch("mas.agents.trend_spotter.discover_amazon_products", new_callable=AsyncMock, return_value=[]):
        from mas.orchestrator import Orchestrator
        orch = Orchestrator(store)
        summary = await orch.run_cycle()
        assert "steps" in summary
        assert summary["steps"]["trend_spotter"]["new_products"] == 0
        # Guardrail must run as Step 0 of every cycle
        assert "guardrail" in summary["steps"]


# ── New coverage: gaps closed in the audit ──────────────────────────────────────

@pytest.mark.asyncio
async def test_guardrail_preflight_rejects_thin_margin(store, sample_discovered):
    """Pre-flight must block deployment when gross margin < 40%."""
    from mas.agents.guardrail import GuardrailAgent
    # price 80 → retail 280 → margin is high; force thin by setting retail near cost.
    thin = SupplierProduct(
        product_id="thin-id",
        title="Overpriced Gadget",
        price_usd=80.0,        # 3.5x = 280 retail → margin ~71%, so override below
    )
    # Simulate supplier whose retail barely exceeds cost by monkeypatching margin
    pipeline = ProductPipeline(id="thin-id", discovered_product=sample_discovered, supplier=thin)

    # Thin-margin supplier stub — margin check returns before competitor research,
    # so no need to mock fb_ad_library here.
    class ThinSupplier:
        gross_margin_pct = 12.0
        price_usd = 80.0
        suggested_retail_price = 91.0

    pipeline.supplier = ThinSupplier()
    agent = GuardrailAgent(store)
    ok, reason = await agent.pre_flight_check(pipeline)
    assert ok is False
    assert "Margin too thin" in reason


@pytest.mark.asyncio
async def test_dashboard_net_profit(store, sample_discovered, sample_supplier):
    """build_dashboard_stats must compute net profit = revenue - spend - cogs - fees."""
    from mas.state.models import PerformanceMetrics
    pipeline = ProductPipeline(
        state=PipelineState.MONITORING,
        discovered_product=sample_discovered,
        supplier=sample_supplier,
    )
    m = PerformanceMetrics(
        product_id=pipeline.id, spend_usd=20.0, revenue_usd=100.0,
        cogs_usd=25.0, stripe_fees_usd=4.40, purchases=5,
    )
    m.compute()
    pipeline.metrics.append(m)
    await store.upsert_pipeline(pipeline)

    from mas.orchestrator import Orchestrator
    orch = Orchestrator(store)
    stats = await orch.build_dashboard_stats()
    assert stats["net_profit_usd"] == 50.60
    assert stats["total_revenue_usd"] == 100.0


def test_customer_order_and_pipeline_revenue(sample_discovered, sample_supplier):
    """CustomerOrder records and pipeline revenue aggregation."""
    from mas.state.models import CustomerOrder, OrderStatus
    p = ProductPipeline(discovered_product=sample_discovered, supplier=sample_supplier)
    p.orders.append(CustomerOrder(pipeline_id=p.id, amount_usd=45.99, customer_email="a@b.com"))
    p.orders.append(CustomerOrder(pipeline_id=p.id, amount_usd=45.99, customer_email="c@d.com"))
    assert p.total_orders == 2
    assert round(p.total_revenue_usd, 2) == 91.98
    assert p.orders[0].status == OrderStatus.PENDING_FULFILLMENT

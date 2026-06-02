"""Order management endpoints — track fulfilment from Stripe purchase to delivery."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from mas.state.models import CustomerOrder, OrderStatus
from mas.state.store import StateStore, get_store

router = APIRouter(prefix="/orders", tags=["orders"])


class OrderUpdate(BaseModel):
    aliexpress_order_id: Optional[str] = None
    tracking_number: Optional[str] = None
    carrier: Optional[str] = None
    status: Optional[OrderStatus] = None
    notes: Optional[str] = None


@router.get("/", response_model=List[CustomerOrder])
async def list_orders(
    status: Optional[str] = None,
    limit: int = 100,
    store: StateStore = Depends(get_store),
):
    """List all orders across all pipelines. Filter by status."""
    all_pipelines = await store.list_pipelines(limit=10_000)
    orders = []
    for p in all_pipelines:
        for o in p.orders:
            if status is None or o.status.value == status.upper():
                orders.append(o)
    orders.sort(key=lambda x: x.created_at, reverse=True)
    return orders[:limit]


@router.get("/pending-fulfillment", response_model=List[dict])
async def pending_fulfillment(store: StateStore = Depends(get_store)):
    """Orders that need to be placed on AliExpress — your daily work queue."""
    all_pipelines = await store.list_pipelines(limit=10_000)
    result = []
    for p in all_pipelines:
        for o in p.orders:
            if o.status == OrderStatus.PENDING_FULFILLMENT:
                result.append({
                    "order_id": o.id,
                    "pipeline_id": o.pipeline_id,
                    "product_title": (
                        p.supplier.title if p.supplier
                        else p.discovered_product.title if p.discovered_product
                        else "Unknown"
                    ),
                    "aliexpress_url": p.supplier.aliexpress_url if p.supplier else "",
                    "cost_usd": p.supplier.price_usd if p.supplier else 0.0,
                    "customer_email": o.customer_email,
                    "customer_name": o.customer_name,
                    "amount_paid_usd": o.amount_usd,
                    "profit_usd": round(o.amount_usd - (p.supplier.price_usd if p.supplier else 0), 2),
                    "created_at": o.created_at.isoformat(),
                    "stripe_session": o.stripe_session_id,
                })
    return result


@router.patch("/{order_id}", response_model=CustomerOrder)
async def update_order(
    order_id: str,
    update: OrderUpdate,
    store: StateStore = Depends(get_store),
):
    """Update order fulfillment status (add tracking number, mark shipped, etc)."""
    all_pipelines = await store.list_pipelines(limit=10_000)
    for p in all_pipelines:
        for i, o in enumerate(p.orders):
            if o.id == order_id:
                if update.aliexpress_order_id is not None:
                    o.aliexpress_order_id = update.aliexpress_order_id
                if update.tracking_number is not None:
                    o.tracking_number = update.tracking_number
                if update.carrier is not None:
                    o.carrier = update.carrier
                if update.status is not None:
                    o.status = update.status
                if update.notes is not None:
                    o.notes = update.notes
                from datetime import datetime
                o.updated_at = datetime.utcnow()
                p.orders[i] = o
                await store.upsert_pipeline(p)
                return o
    raise HTTPException(404, f"Order {order_id} not found")

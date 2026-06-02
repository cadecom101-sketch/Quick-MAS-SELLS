"""SQLite-backed, async state store for all ProductPipeline records.

Uses raw aiosqlite so there are zero ORM migration headaches while keeping
full async support. Schema is created on first start (idempotent).
"""
from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional

import aiosqlite

from mas.state.models import AgentEvent, PipelineState, ProductPipeline

logger = logging.getLogger(__name__)


class StateStore:
    def __init__(self, db_path: str = "mas_state.db") -> None:
        self._db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._create_schema()
        logger.info("StateStore connected: %s", self._db_path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    # ── Schema ─────────────────────────────────────────────────────────────────

    async def _create_schema(self) -> None:
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS pipelines (
                id          TEXT PRIMARY KEY,
                state       TEXT NOT NULL,
                payload     TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_pipelines_state ON pipelines(state);

            CREATE TABLE IF NOT EXISTS events (
                id          TEXT PRIMARY KEY,
                agent_name  TEXT NOT NULL,
                event_type  TEXT NOT NULL,
                pipeline_id TEXT,
                payload     TEXT NOT NULL,
                emitted_at  TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_pipeline ON events(pipeline_id);
        """)
        await self._db.commit()

    # ── Pipeline CRUD ───────────────────────────────────────────────────────────

    async def upsert_pipeline(self, pipeline: ProductPipeline) -> None:
        payload = pipeline.model_dump_json()
        await self._db.execute(
            """
            INSERT INTO pipelines (id, state, payload, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                state      = excluded.state,
                payload    = excluded.payload,
                updated_at = excluded.updated_at
            """,
            (
                pipeline.id,
                pipeline.state.value,
                payload,
                pipeline.created_at.isoformat(),
                pipeline.updated_at.isoformat(),
            ),
        )
        await self._db.commit()

    async def get_pipeline(self, pipeline_id: str) -> Optional[ProductPipeline]:
        async with self._db.execute(
            "SELECT payload FROM pipelines WHERE id = ?", (pipeline_id,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return ProductPipeline.model_validate_json(row["payload"])

    async def list_pipelines(
        self, state: Optional[PipelineState] = None, limit: int = 100
    ) -> List[ProductPipeline]:
        if state:
            async with self._db.execute(
                "SELECT payload FROM pipelines WHERE state = ? ORDER BY updated_at DESC LIMIT ?",
                (state.value, limit),
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with self._db.execute(
                "SELECT payload FROM pipelines ORDER BY updated_at DESC LIMIT ?", (limit,)
            ) as cur:
                rows = await cur.fetchall()
        return [ProductPipeline.model_validate_json(r["payload"]) for r in rows]

    async def get_all_pipelines_map(self) -> Dict[str, ProductPipeline]:
        pipelines = await self.list_pipelines(limit=10_000)
        return {p.id: p for p in pipelines}

    # ── Events ─────────────────────────────────────────────────────────────────

    async def emit_event(self, event: AgentEvent) -> None:
        await self._db.execute(
            """
            INSERT OR IGNORE INTO events (id, agent_name, event_type, pipeline_id, payload, emitted_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.agent_name,
                event.event_type,
                event.pipeline_id,
                json.dumps(event.payload),
                event.emitted_at.isoformat(),
            ),
        )
        await self._db.commit()

    async def get_events(
        self, pipeline_id: Optional[str] = None, limit: int = 200
    ) -> List[AgentEvent]:
        if pipeline_id:
            async with self._db.execute(
                "SELECT * FROM events WHERE pipeline_id = ? ORDER BY emitted_at DESC LIMIT ?",
                (pipeline_id, limit),
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with self._db.execute(
                "SELECT * FROM events ORDER BY emitted_at DESC LIMIT ?", (limit,)
            ) as cur:
                rows = await cur.fetchall()
        return [
            AgentEvent(
                id=r["id"],
                agent_name=r["agent_name"],
                event_type=r["event_type"],
                pipeline_id=r["pipeline_id"] or "",
                payload=json.loads(r["payload"]),
                emitted_at=r["emitted_at"],
            )
            for r in rows
        ]


# Singleton pattern – initialised by the FastAPI lifespan
_store: Optional[StateStore] = None


def get_store() -> StateStore:
    if _store is None:
        raise RuntimeError("StateStore not initialised. Call init_store() first.")
    return _store


async def init_store(db_path: str = "mas_state.db") -> StateStore:
    global _store
    _store = StateStore(db_path)
    await _store.connect()
    return _store

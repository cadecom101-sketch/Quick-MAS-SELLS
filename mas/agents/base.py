"""Base agent class with retry, health-check, and fail-closed protocol."""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional

from mas.state.models import AgentEvent
from mas.state.store import StateStore
from mas.telemetry.logger import get_logger


class BaseAgent(ABC):
    MAX_CONSECUTIVE_FAILURES = 3

    def __init__(self, store: StateStore) -> None:
        self.store = store
        self.name = self.__class__.__name__
        self.log = get_logger(self.name)
        self._consecutive_failures = 0
        self._healthy = True
        self._last_health_check: Optional[datetime] = None

    # ── Health ──────────────────────────────────────────────────────────────────

    @property
    def healthy(self) -> bool:
        return self._healthy

    def _record_success(self) -> None:
        self._consecutive_failures = 0
        self._healthy = True
        self._last_health_check = datetime.utcnow()

    def _record_failure(self, exc: Exception) -> None:
        self._consecutive_failures += 1
        self.log.error(
            "agent_failure",
            agent=self.name,
            consecutive=self._consecutive_failures,
            error=str(exc),
        )
        if self._consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
            self._healthy = False
            self.log.error(
                "agent_unhealthy_fail_closed",
                agent=self.name,
                msg="Agent marked unhealthy after 3 consecutive failures. "
                    "Human intervention required.",
            )

    # ── Event bus helper ────────────────────────────────────────────────────────

    async def emit(self, event_type: str, pipeline_id: str = "", **payload: Any) -> None:
        event = AgentEvent(
            agent_name=self.name,
            event_type=event_type,
            pipeline_id=pipeline_id,
            payload=payload,
        )
        await self.store.emit_event(event)

    # ── Retry wrapper ───────────────────────────────────────────────────────────

    async def run_with_retry(self, *args: Any, **kwargs: Any) -> Any:
        if not self._healthy:
            raise RuntimeError(f"{self.name} is unhealthy. Refusing to run (fail-closed).")
        backoff = 2.0
        for attempt in range(1, 4):
            try:
                result = await self._run(*args, **kwargs)
                self._record_success()
                return result
            except Exception as exc:
                self._record_failure(exc)
                if attempt < 3 and self._healthy:
                    self.log.warning(
                        "agent_retry",
                        attempt=attempt,
                        backoff=backoff,
                        error=str(exc),
                    )
                    await asyncio.sleep(backoff)
                    backoff *= 2
                else:
                    raise

    @abstractmethod
    async def _run(self, *args: Any, **kwargs: Any) -> Any:
        """Implement the agent's core logic here."""
        ...

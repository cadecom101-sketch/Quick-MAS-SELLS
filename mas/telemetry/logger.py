"""Structured JSON telemetry + Rich console sink.

Usage:
    from mas.telemetry.logger import get_logger
    log = get_logger("TrendSpotterAgent")
    log.info("product_discovered", product_id="abc", title="Neck Massager")
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from typing import Any

from rich.console import Console
from rich.logging import RichHandler

_console = Console(stderr=True)


class _StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        extras = {k: v for k, v in record.__dict__.items() if k.startswith("_x_")}
        doc = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            **{k[3:]: v for k, v in extras.items()},
        }
        if record.exc_info:
            doc["exc"] = self.formatException(record.exc_info)
        return json.dumps(doc)


class _ContextLogger(logging.LoggerAdapter):
    def process(self, msg: str, kwargs: Any) -> tuple:
        extra = kwargs.pop("extra", {})
        # Flatten keyword args into the record with _x_ prefix to avoid clashes
        for k, v in kwargs.pop("kw", {}).items():
            extra[f"_x_{k}"] = v
        kwargs["extra"] = extra
        return msg, kwargs

    def _log_kw(self, level: int, msg: str, **kw: Any) -> None:
        self.log(level, msg, extra={f"_x_{k}": v for k, v in kw.items()})

    def info(self, msg: str, *args: Any, **kw: Any) -> None:  # type: ignore[override]
        self.logger.info(msg, *args, extra={f"_x_{k}": v for k, v in kw.items()})

    def warning(self, msg: str, *args: Any, **kw: Any) -> None:  # type: ignore[override]
        self.logger.warning(msg, *args, extra={f"_x_{k}": v for k, v in kw.items()})

    def error(self, msg: str, *args: Any, **kw: Any) -> None:  # type: ignore[override]
        self.logger.error(msg, *args, extra={f"_x_{k}": v for k, v in kw.items()})

    def debug(self, msg: str, *args: Any, **kw: Any) -> None:  # type: ignore[override]
        self.logger.debug(msg, *args, extra={f"_x_{k}": v for k, v in kw.items()})


_configured = False


def configure_logging(level: str = "INFO") -> None:
    global _configured
    if _configured:
        return
    root = logging.getLogger()
    root.setLevel(level)

    # Rich handler – human-readable in dev
    rich_handler = RichHandler(
        console=_console,
        show_time=True,
        show_path=False,
        markup=True,
        rich_tracebacks=True,
    )
    rich_handler.setLevel(level)
    root.addHandler(rich_handler)

    # JSON file handler – machine-readable audit trail
    file_handler = logging.FileHandler("mas_telemetry.jsonl", encoding="utf-8")
    file_handler.setFormatter(_StructuredFormatter())
    file_handler.setLevel(level)
    root.addHandler(file_handler)

    _configured = True


def get_logger(name: str) -> _ContextLogger:
    configure_logging()
    base = logging.getLogger(name)
    return _ContextLogger(base, extra={})

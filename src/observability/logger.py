"""
Observability — structured logging + trace context.

Every tool call, agent decision, and eval result is logged
with structured fields for debugging + compliance.

In production, these would go to:
  - ELK / Loki / CloudWatch for search
  - Jaeger / Tempo for distributed traces
  - Datadog / Grafana for dashboards
"""

from __future__ import annotations

import json
import logging
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Generator


# ── Structured log formatter ──────────────────────────────────────

class StructuredFormatter(logging.Formatter):
    """JSON-lines structured log formatter."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add extra fields
        for key in ("trace_id", "span_id", "tool_name", "latency_ms",
                     "incident_id", "server_name", "eval_check"):
            val = getattr(record, key, None)
            if val is not None:
                log_entry[key] = val

        return json.dumps(log_entry)


# ── Trace context ──────────────────────────────────────────────────

@dataclass
class Span:
    """A single span within a trace."""
    name: str
    trace_id: str
    span_id: str
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)

    @property
    def duration_ms(self) -> float:
        if self.end_time:
            return (self.end_time - self.start_time) * 1000
        return (time.time() - self.start_time) * 1000

    def add_event(self, name: str, **attrs):
        self.events.append({
            "name": name,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "attributes": attrs,
        })

    def finish(self):
        self.end_time = time.time()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "duration_ms": round(self.duration_ms, 2),
            "attributes": self.attributes,
            "events": self.events,
        }


@dataclass
class TraceCollector:
    """Collects spans for a single triage operation."""
    trace_id: str = ""
    spans: list[Span] = field(default_factory=list)
    _span_counter: int = 0

    def new_span(self, name: str, **attrs) -> Span:
        self._span_counter += 1
        span = Span(
            name=name,
            trace_id=self.trace_id,
            span_id=f"span-{self._span_counter:03d}",
            attributes=attrs,
        )
        self.spans.append(span)
        return span

    @contextmanager
    def span(self, name: str, **attrs) -> Generator[Span, None, None]:
        """Context manager for auto-finishing spans."""
        s = self.new_span(name, **attrs)
        try:
            yield s
        finally:
            s.finish()

    def get_summary(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "total_spans": len(self.spans),
            "total_duration_ms": sum(s.duration_ms for s in self.spans),
            "spans": [s.to_dict() for s in self.spans],
        }


# ── Setup ──────────────────────────────────────────────────────────

def setup_logging(level: str = "INFO", structured: bool = False):
    """
    Configure logging for the triage copilot.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR).
        structured: If True, use JSON-lines format. If False, human-readable.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stderr)

    if structured:
        handler.setFormatter(StructuredFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s │ %(levelname)-5s │ %(name)-15s │ %(message)s",
            datefmt="%H:%M:%S",
        ))

    root.addHandler(handler)

    # Suppress noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("mcp").setLevel(logging.WARNING)

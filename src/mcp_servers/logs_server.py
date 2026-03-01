"""
MCP Server — Logs

Tools:
  query_logs      — search log entries by service, time range, level
  extract_error_signatures — find unique error patterns in a log blob
  get_log_context — get surrounding log lines for a specific trace ID

Backed by mock JSON files in data/logs/.
In production, this would hit Elasticsearch / Loki / CloudWatch.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# ── Data path ──────────────────────────────────────────────────────
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "logs"

mcp = FastMCP(
    "logs-server",
    instructions="Query and analyse application logs. Returns structured log entries and error patterns.",
)


def _load_logs(service: str) -> list[dict]:
    """Load mock logs for a service."""
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", service)
    candidates = [
        DATA_DIR / f"{safe}.json",
        DATA_DIR / f"{safe.replace('-', '_')}.json",
    ]
    for p in candidates:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    return []


def _filter_by_time(logs: list[dict], start: str | None, end: str | None) -> list[dict]:
    """Filter logs by ISO-8601 time range."""
    filtered = logs
    if start:
        try:
            st = datetime.fromisoformat(start.replace("Z", "+00:00"))
            filtered = [
                l for l in filtered
                if datetime.fromisoformat(l["timestamp"].replace("Z", "+00:00")) >= st
            ]
        except ValueError:
            pass
    if end:
        try:
            et = datetime.fromisoformat(end.replace("Z", "+00:00"))
            filtered = [
                l for l in filtered
                if datetime.fromisoformat(l["timestamp"].replace("Z", "+00:00")) <= et
            ]
        except ValueError:
            pass
    return filtered


# ── Tools ──────────────────────────────────────────────────────────

@mcp.tool()
def query_logs(
    service: str,
    start_time: str | None = None,
    end_time: str | None = None,
    level: str = "ERROR",
    limit: int = 50,
) -> str:
    """
    Query log entries for a service.

    Args:
        service: Service name (e.g. "payment-service")
        start_time: ISO-8601 start (inclusive). Default: last 15 min.
        end_time: ISO-8601 end (inclusive). Default: now.
        level: Minimum log level — DEBUG, INFO, WARN, ERROR. Default ERROR.
        limit: Max entries to return. Default 50.

    Returns:
        JSON array of matching log entries with timestamp, level, message, trace_id.
    """
    level_order = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3}
    min_level = level_order.get(level.upper(), 3)

    logs = _load_logs(service)
    if not logs:
        return json.dumps({"error": f"No logs found for service '{service}'", "available_services": _available_services()})

    logs = _filter_by_time(logs, start_time, end_time)
    logs = [l for l in logs if level_order.get(l.get("level", "INFO"), 1) >= min_level]
    logs = logs[:limit]

    return json.dumps({
        "service": service,
        "count": len(logs),
        "entries": logs,
    }, indent=2)


@mcp.tool()
def extract_error_signatures(service: str, start_time: str | None = None, end_time: str | None = None) -> str:
    """
    Identify unique error patterns in recent logs.

    Returns a ranked list of error signatures with counts — useful for
    quickly understanding the dominant failure mode.

    Args:
        service: Service name.
        start_time: ISO-8601 start. Default: last 30 min.
        end_time: ISO-8601 end. Default: now.
    """
    logs = _load_logs(service)
    logs = _filter_by_time(logs, start_time, end_time)
    errors = [l for l in logs if l.get("level") in ("ERROR", "WARN")]

    # Extract signature: error_code if present, else first 80 chars of message
    sigs: list[str] = []
    for e in errors:
        code = e.get("error_code", "")
        msg = e.get("message", "")[:80]
        sigs.append(f"{code}: {msg}" if code else msg)

    counts = Counter(sigs)
    ranked = [
        {"signature": sig, "count": cnt, "first_seen": None, "last_seen": None}
        for sig, cnt in counts.most_common(10)
    ]

    # Fill in first/last seen
    for r in ranked:
        matching = [l for l in errors if r["signature"] in f"{l.get('error_code', '')}: {l.get('message', '')}" or r["signature"] in l.get("message", "")]
        if matching:
            r["first_seen"] = matching[0].get("timestamp")
            r["last_seen"] = matching[-1].get("timestamp")

    return json.dumps({
        "service": service,
        "total_errors": len(errors),
        "unique_signatures": len(ranked),
        "signatures": ranked,
    }, indent=2)


@mcp.tool()
def get_log_context(service: str, trace_id: str) -> str:
    """
    Get all log entries for a specific trace ID — useful for following
    a request across log lines.

    Args:
        service: Service name.
        trace_id: The trace/correlation ID to search for.
    """
    logs = _load_logs(service)
    matching = [l for l in logs if l.get("trace_id") == trace_id]

    if not matching:
        return json.dumps({"error": f"No logs found for trace_id '{trace_id}' in '{service}'"})

    return json.dumps({
        "service": service,
        "trace_id": trace_id,
        "count": len(matching),
        "entries": matching,
    }, indent=2)


def _available_services() -> list[str]:
    """List services that have log files."""
    return [p.stem.replace("_", "-") for p in DATA_DIR.glob("*.json")]


@mcp.tool()
def list_available_services() -> str:
    """List all services that have log data available."""
    services = _available_services()
    return json.dumps({"services": services})


# ── Run ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mcp.run()

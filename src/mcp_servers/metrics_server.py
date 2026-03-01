"""
MCP Server — Metrics

Tools:
  query_metrics        — get time-series metrics for a service
  get_active_alerts    — list currently firing alerts
  get_deployments      — show recent deployments (change context)
  get_service_health   — quick health summary

Backed by mock JSON in data/metrics/ and data/alerts/.
In production: Prometheus, Datadog, Grafana, CloudWatch.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# ── Data paths ─────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent.parent / "data"
METRICS_FILE = BASE_DIR / "metrics" / "service_metrics.json"
ALERTS_FILE = BASE_DIR / "alerts" / "sample_alerts.json"

mcp = FastMCP(
    "metrics-server",
    instructions="Query service metrics, active alerts, and recent deployments.",
)


def _load_metrics() -> dict:
    if METRICS_FILE.exists():
        return json.loads(METRICS_FILE.read_text(encoding="utf-8"))
    return {}


def _load_alerts() -> list[dict]:
    if ALERTS_FILE.exists():
        return json.loads(ALERTS_FILE.read_text(encoding="utf-8"))
    return []


# ── Tools ──────────────────────────────────────────────────────────

@mcp.tool()
def query_metrics(
    service: str,
    metric_name: str = "error_rate",
    start_time: str | None = None,
    end_time: str | None = None,
) -> str:
    """
    Query time-series metrics for a service.

    Args:
        service: Service name (e.g. "payment-service").
        metric_name: One of: error_rate, latency_p99_ms, cpu_percent,
                     memory_mb, active_connections, gc_pause_ms.
        start_time: ISO-8601 start. Filters data points >= this time.
        end_time: ISO-8601 end. Filters data points <= this time.

    Returns:
        JSON with data points array, plus summary stats (min, max, avg, latest).
    """
    data = _load_metrics()
    svc_data = data.get(service)

    if not svc_data:
        available = [k for k in data.keys() if k != "recent_deployments"]
        return json.dumps({"error": f"No metrics for '{service}'", "available_services": available})

    series = svc_data.get(metric_name)
    if not series:
        available_metrics = list(svc_data.keys())
        return json.dumps({"error": f"Metric '{metric_name}' not found", "available_metrics": available_metrics})

    # Filter by time
    points = series
    if start_time:
        try:
            st = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            points = [p for p in points if datetime.fromisoformat(p["timestamp"].replace("Z", "+00:00")) >= st]
        except ValueError:
            pass
    if end_time:
        try:
            et = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            points = [p for p in points if datetime.fromisoformat(p["timestamp"].replace("Z", "+00:00")) <= et]
        except ValueError:
            pass

    if not points:
        return json.dumps({"service": service, "metric": metric_name, "data_points": [], "note": "No data in range"})

    values = [p["value"] for p in points]
    return json.dumps({
        "service": service,
        "metric": metric_name,
        "data_points": points,
        "summary": {
            "min": min(values),
            "max": max(values),
            "avg": round(sum(values) / len(values), 2),
            "latest": values[-1],
            "count": len(values),
        },
    }, indent=2)


@mcp.tool()
def get_active_alerts(service: str | None = None) -> str:
    """
    Get currently firing alerts, optionally filtered by service.

    Args:
        service: Filter to a specific service. If None, returns all alerts.
    """
    alerts = _load_alerts()
    if service:
        alerts = [a for a in alerts if a.get("service") == service]

    return json.dumps({
        "total_alerts": len(alerts),
        "alerts": alerts,
    }, indent=2)


@mcp.tool()
def get_deployments(service: str | None = None, hours_back: int = 24) -> str:
    """
    Get recent deployments — critical for correlating changes with incidents.

    Args:
        service: Filter to a specific service. If None, returns all.
        hours_back: How far back to look. Default 24 hours.
    """
    data = _load_metrics()
    deployments = data.get("recent_deployments", [])

    if service:
        deployments = [d for d in deployments if d.get("service") == service]

    return json.dumps({
        "total": len(deployments),
        "deployments": deployments,
    }, indent=2)


@mcp.tool()
def get_service_health(service: str) -> str:
    """
    Quick health summary: latest values of key metrics + any active alerts.

    Args:
        service: Service name.
    """
    data = _load_metrics()
    alerts = _load_alerts()

    svc_data = data.get(service)
    if not svc_data:
        return json.dumps({"error": f"No data for '{service}'"})

    # Get latest value for each metric
    health: dict = {"service": service, "metrics": {}, "active_alerts": []}
    for metric_name, series in svc_data.items():
        if isinstance(series, list) and series:
            latest = series[-1]
            health["metrics"][metric_name] = {
                "latest_value": latest["value"],
                "timestamp": latest["timestamp"],
            }

    # Active alerts for this service
    health["active_alerts"] = [a for a in alerts if a.get("service") == service]
    health["alert_count"] = len(health["active_alerts"])

    # Deployments
    deployments = data.get("recent_deployments", [])
    svc_deploys = [d for d in deployments if d.get("service") == service]
    health["recent_deployments"] = svc_deploys

    return json.dumps(health, indent=2)


# ── Run ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mcp.run()

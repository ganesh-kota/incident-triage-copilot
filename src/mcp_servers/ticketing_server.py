"""
MCP Server — Ticketing

Tools:
  create_incident  — open a new incident ticket
  update_incident  — update status/evidence on existing ticket
  get_incident     — retrieve ticket details
  list_incidents   — list recent tickets

In-memory store for the demo.
In production: Jira, ServiceNow, PagerDuty, Opsgenie.
"""

from __future__ import annotations

import json
from datetime import datetime

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "ticketing-server",
    instructions="Create and manage incident tickets. In-memory store for demo purposes.",
)

# ── In-memory ticket store ─────────────────────────────────────────
_tickets: dict[str, dict] = {}
_counter = 0


def _next_id() -> str:
    global _counter
    _counter += 1
    return f"INC-{_counter:04d}"


# ── Tools ──────────────────────────────────────────────────────────

@mcp.tool()
def create_incident(
    title: str,
    severity: str,
    summary: str,
    service: str = "",
    evidence_links: str = "",
    assignee: str = "",
) -> str:
    """
    Create a new incident ticket.

    Args:
        title: Short incident title (e.g. "payment-service 503s due to DB failure").
        severity: SEV1, SEV2, SEV3, or SEV4.
        summary: Detailed summary of the incident.
        service: Affected service name.
        evidence_links: Comma-separated list of evidence references.
        assignee: On-call engineer name/handle.

    Returns:
        JSON with created ticket details including the ticket_id.
    """
    ticket_id = _next_id()
    links = [l.strip() for l in evidence_links.split(",") if l.strip()] if evidence_links else []

    ticket = {
        "ticket_id": ticket_id,
        "title": title,
        "severity": severity.upper(),
        "status": "open",
        "summary": summary,
        "service": service,
        "evidence_links": links,
        "assignee": assignee or "unassigned",
        "timeline": [
            {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "action": "created",
                "detail": f"Incident created: {title}",
            }
        ],
        "created_at": datetime.utcnow().isoformat() + "Z",
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }

    _tickets[ticket_id] = ticket

    return json.dumps({
        "success": True,
        "ticket_id": ticket_id,
        "message": f"Incident {ticket_id} created successfully",
        "ticket": ticket,
    }, indent=2)


@mcp.tool()
def update_incident(
    ticket_id: str,
    status: str = "",
    update_note: str = "",
    additional_evidence: str = "",
    severity: str = "",
) -> str:
    """
    Update an existing incident ticket.

    Args:
        ticket_id: The ticket ID (e.g. "INC-0001").
        status: New status — open, investigating, identified, monitoring, resolved.
        update_note: Free-text update to add to the timeline.
        additional_evidence: Comma-separated evidence links to add.
        severity: Update severity if needed.
    """
    ticket = _tickets.get(ticket_id)
    if not ticket:
        return json.dumps({"error": f"Ticket '{ticket_id}' not found", "available": list(_tickets.keys())})

    now = datetime.utcnow().isoformat() + "Z"

    if status:
        ticket["status"] = status.lower()
        ticket["timeline"].append({"timestamp": now, "action": "status_change", "detail": f"Status → {status}"})

    if update_note:
        ticket["timeline"].append({"timestamp": now, "action": "note", "detail": update_note})

    if additional_evidence:
        new_links = [l.strip() for l in additional_evidence.split(",") if l.strip()]
        ticket["evidence_links"].extend(new_links)
        ticket["timeline"].append({"timestamp": now, "action": "evidence_added", "detail": f"Added: {new_links}"})

    if severity:
        ticket["severity"] = severity.upper()
        ticket["timeline"].append({"timestamp": now, "action": "severity_change", "detail": f"Severity → {severity}"})

    ticket["updated_at"] = now

    return json.dumps({
        "success": True,
        "ticket_id": ticket_id,
        "message": f"Ticket {ticket_id} updated",
        "ticket": ticket,
    }, indent=2)


@mcp.tool()
def get_incident(ticket_id: str) -> str:
    """
    Get full details of an incident ticket.

    Args:
        ticket_id: The ticket ID (e.g. "INC-0001").
    """
    ticket = _tickets.get(ticket_id)
    if not ticket:
        return json.dumps({"error": f"Ticket '{ticket_id}' not found", "available": list(_tickets.keys())})

    return json.dumps(ticket, indent=2)


@mcp.tool()
def list_incidents(status: str = "") -> str:
    """
    List all incident tickets, optionally filtered by status.

    Args:
        status: Filter by status (open, investigating, resolved, etc.). Empty = all.
    """
    tickets = list(_tickets.values())
    if status:
        tickets = [t for t in tickets if t["status"] == status.lower()]

    return json.dumps({
        "total": len(tickets),
        "tickets": [
            {
                "ticket_id": t["ticket_id"],
                "title": t["title"],
                "severity": t["severity"],
                "status": t["status"],
                "service": t["service"],
                "created_at": t["created_at"],
            }
            for t in tickets
        ],
    }, indent=2)


# ── Run ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mcp.run()

"""
Incident Contract — Pydantic Models (Phase 0)

These models are the *law* of the system.
Every input must be parseable into IncidentInput.
Every output must be a valid TriageOutput — no partial answers allowed.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────────

class Severity(str, Enum):
    SEV1 = "SEV1"
    SEV2 = "SEV2"
    SEV3 = "SEV3"
    SEV4 = "SEV4"


class Environment(str, Enum):
    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


# ── Input Contract ─────────────────────────────────────────────────

class IncidentInput(BaseModel):
    """What the on-call engineer provides. Only alert_text is mandatory."""

    alert_text: str = Field(
        ...,
        description="Raw alert/pager text. The only required field.",
        min_length=1,
    )
    stack_trace: Optional[str] = Field(
        default=None,
        description="Full stack trace if available.",
    )
    service_name: Optional[str] = Field(
        default=None,
        description="Name of the affected service (e.g. 'payment-service').",
    )
    environment: Environment = Field(
        default=Environment.PRODUCTION,
        description="Target environment.",
    )
    time_range_minutes: int = Field(
        default=15,
        ge=1,
        le=1440,
        description="How far back to look (minutes). Default 15.",
    )
    additional_context: Optional[str] = Field(
        default=None,
        description="Anything else the engineer wants to share.",
    )
    severity: Optional[Severity] = Field(
        default=None,
        description="Severity if already set by alerting system.",
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="When the incident was reported.",
    )


# ── Output Contract (every section mandatory) ──────────────────────

class EvidenceItem(BaseModel):
    """A single piece of evidence with source citation."""
    category: str = Field(..., description="LOGS | METRICS | RUNBOOK | DEPLOYMENT | OTHER")
    description: str = Field(..., description="What this evidence shows.")
    source_tool: str = Field(..., description="Which MCP tool produced this (e.g. logs_server/query_logs).")
    raw_snippet: Optional[str] = Field(default=None, description="Verbatim excerpt from the source.")


class RankedCause(BaseModel):
    """A possible root cause with confidence and supporting evidence."""
    rank: int = Field(..., ge=1)
    confidence: Confidence
    title: str
    reasoning: str
    evidence_refs: list[str] = Field(
        default_factory=list,
        description="References to EvidenceItem descriptions that support this cause.",
    )


class DiagnosticStep(BaseModel):
    """A concrete next step the on-call should take."""
    order: int = Field(..., ge=1)
    action: str
    command: Optional[str] = Field(default=None, description="Exact command to run, if applicable.")
    purpose: str


class Mitigation(BaseModel):
    """A remediation action with risk level."""
    order: int = Field(..., ge=1)
    risk: RiskLevel
    action: str
    rollback_steps: Optional[str] = Field(default=None, description="How to undo this if it makes things worse.")
    requires_confirmation: bool = Field(
        default=False,
        description="True if this needs human approval before execution.",
    )


class StakeholderUpdate(BaseModel):
    """Draft status update for leadership / Slack / Teams."""
    status_emoji: str = Field(default="🔴")
    title: str
    status: str = Field(description="Investigating | Identified | Monitoring | Resolved")
    impact: str
    cause_summary: str
    eta: str


class TriageOutput(BaseModel):
    """
    The FULL triage result. Every field is required.
    If the agent can't fill a section, it must say why and cite the gap.
    """
    incident_id: str = Field(..., description="Generated incident identifier.")
    summary: str = Field(..., min_length=10, description="1–2 sentence incident summary.")
    evidence: list[EvidenceItem] = Field(..., min_length=1, description="Must have at least one evidence item.")
    likely_causes: list[RankedCause] = Field(..., min_length=1)
    diagnostic_steps: list[DiagnosticStep] = Field(..., min_length=1)
    mitigations: list[Mitigation] = Field(..., min_length=1)
    stakeholder_update: StakeholderUpdate
    severity: Severity = Field(default=Severity.SEV2)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ── Ticketing models ───────────────────────────────────────────────

class IncidentTicket(BaseModel):
    """Represents a ticket created in Jira / ServiceNow / PagerDuty."""
    ticket_id: str
    title: str
    severity: Severity
    status: str = Field(default="open")
    summary: str
    evidence_links: list[str] = Field(default_factory=list)
    assignee: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

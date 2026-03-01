"""
Tests for the Incident Triage Copilot.

Run: python -m pytest tests/ -v
"""

import json
from datetime import datetime

import pytest

# ── Model tests ────────────────────────────────────────────────────

from src.models.incident import (
    Confidence,
    DiagnosticStep,
    Environment,
    EvidenceItem,
    IncidentInput,
    Mitigation,
    RankedCause,
    RiskLevel,
    Severity,
    StakeholderUpdate,
    TriageOutput,
)


class TestIncidentInput:
    def test_minimal_input(self):
        """Only alert_text is required."""
        inp = IncidentInput(alert_text="Server is down")
        assert inp.alert_text == "Server is down"
        assert inp.environment == Environment.PRODUCTION
        assert inp.time_range_minutes == 15

    def test_full_input(self):
        inp = IncidentInput(
            alert_text="Error rate > 5%",
            service_name="payment-service",
            environment=Environment.STAGING,
            severity=Severity.SEV2,
            time_range_minutes=60,
            stack_trace="Traceback...",
            additional_context="Deployed v2.3.1",
        )
        assert inp.service_name == "payment-service"
        assert inp.severity == Severity.SEV2

    def test_empty_alert_rejected(self):
        with pytest.raises(Exception):
            IncidentInput(alert_text="")


class TestTriageOutput:
    def test_valid_output(self):
        output = TriageOutput(
            incident_id="INC-001",
            summary="Payment service is failing due to DB issues.",
            evidence=[
                EvidenceItem(
                    category="LOGS",
                    description="Connection refused errors",
                    source_tool="logs_server/query_logs",
                )
            ],
            likely_causes=[
                RankedCause(
                    rank=1,
                    confidence=Confidence.HIGH,
                    title="DB down",
                    reasoning="Connection refused in logs",
                )
            ],
            diagnostic_steps=[
                DiagnosticStep(order=1, action="Check DB pods", purpose="Verify DB status")
            ],
            mitigations=[
                Mitigation(order=1, risk=RiskLevel.LOW, action="Failover to replica")
            ],
            stakeholder_update=StakeholderUpdate(
                title="Payment Service Incident",
                status="Investigating",
                impact="12% errors",
                cause_summary="DB connectivity",
                eta="15 min",
            ),
        )
        assert output.incident_id == "INC-001"
        assert len(output.evidence) >= 1

    def test_missing_evidence_rejected(self):
        with pytest.raises(Exception):
            TriageOutput(
                incident_id="INC-001",
                summary="Something happened",
                evidence=[],  # must have at least 1
                likely_causes=[
                    RankedCause(rank=1, confidence=Confidence.LOW, title="x", reasoning="y")
                ],
                diagnostic_steps=[
                    DiagnosticStep(order=1, action="x", purpose="y")
                ],
                mitigations=[
                    Mitigation(order=1, risk=RiskLevel.LOW, action="x")
                ],
                stakeholder_update=StakeholderUpdate(
                    title="x", status="x", impact="x", cause_summary="x", eta="x"
                ),
            )


# ── Context policy tests ──────────────────────────────────────────

from src.agent.context_policy import estimate_tokens, redact_secrets, truncate_to_budget


class TestContextPolicy:
    def test_redact_api_key(self):
        text = "key = sk-abc123def456ghi789jkl012mno345pqr"
        result = redact_secrets(text)
        assert "sk-abc" not in result
        assert "[REDACTED_API_KEY]" in result

    def test_redact_bearer_token(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xxx"
        result = redact_secrets(text)
        assert "eyJhb" not in result
        assert "[REDACTED_TOKEN]" in result

    def test_redact_connection_string(self):
        text = "DATABASE_URL=postgresql://user:pass@host:5432/db"
        result = redact_secrets(text)
        assert "user:pass" not in result

    def test_safe_text_unchanged(self):
        text = "Connection refused to postgres-primary:5432"
        result = redact_secrets(text)
        assert result == text

    def test_token_estimation(self):
        assert estimate_tokens("hello world") > 0

    def test_truncation(self):
        long_text = "x" * 10000
        result = truncate_to_budget(long_text, 100)
        assert len(result) < 10000
        assert "truncated" in result


# ── Grounding tests ───────────────────────────────────────────────

from src.agent.grounding import check_required_sections, extract_citations, validate_citations


class TestGrounding:
    def test_extract_citations(self):
        text = """
        [LOGS: logs_server/query_logs] Found 47 ECONNREFUSED errors
        [METRICS: metrics_server/query_metrics] Error rate at 12%
        """
        citations = extract_citations(text)
        assert len(citations) >= 2
        assert citations[0].category == "LOGS"

    def test_validate_citations(self):
        from src.agent.grounding import Citation

        citations = [
            Citation(
                category="LOGS",
                source="logs_server/query_logs",
                description="test",
                raw_text="test",
            )
        ]
        result = validate_citations(citations, ["logs_server__query_logs"])
        assert result["valid"] == 1
        assert result["ungrounded"] == 0

    def test_required_sections(self):
        text = """
        ## 🚨 Incident Summary
        Something happened.
        ## 📋 Evidence
        - stuff
        ## 🔍 Likely Causes
        1. cause
        ## 🔧 Next Diagnostic Steps
        1. step
        ## 🛡️ Safe Mitigations
        1. do something
        ## 📢 Stakeholder Update
        Status update
        """
        result = check_required_sections(text)
        assert result["complete"] is True


# ── Evaluator tests ───────────────────────────────────────────────

from src.agent.evaluator import eval_completeness, eval_safety, eval_severity_policy


class TestEvaluator:
    def test_completeness_pass(self):
        text = """
        ## 🚨 Incident Summary
        x
        ## 📋 Evidence
        x
        ## 🔍 Likely Causes
        x
        ## 🔧 Next Diagnostic Steps
        x
        ## 🛡️ Safe Mitigations
        x
        ## 📢 Stakeholder Update
        x
        """
        result = eval_completeness(text)
        assert result.passed

    def test_safety_detects_drop_table(self):
        text = "Run: DROP TABLE users;"
        result = eval_safety(text)
        assert not result.passed

    def test_severity_policy_sev1(self):
        text = "[HIGH RISK] Restart database"
        result = eval_severity_policy(text, "SEV1")
        assert not result.passed


# ── State tests ───────────────────────────────────────────────────

from src.agent.state import StateManager, ToolCall


class TestState:
    def test_conversation_tracking(self):
        sm = StateManager()
        sm.add_user_message("Help!")
        sm.add_assistant_message("On it.")
        assert len(sm.conversation_history) == 2

    def test_tool_result_caching(self):
        sm = StateManager()
        tc = ToolCall(tool_name="test__tool", arguments={"a": 1}, result="ok")
        sm.add_tool_result(tc)
        cached = sm.get_cached_result("test__tool", {"a": 1})
        assert cached == "ok"

    def test_reset(self):
        sm = StateManager()
        sm.add_user_message("test")
        sm.reset()
        assert len(sm.conversation_history) == 0

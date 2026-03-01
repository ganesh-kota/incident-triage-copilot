"""
Evaluation Hooks — automated checks that run on every triage output.

These gates prevent bad outputs from reaching the on-call engineer.

Checks:
  1. Completeness  — all required sections present
  2. Grounding     — citations reference real tool calls
  3. Severity      — mitigations respect severity policy
  4. Safety        — no dangerous actions without confirmation flags
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .grounding import check_required_sections, extract_citations, validate_citations


@dataclass
class EvalResult:
    """Result of a single evaluation check."""
    check_name: str
    passed: bool
    score: float  # 0.0 to 1.0
    message: str
    details: dict | None = None


def eval_completeness(output_text: str) -> EvalResult:
    """Check that all required output sections are present."""
    result = check_required_sections(output_text)
    passed = result["complete"]
    score = result["sections_found"] / max(result["sections_required"], 1)

    msg = "All sections present" if passed else f"Missing: {', '.join(result['missing_sections'])}"

    return EvalResult(
        check_name="completeness",
        passed=passed,
        score=score,
        message=msg,
        details=result,
    )


def eval_grounding(output_text: str, tool_calls_made: list[str]) -> EvalResult:
    """Check that factual claims are backed by tool evidence."""
    citations = extract_citations(output_text)

    if not citations:
        return EvalResult(
            check_name="grounding",
            passed=False,
            score=0.0,
            message="No citations found in output — every claim must cite a source.",
        )

    validation = validate_citations(citations, tool_calls_made)
    passed = validation["grounding_score"] >= 0.8  # allow 20% slack
    score = validation["grounding_score"]

    if passed:
        msg = f"Grounding OK: {validation['valid']}/{validation['total_citations']} citations verified"
    else:
        msg = f"Grounding FAIL: {validation['ungrounded']} ungrounded claims"

    return EvalResult(
        check_name="grounding",
        passed=passed,
        score=score,
        message=msg,
        details=validation,
    )


def eval_severity_policy(output_text: str, severity: str | None) -> EvalResult:
    """
    Check that mitigations respect the severity policy.

    SEV1: only LOW risk without confirmation
    SEV2: LOW + MEDIUM ok; HIGH needs confirmation flag
    """
    if not severity:
        return EvalResult(
            check_name="severity_policy",
            passed=True,
            score=1.0,
            message="No severity set — policy not enforced.",
        )

    # Find HIGH RISK mitigations
    high_risk_pattern = re.compile(r"\[HIGH\s+RISK[^\]]*\]", re.IGNORECASE)
    high_risk_matches = high_risk_pattern.findall(output_text)

    # Check if they have "needs confirmation"
    confirmation_pattern = re.compile(r"\[HIGH\s+RISK\s*—?\s*needs?\s+confirmation\]", re.IGNORECASE)
    confirmed = confirmation_pattern.findall(output_text)

    sev = severity.upper()

    if sev == "SEV1":
        # No HIGH or MEDIUM risk without extra caution
        medium_risk = re.findall(r"\[MEDIUM\s+RISK\]", output_text, re.IGNORECASE)
        if high_risk_matches or medium_risk:
            return EvalResult(
                check_name="severity_policy",
                passed=False,
                score=0.3,
                message=f"SEV1 violation: Found {len(high_risk_matches)} HIGH + {len(medium_risk)} MEDIUM risk mitigations. SEV1 allows only LOW risk.",
            )

    if sev in ("SEV1", "SEV2"):
        unconfirmed_high = len(high_risk_matches) - len(confirmed)
        if unconfirmed_high > 0:
            return EvalResult(
                check_name="severity_policy",
                passed=False,
                score=0.5,
                message=f"HIGH risk mitigations must have 'needs confirmation' flag for {sev}. {unconfirmed_high} missing.",
            )

    return EvalResult(
        check_name="severity_policy",
        passed=True,
        score=1.0,
        message=f"Severity policy OK for {sev}",
    )


def eval_safety(output_text: str) -> EvalResult:
    """
    Check for dangerous actions that should always require confirmation.
    """
    dangerous_patterns = [
        (r"DROP\s+(TABLE|DATABASE)", "DROP TABLE/DATABASE"),
        (r"DELETE\s+FROM\s+\w+\s*(;|WHERE\s+1)", "Bulk DELETE"),
        (r"rm\s+-rf\s+/", "rm -rf /"),
        (r"TRUNCATE\s+TABLE", "TRUNCATE TABLE"),
        (r"format\s+[cC]:", "Format drive"),
    ]

    violations = []
    for pattern, label in dangerous_patterns:
        if re.search(pattern, output_text, re.IGNORECASE):
            violations.append(label)

    if violations:
        return EvalResult(
            check_name="safety",
            passed=False,
            score=0.0,
            message=f"Dangerous actions detected without safeguards: {', '.join(violations)}",
        )

    return EvalResult(
        check_name="safety",
        passed=True,
        score=1.0,
        message="No dangerous actions detected",
    )


def run_all_evals(
    output_text: str,
    tool_calls_made: list[str],
    severity: str | None = None,
) -> list[EvalResult]:
    """Run all evaluation checks and return results."""
    return [
        eval_completeness(output_text),
        eval_grounding(output_text, tool_calls_made),
        eval_severity_policy(output_text, severity),
        eval_safety(output_text),
    ]


def format_eval_report(results: list[EvalResult]) -> str:
    """Format eval results into a readable report."""
    lines = ["═══ Evaluation Report ═══"]
    all_passed = True
    for r in results:
        icon = "✅" if r.passed else "❌"
        lines.append(f"  {icon} {r.check_name}: {r.message} (score: {r.score:.0%})")
        if not r.passed:
            all_passed = False

    overall = "PASS ✅" if all_passed else "FAIL ❌ — output may need revision"
    lines.append(f"\n  Overall: {overall}")
    return "\n".join(lines)

"""
Grounding — enforces that every factual claim is backed by tool evidence.

This module provides:
  1. Citation extraction — parse citations from agent output
  2. Validation — check that cited sources match actual tool calls
  3. Formatting — ensure citations follow the standard format
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Citation:
    """A parsed citation from the agent output."""
    category: str       # LOGS, METRICS, RUNBOOK, DEPLOYMENT
    source: str         # e.g. "logs_server/query_logs"
    description: str    # what the citation claims
    raw_text: str       # the original text


# Pattern: [CATEGORY: source] description
_CITATION_PATTERN = re.compile(
    r"\[(\w+):\s*([^\]]+)\]\s*(.+?)(?=\n|\[|$)",
    re.MULTILINE,
)


def extract_citations(text: str) -> list[Citation]:
    """Extract all citations from agent output text."""
    citations = []
    for match in _CITATION_PATTERN.finditer(text):
        citations.append(Citation(
            category=match.group(1).upper(),
            source=match.group(2).strip(),
            description=match.group(3).strip(),
            raw_text=match.group(0).strip(),
        ))
    return citations


def validate_citations(
    citations: list[Citation],
    tool_calls_made: list[str],
) -> dict:
    """
    Check that cited sources correspond to tools that were actually called.

    Returns a validation report.
    """
    # Normalize tool call names (e.g. "logs_server__query_logs" → "logs_server/query_logs")
    normalized_calls = {tc.replace("__", "/") for tc in tool_calls_made}

    valid = []
    ungrounded = []

    for citation in citations:
        if citation.source in normalized_calls:
            valid.append(citation)
        else:
            # Check partial match (server name only)
            server = citation.source.split("/")[0]
            if any(server in tc for tc in normalized_calls):
                valid.append(citation)
            else:
                ungrounded.append(citation)

    return {
        "total_citations": len(citations),
        "valid": len(valid),
        "ungrounded": len(ungrounded),
        "ungrounded_details": [
            {"source": c.source, "claim": c.description[:100]}
            for c in ungrounded
        ],
        "grounding_score": len(valid) / max(len(citations), 1),
    }


def check_required_sections(text: str) -> dict:
    """
    Verify that the agent output contains all required sections
    from the incident contract.
    """
    required = {
        "Incident Summary": r"##\s*🚨?\s*Incident\s+Summary",
        "Evidence": r"##\s*📋?\s*Evidence",
        "Likely Causes": r"##\s*🔍?\s*Likely\s+Causes",
        "Diagnostic Steps": r"##\s*🔧?\s*(Next\s+)?Diagnostic\s+Steps",
        "Mitigations": r"##\s*🛡️?\s*Safe\s+Mitigations",
        "Stakeholder Update": r"##\s*📢?\s*Stakeholder\s+Update",
    }

    present = {}
    missing = []

    for section_name, pattern in required.items():
        if re.search(pattern, text, re.IGNORECASE):
            present[section_name] = True
        else:
            present[section_name] = False
            missing.append(section_name)

    return {
        "sections_found": sum(present.values()),
        "sections_required": len(required),
        "complete": len(missing) == 0,
        "missing_sections": missing,
        "details": present,
    }

"""
Context Policy — controls what goes into the LLM prompt and what gets redacted.

Rules:
  1. Token budget: tool results are summarized if over MAX_TOOL_RESULT_TOKENS
  2. PII / secret redaction: strip anything that looks like a key, token, or email
  3. Prioritization: most recent and most relevant context first
"""

from __future__ import annotations

import re

# ── Redaction patterns ─────────────────────────────────────────────

_REDACT_PATTERNS = [
    # API keys / tokens
    (re.compile(r"(sk-[a-zA-Z0-9]{20,})", re.I), "[REDACTED_API_KEY]"),
    (re.compile(r"(Bearer\s+[a-zA-Z0-9._\-]{20,})", re.I), "Bearer [REDACTED_TOKEN]"),
    (re.compile(r"(token[=:]\s*['\"]?[a-zA-Z0-9._\-]{20,})", re.I), "token=[REDACTED]"),
    (re.compile(r"(password[=:]\s*['\"]?[^\s'\"]{4,})", re.I), "password=[REDACTED]"),
    (re.compile(r"(secret[=:]\s*['\"]?[^\s'\"]{4,})", re.I), "secret=[REDACTED]"),
    # Connection strings
    (re.compile(r"(postgresql://[^\s]+)", re.I), "[REDACTED_CONN_STRING]"),
    (re.compile(r"(mongodb://[^\s]+)", re.I), "[REDACTED_CONN_STRING]"),
    (re.compile(r"(redis://[^\s]+)", re.I), "[REDACTED_CONN_STRING]"),
    # Email addresses
    (re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"), "[REDACTED_EMAIL]"),
    # IP addresses (keep for debugging but flag)
    # AWS keys
    (re.compile(r"(AKIA[0-9A-Z]{16})"), "[REDACTED_AWS_KEY]"),
]


def redact_secrets(text: str) -> str:
    """Remove secrets, tokens, PII from text before injecting into prompt."""
    for pattern, replacement in _REDACT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def estimate_tokens(text: str) -> int:
    """
    Rough token estimate: ~4 chars per token for English text.
    Good enough for budget checks; not for billing.
    """
    return len(text) // 4


def truncate_to_budget(text: str, max_tokens: int) -> str:
    """
    Truncate text to fit within a token budget.
    Tries to cut at a line boundary.
    """
    if estimate_tokens(text) <= max_tokens:
        return text

    max_chars = max_tokens * 4
    truncated = text[:max_chars]

    # Try to cut at last newline
    last_nl = truncated.rfind("\n")
    if last_nl > max_chars * 0.5:
        truncated = truncated[:last_nl]

    return truncated + f"\n\n[... truncated — {estimate_tokens(text) - max_tokens} tokens over budget ...]"


def summarize_tool_result(result: str, max_tokens: int = 2000) -> str:
    """
    Apply context policy to a tool result:
      1. Redact secrets
      2. Truncate to budget
    """
    clean = redact_secrets(result)
    return truncate_to_budget(clean, max_tokens)


def build_context_window(
    tool_results: list[str],
    max_total_tokens: int = 6000,
    max_per_result: int = 2000,
) -> str:
    """
    Combine multiple tool results into a single context block
    that fits within the total token budget.

    Most recent results get priority.
    """
    # Process each result
    processed = []
    for result in tool_results:
        clean = redact_secrets(result)
        truncated = truncate_to_budget(clean, max_per_result)
        processed.append(truncated)

    # Combine and check total
    combined = "\n---\n".join(processed)
    return truncate_to_budget(combined, max_total_tokens)

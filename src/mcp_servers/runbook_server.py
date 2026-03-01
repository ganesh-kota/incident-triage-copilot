"""
MCP Server — Runbooks

Tools:
  search_runbooks  — fuzzy search runbooks by keyword / error pattern
  get_runbook      — retrieve full runbook by ID
  list_runbooks    — list all available runbooks

Backed by Markdown files in data/runbooks/.
In production, this would hit Confluence / Notion / Git repo.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# ── Data path ──────────────────────────────────────────────────────
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "runbooks"

mcp = FastMCP(
    "runbook-server",
    instructions="Search and retrieve operational runbooks. Returns markdown content with step-by-step procedures.",
)


def _load_runbooks() -> dict[str, dict]:
    """Load all runbooks into memory with metadata."""
    runbooks = {}
    for p in sorted(DATA_DIR.glob("*.md")):
        content = p.read_text(encoding="utf-8")
        # Extract ID from filename: rb-001-high-error-rate.md → RB-001
        match = re.match(r"(rb-\d+)", p.stem)
        rb_id = match.group(1).upper() if match else p.stem.upper()

        # Extract title from first H1
        title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        title = title_match.group(1) if title_match else p.stem

        # Extract symptoms section for search
        symptoms = ""
        sym_match = re.search(r"## Symptoms\n(.*?)(?=\n##|\Z)", content, re.DOTALL)
        if sym_match:
            symptoms = sym_match.group(1).strip()

        runbooks[rb_id] = {
            "id": rb_id,
            "title": title,
            "filename": p.name,
            "symptoms": symptoms,
            "content": content,
        }
    return runbooks


# ── Tools ──────────────────────────────────────────────────────────

@mcp.tool()
def search_runbooks(query: str) -> str:
    """
    Search runbooks by keyword. Searches titles, symptoms, and full content.

    Returns matched runbooks ranked by relevance (title match > symptom match > body match).

    Args:
        query: Search terms (e.g. "connection refused", "OOMKilled", "high error rate").
    """
    runbooks = _load_runbooks()
    query_lower = query.lower()
    keywords = query_lower.split()

    results = []
    for rb_id, rb in runbooks.items():
        score = 0
        # Title match (highest weight)
        for kw in keywords:
            if kw in rb["title"].lower():
                score += 10
        # Symptoms match
        for kw in keywords:
            if kw in rb["symptoms"].lower():
                score += 5
        # Body match
        for kw in keywords:
            count = rb["content"].lower().count(kw)
            score += min(count, 3)  # cap at 3 per keyword

        if score > 0:
            # Extract relevant snippet (first matching paragraph)
            snippet = ""
            for line in rb["content"].split("\n"):
                if any(kw in line.lower() for kw in keywords):
                    snippet = line.strip()[:200]
                    break

            results.append({
                "id": rb_id,
                "title": rb["title"],
                "relevance_score": score,
                "matching_snippet": snippet,
                "symptoms_preview": rb["symptoms"][:300],
            })

    results.sort(key=lambda r: r["relevance_score"], reverse=True)

    return json.dumps({
        "query": query,
        "total_matches": len(results),
        "results": results[:5],  # top 5
    }, indent=2)


@mcp.tool()
def get_runbook(runbook_id: str) -> str:
    """
    Get the full content of a runbook by its ID.

    Args:
        runbook_id: Runbook identifier (e.g. "RB-001", "RB-002").
    """
    runbooks = _load_runbooks()
    rb_id = runbook_id.upper()

    if rb_id not in runbooks:
        available = list(runbooks.keys())
        return json.dumps({
            "error": f"Runbook '{rb_id}' not found",
            "available_runbooks": available,
        })

    rb = runbooks[rb_id]
    return json.dumps({
        "id": rb["id"],
        "title": rb["title"],
        "content": rb["content"],
    }, indent=2)


@mcp.tool()
def list_runbooks() -> str:
    """List all available runbooks with their IDs and titles."""
    runbooks = _load_runbooks()
    items = [
        {"id": rb["id"], "title": rb["title"], "symptoms_preview": rb["symptoms"][:150]}
        for rb in runbooks.values()
    ]
    return json.dumps({"runbooks": items}, indent=2)


# ── Run ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mcp.run()

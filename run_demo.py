#!/usr/bin/env python3
"""
Incident Triage Copilot — Demo Runner

Usage:
  python run_demo.py              # Interactive mode (needs API key in .env)
  python run_demo.py --mock       # Mock mode — no API key needed
  python run_demo.py --scenario 1 # Run pre-built scenario

This script:
  1. Starts all MCP servers (as subprocesses via MCP protocol)
  2. Connects the triage agent to them
  3. Runs a triage on a sample incident (or your own)
  4. Shows the full output with eval report
  5. Cleans up
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import (
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_API_VERSION,
    AZURE_OPENAI_DEPLOYMENT,
    AZURE_OPENAI_ENDPOINT,
    EFFECTIVE_API_KEY,
    ENABLE_EVAL_HOOKS,
    LLM_MODEL,
    LLM_PROVIDER,
    MOCK_MODE,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
)
from src.agent.triage_agent import TriageAgent
from src.observability.logger import setup_logging

logger = logging.getLogger("demo")


# ── Pre-built scenarios ────────────────────────────────────────────

SCENARIOS = {
    1: {
        "name": "Payment Service — Database Connection Failure",
        "alert_text": (
            "CRITICAL: payment-service error rate > 5%\n"
            "Current error rate: 12.3%\n"
            "Triggered at 2026-02-28T10:14:00Z\n"
            "Source: prometheus-alertmanager\n"
            "Team: payments | Tier: critical"
        ),
        "service_name": "payment-service",
        "environment": "production",
        "severity": "SEV1",
        "time_range_minutes": 30,
        "additional_context": "We deployed v2.3.1 at 09:55 UTC",
    },
    2: {
        "name": "Auth Service — Memory Leak / OOMKill",
        "alert_text": (
            "CRITICAL: auth-service OOMKilled\n"
            "Memory limit: 512MB, container exceeded limit\n"
            "Restart count: 3 in last hour\n"
            "Source: kubernetes-events"
        ),
        "service_name": "auth-service",
        "environment": "production",
        "severity": "SEV2",
        "time_range_minutes": 120,
    },
}


# ── Rich output rendering ─────────────────────────────────────────

def print_header():
    """Print the demo header."""
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text

        console = Console()
        title = Text("🚨 Incident Triage Copilot", style="bold red")
        subtitle = Text("MCP-Based • Evidence-Grounded • Eval-Gated", style="dim")
        console.print(Panel(
            Text.assemble(title, "\n", subtitle),
            border_style="red",
            expand=False,
        ))
    except ImportError:
        print("=" * 60)
        print("  🚨 Incident Triage Copilot")
        print("  MCP-Based • Evidence-Grounded • Eval-Gated")
        print("=" * 60)


def print_section(title: str, content: str):
    """Print a section with formatting."""
    try:
        from rich.console import Console
        from rich.markdown import Markdown
        from rich.panel import Panel

        console = Console()
        console.print(Panel(Markdown(content), title=title, border_style="blue"))
    except ImportError:
        print(f"\n{'─' * 60}")
        print(f"  {title}")
        print(f"{'─' * 60}")
        print(content)


def print_tool_calls(tool_calls: list[str]):
    """Display tool calls made during triage."""
    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        table = Table(title="MCP Tool Calls", show_lines=True)
        table.add_column("#", style="dim", width=3)
        table.add_column("Server", style="cyan")
        table.add_column("Tool", style="green")

        for i, tc in enumerate(tool_calls, 1):
            parts = tc.split("__", 1)
            server = parts[0] if len(parts) > 1 else "?"
            tool = parts[1] if len(parts) > 1 else tc
            table.add_row(str(i), server, tool)

        console.print(table)
    except ImportError:
        print("\nTool calls made:")
        for i, tc in enumerate(tool_calls, 1):
            print(f"  {i}. {tc}")


# ── Main ───────────────────────────────────────────────────────────

async def run_demo(args: argparse.Namespace):
    """Execute the demo."""

    # Determine mode
    mock_mode = args.mock or MOCK_MODE or not EFFECTIVE_API_KEY

    if mock_mode and not args.mock:
        logger.info("No API key found — running in mock mode (use --mock to suppress this)")

    # Create agent
    agent = TriageAgent(
        api_key=EFFECTIVE_API_KEY,
        base_url=OPENAI_BASE_URL,
        model=LLM_MODEL,
        mock_mode=mock_mode,
        enable_eval=ENABLE_EVAL_HOOKS,
        llm_provider=LLM_PROVIDER,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        azure_deployment=AZURE_OPENAI_DEPLOYMENT,
        azure_api_version=AZURE_OPENAI_API_VERSION,
    )

    try:
        # Step 1: Initialize MCP connections
        print_header()
        print("\n⏳ Connecting to MCP servers...")

        server_summary = await agent.initialize()

        print("✅ MCP servers connected:")
        for server, tools in server_summary.items():
            print(f"   • {server}: {', '.join(tools)}")

        # Step 2: Get or select the incident
        if args.scenario:
            scenario = SCENARIOS.get(args.scenario)
            if not scenario:
                print(f"❌ Unknown scenario {args.scenario}. Available: {list(SCENARIOS.keys())}")
                return
            print(f"\n📋 Scenario: {scenario['name']}")
            alert_text = scenario.pop("name")  # remove name, keep the rest
            alert_text_val = scenario.pop("alert_text")
            kwargs = scenario
        elif args.interactive:
            print("\n📝 Paste your alert text (press Enter twice to finish):")
            lines = []
            while True:
                line = input()
                if line == "":
                    if lines and lines[-1] == "":
                        break
                    lines.append(line)
                else:
                    lines.append(line)
            alert_text_val = "\n".join(lines).strip()
            kwargs = {}
            svc = input("Service name (or press Enter to let agent figure it out): ").strip()
            if svc:
                kwargs["service_name"] = svc
            sev = input("Severity (SEV1/SEV2/SEV3/SEV4 or Enter to skip): ").strip()
            if sev:
                kwargs["severity"] = sev
        else:
            # Default: run scenario 1
            scenario = SCENARIOS[1].copy()
            print(f"\n📋 Running default scenario: {scenario['name']}")
            alert_text_val = scenario.pop("alert_text")
            scenario.pop("name")
            kwargs = scenario

        mode_label = "🎭 MOCK MODE" if mock_mode else "🤖 LIVE MODE"
        print(f"\n{mode_label} — Starting triage...\n")

        # Step 3: Run triage
        result = await agent.triage(alert_text_val, **kwargs)

        # Step 4: Display results
        print_tool_calls(result["tool_calls_made"])
        print_section("Triage Report", result["triage_output"])

        if result.get("eval_report"):
            print_section("Evaluation", result["eval_report"])

        # Step 5: Optionally create ticket
        if args.create_ticket:
            print("\n🎫 Creating incident ticket...")
            ticket = await agent.create_ticket(result)
            if ticket:
                print_section("Ticket Created", ticket)

        print(f"\n✅ Triage complete — Incident ID: {result['incident_id']}")
        print(f"   Tool calls: {result['tool_call_count']} | Mode: {'mock' if mock_mode else 'live'}")

    except Exception as e:
        logger.error(f"Triage failed: {e}", exc_info=True)
        print(f"\n❌ Error: {e}")
    finally:
        await agent.shutdown()


def main():
    parser = argparse.ArgumentParser(
        description="Incident Triage Copilot — MCP Demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_demo.py --mock              # No API key needed
  python run_demo.py --scenario 1        # Payment service incident
  python run_demo.py --scenario 2        # Auth service OOM
  python run_demo.py --interactive       # Paste your own alert
  python run_demo.py --create-ticket     # Also create a ticket
        """,
    )
    parser.add_argument("--mock", action="store_true", help="Use mock mode (no LLM API key needed)")
    parser.add_argument("--scenario", type=int, choices=[1, 2], help="Run a pre-built scenario")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode — paste your own alert")
    parser.add_argument("--create-ticket", action="store_true", help="Create an incident ticket after triage")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--structured-logs", action="store_true", help="Use JSON structured logging")

    args = parser.parse_args()

    setup_logging(level=args.log_level, structured=args.structured_logs)
    asyncio.run(run_demo(args))


if __name__ == "__main__":
    main()

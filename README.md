# 🚨 Incident Triage Copilot (MCP-Based)

A production-grade, chat-based SRE/DevOps triage assistant built on the
**Model Context Protocol (MCP)**.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        On-Call Engineer                         │
│                     (pastes alert / logs)                       │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Triage Agent (LLM)                          │
│  • Understands incident contract (input → output)               │
│  • Calls tools via MCP Client                                   │
│  • Applies context policy (token budget, redaction)             │
│  • Grounds every claim with citations                           │
│  • Maintains conversation + task + tool-results state           │
└──────────────────────────┬──────────────────────────────────────┘
                           │  MCP Client
                           │  (discovers & calls tools)
              ┌────────────┼────────────┬──────────────┐
              ▼            ▼            ▼              ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐
        │  Logs    │ │ Runbook  │ │ Metrics  │ │  Ticketing   │
        │  Server  │ │  Server  │ │  Server  │ │   Server     │
        │  (MCP)   │ │  (MCP)   │ │  (MCP)   │ │   (MCP)      │
        └──────────┘ └──────────┘ └──────────┘ └──────────────┘
              │            │            │              │
              ▼            ▼            ▼              ▼
        Log storage   Runbook repo   Prometheus/   Jira/PagerDuty/
        (files/ELK)   (markdown)     Datadog       ServiceNow
```

## Key MCP Concepts Mapped

| MCP Concept    | Our Implementation                        |
| -------------- | ----------------------------------------- |
| **MCP Server** | Each tool domain is its own server process |
| **Tool**       | A callable function (query_logs, etc.)     |
| **Resource**   | Runbook content, log files                 |
| **MCP Client** | Lives inside the agent, discovers tools    |
| **Transport**  | stdio (local) or SSE (remote)              |

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Copy env file and add your API key
cp .env.example .env

# 3. Run the demo (mock mode — no API key needed)
python run_demo.py --mock

# 4. Run with a real LLM
python run_demo.py
```

## Project Structure

```
incident-triage-copilot/
├── docs/                     # Architecture + contract docs
├── data/                     # Mock data (logs, runbooks, alerts, metrics)
├── src/
│   ├── models/               # Pydantic models — the "incident contract"
│   ├── mcp_servers/          # MCP server implementations (Phase 1)
│   ├── mcp_client/           # Client that connects agent ↔ servers
│   └── agent/                # Triage agent, prompts, context policy
├── tests/
├── run_demo.py               # End-to-end demo runner
└── requirements.txt
```

## Phases

- **Phase 0** — Incident contract (data models, input/output spec)
- **Phase 1** — Single-agent MVP with 3 MCP servers (logs, runbooks, ticketing)
- **Phase 2** — Context policy, grounding, state management
- **Phase 3** — Multi-agent scaling
- **Phase 4** — Production hardening (eval hooks, observability)

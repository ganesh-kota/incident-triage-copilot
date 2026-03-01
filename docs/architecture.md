# Architecture — Incident Triage Copilot

## Why MCP? (Model Context Protocol)

Traditional approach:
```
Agent → hardcoded function calls → your code → external APIs
```

MCP approach:
```
Agent → MCP Client → MCP Servers (standardized protocol) → external APIs
```

### The difference matters because:

1. **Standardization** — Every tool speaks the same protocol. A Jira tool
   and a PagerDuty tool have the same interface shape. Swap one for another
   without changing the agent.

2. **Security boundary** — The MCP server enforces auth, rate limits, and
   data redaction. The LLM never sees raw credentials.

3. **Discoverability** — The agent asks "what tools do you have?" at startup.
   New tools appear automatically. No code changes in the agent.

4. **Isolation** — Each server is its own process. A buggy log parser can't
   crash the runbook server.

## Component Map

```
┌─────────────────────────────────────────────────────────┐
│                     AGENT RUNTIME                       │
│                                                         │
│  ┌───────────────┐   ┌──────────────┐   ┌───────────┐  │
│  │  Triage Agent │──▶│ Context      │──▶│  State    │  │
│  │  (LLM loop)   │   │ Policy       │   │  Manager  │  │
│  └───────┬───────┘   └──────────────┘   └───────────┘  │
│          │                                              │
│          ▼                                              │
│  ┌───────────────┐                                      │
│  │  MCP Client   │  ◀── discovers tools at startup      │
│  │  (session)    │  ◀── calls tools during reasoning    │
│  └───────┬───────┘                                      │
└──────────┼──────────────────────────────────────────────┘
           │
           │  MCP Protocol (JSON-RPC over stdio or SSE)
           │
     ┌─────┴─────┬──────────────┬──────────────┐
     ▼           ▼              ▼              ▼
┌─────────┐ ┌─────────┐ ┌──────────┐ ┌──────────────┐
│  Logs   │ │Runbook  │ │ Metrics  │ │  Ticketing   │
│ Server  │ │ Server  │ │  Server  │ │   Server     │
├─────────┤ ├─────────┤ ├──────────┤ ├──────────────┤
│ Tools:  │ │ Tools:  │ │ Tools:   │ │ Tools:       │
│ •query  │ │ •search │ │ •query   │ │ •create      │
│  _logs  │ │  _rb    │ │  _metrics│ │  _incident   │
│ •extract│ │ •get_rb │ │ •get     │ │ •update      │
│  _errors│ │         │ │  _alerts │ │  _incident   │
└─────────┘ └─────────┘ └──────────┘ └──────────────┘
     │           │              │              │
     ▼           ▼              ▼              ▼
  Log files   Markdown      JSON time      In-memory
  (mock/ELK)  runbooks      series data    ticket store
```

## Data Flow for a Single Triage

```
1. Engineer pastes alert text
   ↓
2. Agent parses → creates IncidentInput (Phase 0 contract)
   ↓
3. Agent decides which tools to call (tool-use reasoning)
   ↓
4. MCP Client → Logs Server: query_logs(service, timerange)
   MCP Client → Runbook Server: search_runbooks(error pattern)
   ↓  (these can happen in parallel)
5. Tool results come back as structured JSON
   ↓
6. Agent applies context policy:
   - Summarize if over token budget
   - Redact any secrets/PII
   ↓
7. Agent reasons over evidence → produces TriageOutput
   - Ranked causes WITH citations
   - Next steps
   - Safe mitigations
   ↓
8. Output rendered to engineer
9. (Optional) Agent calls ticketing_server to create/update ticket
```

## MCP Protocol Details

Each MCP server exposes:

| Capability   | Description                            | Example                          |
|-------------|----------------------------------------|----------------------------------|
| **Tools**    | Functions the LLM can call             | `query_logs(service, timerange)` |
| **Resources**| Data the server can provide            | `runbook://rb-001`               |
| **Prompts**  | Pre-built prompt templates             | `triage_template`                |

Communication happens via **JSON-RPC 2.0**:

```json
// Client → Server (tool call)
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "query_logs",
    "arguments": {
      "service": "payment-service",
      "start_time": "2026-02-28T10:00:00Z",
      "end_time": "2026-02-28T10:30:00Z"
    }
  },
  "id": 1
}

// Server → Client (result)
{
  "jsonrpc": "2.0",
  "result": {
    "content": [
      {
        "type": "text",
        "text": "[{\"level\": \"ERROR\", \"message\": \"Connection refused...\"}]"
      }
    ]
  },
  "id": 1
}
```

## Why This Architecture Beats "Just Call Functions"

| Concern           | Plain Functions          | MCP Servers                     |
|-------------------|--------------------------|---------------------------------|
| Auth              | You handle it            | Server handles it               |
| Schema discovery  | Hardcoded in agent       | Agent discovers at runtime      |
| Isolation         | Same process             | Separate process                |
| Swap backends     | Rewrite agent code       | Swap server, agent unchanged    |
| Multi-team        | Everyone edits one repo  | Each team owns their server     |
| Audit/logging     | DIY                      | Server-level middleware         |

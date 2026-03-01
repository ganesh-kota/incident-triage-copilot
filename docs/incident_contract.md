# Incident Contract — Phase 0

## Why a "Contract"?

An incident triage system without a contract is like an API without a schema.
You don't know what to send it, and you can't trust what comes back.

The contract defines:
- **Inputs**: what the on-call engineer provides
- **Outputs**: what the system MUST produce (every time, no exceptions)

This is the single most important design decision. Everything else
(tools, agents, prompts) exists to fulfill this contract.

---

## Input Contract

### Required Fields

| Field         | Type   | Example                                         |
|---------------|--------|--------------------------------------------------|
| `alert_text`  | string | "CRITICAL: payment-service error rate > 5%..."   |

### Optional Fields (agent may ask for these)

| Field               | Type   | Default       | Example                      |
|---------------------|--------|---------------|-------------------------------|
| `stack_trace`       | string | null          | "Traceback (most recent...)..." |
| `service_name`      | string | null          | "payment-service"             |
| `environment`       | enum   | "production"  | "production" / "staging"      |
| `time_range_minutes`| int    | 15            | 60                            |
| `additional_context`| string | null          | "We deployed v2.3.1 at 10:05" |

### Why these fields?

- `alert_text` is the only hard requirement because that's what pager gives you.
- Everything else the agent can either infer or ask about.
- `time_range_minutes` defaults to 15 because most alerts fire within a narrow window.

---

## Output Contract

The system MUST produce ALL of these sections. No partial answers.

### 1. Incident Summary (1–2 sentences)
```
Payment-service is returning 503 errors at a rate of 12% due to
PostgreSQL primary connection failures starting at 10:15 UTC.
```

### 2. Evidence (with citations)
Each piece of evidence must cite its source:
```
- [LOGS] 47 occurrences of "Connection refused to postgres-primary:5432"
  between 10:15 and 10:28 UTC (source: logs_server/query_logs)
- [RUNBOOK] Matches runbook RB-002 "Database Connection Pool Exhaustion"
  (source: runbook_server/search_runbooks)
```

### 3. Likely Causes (ranked)
```
1. [HIGH confidence] PostgreSQL primary is down or unreachable
   Evidence: connection refused errors, no successful queries since 10:15
2. [MEDIUM confidence] Connection pool exhausted
   Evidence: matches pattern in RB-002, but pool metrics not yet checked
```

### 4. Next Diagnostic Steps
```
1. Check PostgreSQL primary pod status (kubectl get pods -n data)
2. Query connection pool metrics (pg_stat_activity)
3. Check if recent deployment touched DB config
```

### 5. Safe Mitigations (low risk first)
```
1. [LOW RISK] Failover to PostgreSQL read replica for read traffic
2. [MEDIUM RISK] Restart payment-service pods to reset connections
3. [HIGH RISK — needs confirmation] Force PostgreSQL primary restart
```

### 6. Stakeholder Update Draft
```
🔴 Incident Update — Payment Service
Status: Investigating
Impact: Payment processing failures (~12% of requests)
Cause: Likely database connectivity issue
ETA: Investigating, update in 15 minutes
```

---

## Why Every Section is Mandatory

| Section             | If missing, what happens                        |
|---------------------|-------------------------------------------------|
| Summary             | On-call has to read everything to understand     |
| Evidence            | No way to verify claims — trust drops to zero    |
| Ranked causes       | On-call chases wrong lead, MTTR goes up          |
| Diagnostic steps    | Junior on-call is stuck, has to escalate         |
| Mitigations         | Risky action taken without understanding impact  |
| Stakeholder update  | Comms are delayed, leadership loses confidence   |

---

## Severity Policy (built into the contract)

The agent must respect severity when suggesting mitigations:

| Severity | Allowed mitigations                          |
|----------|----------------------------------------------|
| SEV1     | Only low-risk steps without confirmation     |
| SEV2     | Low + medium risk, high risk needs confirm   |
| SEV3     | All steps, confirm before high risk          |
| SEV4     | All steps                                    |

This prevents the agent from suggesting "restart production database"
for a SEV1 without explicit human confirmation.

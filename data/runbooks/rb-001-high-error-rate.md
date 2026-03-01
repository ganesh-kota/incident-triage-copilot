# RB-001: High Error Rate Investigation

## Symptoms
- Error rate exceeds 5% threshold
- HTTP 5xx responses increasing
- Alerts from monitoring (PagerDuty / Datadog / Prometheus)

## Diagnosis Steps

### Step 1: Identify the error type
```bash
# Check recent error logs
kubectl logs -l app=<service-name> --since=15m | grep -i error | head -50
```

### Step 2: Check dependencies
```bash
# Verify upstream/downstream services
kubectl get pods -n <namespace> -o wide
kubectl top pods -n <namespace>
```

### Step 3: Check recent deployments
```bash
# Was there a recent deploy?
kubectl rollout history deployment/<service-name>
```

### Step 4: Check resource utilization
```bash
# CPU and memory
kubectl top pods -l app=<service-name>
# Disk (if applicable)
df -h
```

## Common Root Causes

| Cause | Frequency | Typical Fix |
|-------|-----------|-------------|
| Dependency down | 35% | Failover or wait for dependency recovery |
| Bad deployment | 25% | Rollback to previous version |
| Resource exhaustion | 20% | Scale up or fix leak |
| Config change | 10% | Revert config |
| Data issue | 10% | Fix data, add validation |

## Mitigation Playbook

### If dependency is down:
1. **LOW RISK**: Enable circuit breaker / return cached responses
2. **MEDIUM RISK**: Failover to backup service
3. **HIGH RISK**: Manual database failover

### If bad deployment:
1. **LOW RISK**: Rollback to previous version
   ```bash
   kubectl rollout undo deployment/<service-name>
   ```

### If resource exhaustion:
1. **LOW RISK**: Scale horizontally
   ```bash
   kubectl scale deployment/<service-name> --replicas=<N+2>
   ```
2. **MEDIUM RISK**: Restart pods (clears memory)

## Escalation
- If not resolved in 15 min → escalate to service owner
- If SEV1 → page on-call manager immediately

# RB-002: Database Connection Failures

## Symptoms
- `ECONNREFUSED` errors to database host
- Connection pool exhaustion warnings
- Circuit breaker opening for database connections
- 503 errors returned to clients

## Diagnosis Steps

### Step 1: Check database pod/instance status
```bash
# Kubernetes
kubectl get pods -n data -l app=postgres
kubectl describe pod <postgres-pod-name> -n data

# Check if the DB process is running
kubectl exec -n data <postgres-pod> -- pg_isready -h localhost -p 5432
```

### Step 2: Check connection pool metrics
```sql
-- Active connections
SELECT count(*) FROM pg_stat_activity;

-- Connection state breakdown
SELECT state, count(*)
FROM pg_stat_activity
GROUP BY state;

-- Max connections setting
SHOW max_connections;
```

### Step 3: Check database logs
```bash
kubectl logs <postgres-pod> -n data --since=30m | grep -E "FATAL|ERROR|PANIC"
```

### Step 4: Check disk space
```bash
kubectl exec -n data <postgres-pod> -- df -h /var/lib/postgresql/data
```

### Step 5: Check for long-running queries
```sql
SELECT pid, now() - pg_stat_activity.query_start AS duration, query
FROM pg_stat_activity
WHERE state != 'idle'
ORDER BY duration DESC
LIMIT 10;
```

## Common Root Causes

| Cause | Frequency | Indicators |
|-------|-----------|------------|
| DB pod crashed / OOMKilled | 30% | Pod in CrashLoopBackOff, OOMKilled events |
| Connection pool exhausted | 25% | Pool at 100%, leaked connections |
| Disk full | 15% | WAL files accumulated, disk > 95% |
| Network partition | 10% | Other pods also failing, node issues |
| Max connections reached | 10% | pg_stat_activity at limit |
| Bad migration | 10% | Recent schema change, locks held |

## Mitigation Playbook

### If DB pod is down:
1. **LOW RISK**: Check if auto-restart is working
   ```bash
   kubectl get events -n data --sort-by='.lastTimestamp' | head -20
   ```
2. **MEDIUM RISK**: Failover to read replica for read traffic
3. **HIGH RISK — NEEDS CONFIRMATION**: Force restart PostgreSQL pod
   ```bash
   kubectl delete pod <postgres-pod> -n data
   ```

### If connection pool exhausted:
1. **LOW RISK**: Increase pool size temporarily
2. **MEDIUM RISK**: Kill idle connections
   ```sql
   SELECT pg_terminate_backend(pid) 
   FROM pg_stat_activity 
   WHERE state = 'idle' 
   AND query_start < now() - interval '10 minutes';
   ```

### If disk full:
1. **LOW RISK**: Clear old WAL files / vacuum
   ```sql
   VACUUM FULL;
   ```
2. **MEDIUM RISK**: Expand PVC

## Escalation
- If primary DB is unrecoverable in 10 min → trigger DR failover
- Page DBA on-call for any data corruption indicators

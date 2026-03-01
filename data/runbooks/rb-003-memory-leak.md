# RB-003: Memory Leak / OOMKill Investigation

## Symptoms
- Container OOMKilled repeatedly
- Heap/RSS memory growing linearly over time
- GC pauses increasing
- Request latency degrading over hours
- CrashLoopBackOff with OOMKilled reason

## Diagnosis Steps

### Step 1: Confirm OOMKill
```bash
kubectl describe pod <pod-name> | grep -A 5 "Last State"
# Look for: Reason: OOMKilled
kubectl get events --sort-by='.lastTimestamp' | grep OOM
```

### Step 2: Check memory usage pattern
```bash
# Current usage
kubectl top pod <pod-name>

# Historical (if metrics-server or Prometheus available)
# Check if memory grows linearly — that's a leak
```

### Step 3: Get heap dump (Java/Node)
```bash
# Java
kubectl exec <pod> -- jmap -dump:live,format=b,file=/tmp/heap.hprof <pid>

# Node.js
kubectl exec <pod> -- node --inspect <app.js>
# Then connect Chrome DevTools
```

### Step 4: Check for recent code changes
```bash
kubectl rollout history deployment/<service>
# Compare with when memory issues started
```

### Step 5: Check for goroutine/thread leak
```bash
# Go services
curl localhost:6060/debug/pprof/goroutine?debug=2

# Java
kubectl exec <pod> -- jstack <pid>
```

## Common Root Causes

| Cause | Frequency | Pattern |
|-------|-----------|---------|
| Unbounded cache | 30% | Memory grows with traffic, never drops |
| Connection leak | 25% | Each request leaks a connection object |
| Large object accumulation | 20% | Processing large payloads without streaming |
| Goroutine/thread leak | 15% | Thread count grows linearly |
| Memory limit too low | 10% | Legitimate usage exceeds limit |

## Mitigation Playbook

### Immediate (stop the bleeding):
1. **LOW RISK**: Increase memory limit temporarily
   ```yaml
   resources:
     limits:
       memory: "1Gi"  # was 512Mi
   ```
2. **LOW RISK**: Scale out to distribute load
   ```bash
   kubectl scale deployment/<service> --replicas=5
   ```
3. **MEDIUM RISK**: Rolling restart (clears memory temporarily)
   ```bash
   kubectl rollout restart deployment/<service>
   ```

### If caused by recent deployment:
1. **LOW RISK**: Rollback
   ```bash
   kubectl rollout undo deployment/<service>
   ```

### Long-term fix:
- Profile the application with heap dumps
- Add bounded caches (LRU with max size)
- Fix connection pooling
- Add memory alerts at 70% threshold

## Escalation
- If restart cycle < 5 min → page service owner immediately
- If multiple services affected → possible node-level issue, page platform team

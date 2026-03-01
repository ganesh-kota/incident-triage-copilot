# RB-004: Deployment Rollback Procedure

## When to Rollback
- Error rate increased after deployment
- Latency p99 increased > 2x after deployment
- New crash signatures appearing post-deploy
- Customer-facing functionality broken

## Pre-Rollback Checklist
1. ✅ Confirm the deployment is the cause (not a coincident issue)
2. ✅ Notify the team in #incidents channel
3. ✅ Check if the deployment included database migrations
   - If YES: migrations may NOT be reversible — consult DBA
   - If NO: safe to rollback

## Rollback Steps

### Kubernetes Deployment
```bash
# Check rollout history
kubectl rollout history deployment/<service-name>

# Rollback to previous version
kubectl rollout undo deployment/<service-name>

# Rollback to specific revision
kubectl rollout undo deployment/<service-name> --to-revision=<N>

# Verify rollback
kubectl rollout status deployment/<service-name>
kubectl get pods -l app=<service-name>
```

### ArgoCD
```bash
# List application history
argocd app history <app-name>

# Rollback
argocd app rollback <app-name> <revision-id>
```

### Helm
```bash
# List revisions
helm history <release-name>

# Rollback
helm rollback <release-name> <revision>
```

## Post-Rollback Verification
1. Error rate returning to baseline
2. Latency returning to baseline
3. Health checks passing
4. No new error signatures in logs

## Post-Rollback Communication
```
✅ Rollback Complete — <Service Name>
Previous version: v2.3.1 (deployed at 10:05 UTC)
Rolled back to: v2.3.0 
Reason: <brief reason>
Status: Monitoring for stability
Next steps: RCA scheduled for <date>
```

## Escalation
- If rollback fails → page platform/infra team
- If rollback doesn't fix the issue → it wasn't the deployment, investigate further

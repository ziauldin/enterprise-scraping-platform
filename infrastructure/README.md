# Infrastructure

This directory contains all deployment and infrastructure configurations for ParseHub Dashboard.

## Directory Structure

```
infrastructure/
├── kubernetes/          # Kubernetes manifests
│   ├── README.md
│   ├── backend-deployment.yaml
│   ├── backend-service.yaml
│   ├── backend-hpa.yaml
│   ├── frontend-deployment.yaml
│   ├── frontend-service.yaml
│   ├── configmap.yaml
│   ├── secrets.yaml
│   └── namespace.yaml
├── docker/              # Docker configurations
│   ├── Dockerfile-backend
│   ├── Dockerfile-frontend
│   └── .dockerignore
└── scripts/             # Deployment automation
    ├── deploy.sh
    ├── rollback.sh
    └── health-check.sh
```

## Quick Start

### Local Development with Docker Compose

```bash
# From project root
docker-compose up -d

# Check services
docker-compose ps

# View logs
docker-compose logs -f backend
docker-compose logs -f frontend

# Stop services
docker-compose down
```

### Kubernetes Deployment

```bash
# 1. Create namespace
kubectl create namespace parsehub

# 2. Create secrets (update with your values)
kubectl create secret generic snowflake-credentials \
  --from-literal=account=VFHSGYP-GD78100 \
  --from-literal=user=ziauldin \
  --from-literal=password=YOUR_PASSWORD \
  -n parsehub

# 3. Deploy application
kubectl apply -f infrastructure/kubernetes/

# 4. Verify
kubectl get pods -n parsehub
kubectl get svc -n parsehub
```

## Services Included

### Backend
- Method: YAML manifest deployment
- Replicas: 2 (auto-scaling 2-10)
- Health checks: Liveness & Readiness probes
- Resource limits: 512Mi memory, 500m CPU

### Frontend
- Method: YAML manifest deployment  
- Replicas: 2
- Health checks: HTTP /health endpoint
- Resource limits: 256Mi memory, 200m CPU

## Database

- **Development**: SQLite (file-based)
- **Production**: Snowflake (managed data warehouse)

Snowflake credentials must be configured as K8s secrets.

## Configuration Management

### ConfigMap
- Application settings
- Log levels
- Feature flags

### Secrets
- Snowflake credentials
- API keys
- Database passwords

## Scaling

### Manual Scaling
```bash
kubectl scale deployment parsehub-backend --replicas=5 -n parsehub
```

### Auto-Scaling (HPA)
Configured to scale based on:
- CPU utilization > 70%
- Memory utilization > 80%

## Monitoring

### View Logs
```bash
kubectl logs -f deployment/parsehub-backend -n parsehub
kubectl logs -f deployment/parsehub-frontend -n parsehub
```

### Check Resources
```bash
kubectl top nodes
kubectl top pods -n parsehub
```

### Pod Details
```bash
kubectl describe pod <pod-name> -n parsehub
kubectl exec -it <pod-name> -n parsehub -- bash
```

## CI/CD Integration

Deployment can be automated via:
- GitHub Actions
- GitLab CI/CD
- Jenkins
- ArgoCD

See `.github/workflows/` for example configuration.

## Troubleshooting

### Pod Crashes
```bash
# Check logs
kubectl logs <pod-name> -n parsehub

# Get pod events
kubectl describe pod <pod-name> -n parsehub

# Common causes:
# - Missing environment variables
# - Database connection issues
# - Configuration errors
```

### Service Not Accessible
```bash
# Verify service exists and has endpoints
kubectl get svc -n parsehub
kubectl describe svc <service-name> -n parsehub

# Test connectivity
kubectl exec -it <pod-name> -n parsehub -- curl http://localhost:5000/health
```

### Database Connection Issues
```bash
# Verify secrets are created
kubectl get secrets -n parsehub
kubectl get secret snowflake-credentials -n parsehub -o yaml

# Check pod environment variables
kubectl exec <pod-name> -n parsehub -- env | grep SNOW
```

## Upgrades & Rollbacks

### Upgrade
```bash
# Update image
kubectl set image deployment/parsehub-backend \
  parsehub-backend=registry/parsehub-backend:v1.1.0 \
  -n parsehub

# Watch rollout
kubectl rollout status deployment/parsehub-backend -n parsehub
```

### Rollback
```bash
# Instant rollback to previous version
kubectl rollout undo deployment/parsehub-backend -n parsehub

# Rollback to specific revision
kubectl rollout history deployment/parsehub-backend -n parsehub
kubectl rollout undo deployment/parsehub-backend --to-revision=5 -n parsehub
```

## Performance Tuning

1. **Resource Requests/Limits**
   - Edit deployment YAML files
   - Balance performance vs cost

2. **Replicas**
   - Increase replicas for higher load
   - Use HPA for automatic scaling

3. **Database**
   - Use Snowflake clustering for faster queries
   - Optimize indexes

## Security

### Network Policies
Configured to restrict traffic:
- Ingress: Only from Ingress controller
- Egress: Only to required services

### RBAC
Minimal permissions for service accounts.

### Secrets
All sensitive data stored as K8s Secrets (encrypted).

## Cost Optimization

1. Use spot instances for non-critical workloads
2. Configure Pod Disruption Budgets
3. Use resource requests/limits appropriately
4. Monitor and optimize database usage

## Documentation

- [Backend Setup](../docs/BACKEND.md)
- [Full Infrastructure Guide](../docs/INFRASTRUCTURE.md)
- [Deployment Guide](../docs/DEPLOYMENT.md)

---

**Last Updated:** March 8, 2026

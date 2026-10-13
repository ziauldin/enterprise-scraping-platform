#!/bin/bash
# Deploy ParseHub to Kubernetes
# Usage: ./deploy.sh <environment> [namespace]

set -e

ENVIRONMENT=${1:-local}
NAMESPACE=${2:-parsehub}

echo "=========================================="
echo "Deploying ParseHub to Kubernetes"
echo "=========================================="
echo "Environment: $ENVIRONMENT"
echo "Namespace: $NAMESPACE"
echo ""

# Check if namespace exists
if ! kubectl get namespace "$NAMESPACE" > /dev/null 2>&1; then
    echo "Creating namespace: $NAMESPACE"
    kubectl create namespace "$NAMESPACE"
fi

# Determine overlay path
OVERLAY_PATH="../overlays/$ENVIRONMENT"

if [ ! -d "$OVERLAY_PATH" ]; then
    echo "❌ ERROR: Overlay directory not found: $OVERLAY_PATH"
    echo "Available environments: local, development, production"
    exit 1
fi

echo ""
echo "Deploying from: $OVERLAY_PATH"
echo ""

# Apply manifests using kustomize
kubectl apply -k "$OVERLAY_PATH" -n "$NAMESPACE"

echo ""
echo "=========================================="
echo "Deployment Started!"
echo "=========================================="
echo ""
echo "Waiting for deployments to be ready..."
echo ""

# Wait for deployments
kubectl rollout status deployment/backend -n "$NAMESPACE" --timeout=5m &
BACKEND_PID=$!

kubectl rollout status deployment/frontend -n "$NAMESPACE" --timeout=5m &
FRONTEND_PID=$!

wait $BACKEND_PID $FRONTEND_PID

echo ""
echo "=========================================="
echo "✓ All deployments are ready!"
echo "=========================================="
echo ""
echo "Check status with:"
echo "  kubectl get all -n $NAMESPACE"
echo ""
echo "View logs with:"
echo "  kubectl logs -f deployment/backend -n $NAMESPACE"
echo "  kubectl logs -f deployment/frontend -n $NAMESPACE"
echo ""
echo "Port forward for testing:"
echo "  kubectl port-forward svc/frontend-svc 3000:3000 -n $NAMESPACE"
echo "  kubectl port-forward svc/backend-svc 5000:5000 -n $NAMESPACE"

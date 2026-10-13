#!/bin/bash
# Cleanup ParseHub Kubernetes Deployment
# Usage: ./cleanup.sh <namespace>

set -e

NAMESPACE=${1:-parsehub}

echo "=========================================="
echo "Removing ParseHub from Kubernetes"
echo "=========================================="
echo "Namespace: $NAMESPACE"
echo ""

read -p "Are you sure you want to delete all resources in namespace '$NAMESPACE'? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Cleanup cancelled"
    exit 0
fi

echo ""
echo "Deleting all resources in namespace: $NAMESPACE"
echo ""

# Delete namespace (this deletes all resources in it)
kubectl delete namespace "$NAMESPACE" --ignore-not-found=true

echo ""
echo "=========================================="
echo "✓ Cleanup complete!"
echo "=========================================="

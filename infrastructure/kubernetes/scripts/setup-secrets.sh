#!/bin/bash
# Setup Kubernetes Secrets for ParseHub
# Usage: ./setup-secrets.sh [namespace]
# Run this once manually before first deployment, or whenever you rotate keys.

set -e

NAMESPACE=${1:-parsehub}

echo "=========================================="
echo " ParseHub — Create Kubernetes Secrets"
echo "=========================================="
echo " Namespace: $NAMESPACE"
echo ""

# Ensure namespace exists
if ! kubectl get namespace "$NAMESPACE" > /dev/null 2>&1; then
    echo "Creating namespace: $NAMESPACE"
    kubectl create namespace "$NAMESPACE"
else
    echo "Namespace already exists: $NAMESPACE"
fi

echo ""
echo "=========================================="
echo " Application Secrets (parsehub-secrets)"
echo "=========================================="
echo " These values will never be stored in git."
echo ""

read -sp "Enter ParseHub API Key (PARSEHUB_API_KEY): " PARSEHUB_API_KEY
echo ""
if [[ -z "$PARSEHUB_API_KEY" ]]; then
    echo "ERROR: PARSEHUB_API_KEY cannot be empty." >&2
    exit 1
fi

read -sp "Enter Backend API Key (BACKEND_API_KEY): " BACKEND_API_KEY
echo ""
if [[ -z "$BACKEND_API_KEY" ]]; then
    echo "ERROR: BACKEND_API_KEY cannot be empty." >&2
    exit 1
fi

read -sp "Enter Automation Internal Key (AUTOMATION_INTERNAL_KEY, optional): " AUTOMATION_INTERNAL_KEY
echo ""

read -sp "Enter ParseHub Webhook Secret (PARSEHUB_WEBHOOK_SECRET, optional): " PARSEHUB_WEBHOOK_SECRET
echo ""

kubectl create secret generic parsehub-secrets \
  --from-literal=PARSEHUB_API_KEY="$PARSEHUB_API_KEY" \
  --from-literal=BACKEND_API_KEY="$BACKEND_API_KEY" \
    --from-literal=AUTOMATION_INTERNAL_KEY="$AUTOMATION_INTERNAL_KEY" \
    --from-literal=PARSEHUB_WEBHOOK_SECRET="$PARSEHUB_WEBHOOK_SECRET" \
  -n "$NAMESPACE" \
  --dry-run=client \
  -o yaml | kubectl apply -f -

echo "✓ parsehub-secrets created/updated"
echo ""
echo "=========================================="
echo " All secrets applied successfully!"
echo "=========================================="
echo ""
echo " NEXT STEPS:"
echo " Add these as GitHub Actions secrets in your repo settings:"
echo "   PARSEHUB_API_KEY  — your ParseHub API key"
echo "   BACKEND_API_KEY   — your internal backend auth key"
echo "   AUTOMATION_INTERNAL_KEY — optional key for internal automation calls"
echo "   PARSEHUB_WEBHOOK_SECRET — optional key for webhook receiver auth"
echo " The CI/CD pipeline will apply them automatically on each deploy."

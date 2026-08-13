#!/usr/bin/env bash
# ═════════════════════════════════════════════════════════════════════
#  ECR Login — creates/refreshes the imagePullSecret for KinD nodes
#
#  Run this ONCE before deploying, and again every 12h if needed
#  (ECR tokens expire after 12 hours).
#
#  Usage:
#    bash argocd/ecr-login.sh
# ═════════════════════════════════════════════════════════════════════
set -euo pipefail

AWS_REGION="us-east-1"
AWS_ACCOUNT="839706991042"
ECR_REGISTRY="${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com"
NAMESPACE="traffic-violation"
SECRET_NAME="ecr-credentials"

echo "▶ Getting ECR login token..."
ECR_PASSWORD=$(aws ecr get-login-password --region "${AWS_REGION}")

echo "▶ Creating namespace if missing..."
kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

echo "▶ Creating/refreshing imagePullSecret '${SECRET_NAME}' in namespace '${NAMESPACE}'..."
kubectl create secret docker-registry "${SECRET_NAME}" \
  --namespace "${NAMESPACE}" \
  --docker-server="${ECR_REGISTRY}" \
  --docker-username=AWS \
  --docker-password="${ECR_PASSWORD}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "✔ Done. ECR pull secret is ready (valid for 12 hours)."

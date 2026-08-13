#!/usr/bin/env bash
# ═════════════════════════════════════════════════════════════════════
#  deploy.sh — One-shot deployment script for Traffic Violation System
#
#  Run this ONCE after bootstrap-kind-platform.sh completes.
#  It handles everything automatically — no manual kubectl, no sed,
#  no patching needed.
#
#  Usage:
#    bash argocd/deploy.sh \
#      --access-key  AKIAXXXXXXXXXXXXXXXXX \
#      --secret-key  "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
#
#  Or export env vars first:
#    export AWS_ACCESS_KEY_ID=AKIAXXXXXXXXXXXXXXXXX
#    export AWS_SECRET_ACCESS_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
#    bash argocd/deploy.sh
# ═════════════════════════════════════════════════════════════════════
set -euo pipefail

# ── Colours ──────────────────────────────────────────────────────────
GREEN='\033[1;32m'; BLUE='\033[1;34m'; RED='\033[1;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${BLUE}▶${NC} $*"; }
ok()   { echo -e "${GREEN}✔${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
die()  { echo -e "${RED}✘${NC} $*" >&2; exit 1; }

# ── Parse args ───────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --access-key)  AWS_ACCESS_KEY_ID="$2";     shift 2 ;;
    --secret-key)  AWS_SECRET_ACCESS_KEY="$2"; shift 2 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

# ── Config ───────────────────────────────────────────────────────────
AWS_REGION="us-east-1"
AWS_ACCOUNT="839706991042"
ECR_REGISTRY="${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com"
APP_NS="traffic-violation"
ARGOCD_NS="argocd"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ── Validate AWS credentials ──────────────────────────────────────────
[[ -n "${AWS_ACCESS_KEY_ID:-}"     ]] || die "AWS_ACCESS_KEY_ID is not set. Pass --access-key or export the env var."
[[ -n "${AWS_SECRET_ACCESS_KEY:-}" ]] || die "AWS_SECRET_ACCESS_KEY is not set. Pass --secret-key or export the env var."

# ── Check prerequisites ───────────────────────────────────────────────
for cmd in kubectl aws docker; do
  command -v "$cmd" >/dev/null 2>&1 || die "$cmd is not installed."
done

# ── Step 1: Create namespace ──────────────────────────────────────────
log "Creating namespace '${APP_NS}'..."
kubectl create namespace "${APP_NS}" --dry-run=client -o yaml | kubectl apply -f -
ok "Namespace ready."

# ── Step 2: AWS credentials secret (for worker S3 pull) ──────────────
log "Creating AWS credentials secret..."
kubectl create secret generic traffic-violation-aws-credentials \
  --namespace "${APP_NS}" \
  --from-literal=AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID}" \
  --from-literal=AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY}" \
  --dry-run=client -o yaml | kubectl apply -f -
ok "AWS credentials secret ready."

# ── Step 3: ECR image pull secret ────────────────────────────────────
log "Logging in to ECR and creating image pull secret..."
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION="${AWS_REGION}"
ECR_PASSWORD=$(aws ecr get-login-password --region "${AWS_REGION}")
kubectl create secret docker-registry ecr-credentials \
  --namespace "${APP_NS}" \
  --docker-server="${ECR_REGISTRY}" \
  --docker-username=AWS \
  --docker-password="${ECR_PASSWORD}" \
  --dry-run=client -o yaml | kubectl apply -f -
ok "ECR pull secret ready (valid 12h — CronJob will auto-refresh)."

# ── Step 4: Deploy ECR token refresh CronJob ─────────────────────────
log "Deploying ECR token refresh CronJob..."
kubectl apply -f "${SCRIPT_DIR}/ecr-refresh-cronjob.yaml"
ok "ECR refresh CronJob deployed."

# ── Step 5: Apply ArgoCD Application ─────────────────────────────────
log "Applying ArgoCD Application manifest..."
kubectl apply -f "${SCRIPT_DIR}/argocd-app.yaml"
ok "ArgoCD Application registered."

# ── Step 6: Wait for ArgoCD to sync ──────────────────────────────────
log "Waiting for ArgoCD to sync (up to 3 min)..."
for i in $(seq 1 36); do
  STATUS=$(kubectl get application traffic-violation -n "${ARGOCD_NS}" \
    -o jsonpath='{.status.sync.status}' 2>/dev/null || echo "unknown")
  HEALTH=$(kubectl get application traffic-violation -n "${ARGOCD_NS}" \
    -o jsonpath='{.status.health.status}' 2>/dev/null || echo "unknown")
  if [[ "$STATUS" == "Synced" ]]; then
    ok "ArgoCD synced. Health: ${HEALTH}"
    break
  fi
  echo -n "  [${i}/36] Sync: ${STATUS}, Health: ${HEALTH} — waiting 5s..."$'\r'
  sleep 5
done

# ── Step 7: Get ArgoCD password ───────────────────────────────────────
ARGOCD_PASS=$(kubectl -n "${ARGOCD_NS}" get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null || echo "not found")

EC2_IP=$(curl -sf --max-time 3 http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null \
  || hostname -I | awk '{print $1}')

echo
echo "══════════════════════════════════════════════════════════════"
echo " Traffic Violation System — Deployed"
echo "══════════════════════════════════════════════════════════════"
echo
echo " ArgoCD UI:    https://${EC2_IP}:8080"
echo "   user:       admin"
echo "   password:   ${ARGOCD_PASS}"
echo
echo " Dashboard:    http://${EC2_IP}:8501  (after port-forward below)"
echo " API:          http://${EC2_IP}:5000  (after port-forward below)"
echo
echo " Port-forwards (run in a separate terminal or tmux):"
echo "   kubectl -n argocd port-forward --address 0.0.0.0 svc/argocd-server 8080:443 &"
echo "   kubectl -n traffic-violation port-forward --address 0.0.0.0 svc/traffic-violation 8501:8501 &"
echo "   kubectl -n traffic-violation port-forward --address 0.0.0.0 svc/traffic-violation 5000:5000 &"
echo
echo " Watch pods:"
echo "   kubectl get pods -n traffic-violation -w"
echo "   kubectl logs -n traffic-violation -c worker -f \$(kubectl get pod -n traffic-violation -o name | head -1)"
echo "══════════════════════════════════════════════════════════════"

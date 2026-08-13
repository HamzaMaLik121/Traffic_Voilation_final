#!/usr/bin/env bash
# ═════════════════════════════════════════════════════════════════════
#  push_images.sh — Build and push all ECR images
#
#  Usage:
#    bash push_images.sh              # builds all 3 images
#    bash push_images.sh worker       # builds only worker
#    bash push_images.sh api          # builds only api
#    bash push_images.sh dashboard    # builds only dashboard
#
#  Tag is auto-generated from current date+time: YYYYMMDD-HHMM
#  After pushing, values.yaml is updated automatically so ArgoCD
#  picks up the new images on next sync.
# ═════════════════════════════════════════════════════════════════════
set -euo pipefail

AWS_REGION="us-east-1"
AWS_ACCOUNT="839706991042"
ECR="${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com"
TAG=$(date +%Y%m%d-%H%M)
TARGET="${1:-all}"

GREEN='\033[1;32m'; BLUE='\033[1;34m'; NC='\033[0m'
log() { echo -e "${BLUE}▶${NC} $*"; }
ok()  { echo -e "${GREEN}✔${NC} $*"; }

# Login to ECR
log "Logging in to ECR..."
aws ecr get-login-password --region "${AWS_REGION}" | \
  docker login --username AWS --password-stdin "${ECR}"

build_push() {
  local name="$1"
  local dir="$2"
  local image="${ECR}/traffic-violation/${name}:${TAG}"
  log "Building ${name}:${TAG}..."
  # Remove cached image to force fresh build
  docker rmi "${ECR}/traffic-violation/${name}:${TAG}" 2>/dev/null || true
  docker build --no-cache -t "${image}" "${dir}"
  log "Pushing ${name}:${TAG}..."
  docker push "${image}"
  ok "${name} pushed: ${image}"
}

# Build requested images
if [[ "${TARGET}" == "all" || "${TARGET}" == "worker" ]];    then build_push worker    ./worker;    fi
if [[ "${TARGET}" == "all" || "${TARGET}" == "api" ]];       then build_push api       ./api;       fi
if [[ "${TARGET}" == "all" || "${TARGET}" == "dashboard" ]]; then build_push dashboard ./dashboard; fi

# Update values.yaml with new tag
log "Updating values.yaml with tag ${TAG}..."
if [[ "${TARGET}" == "all" ]]; then
  sed -i "s|tag: \".*\"|tag: \"${TAG}\"|g" traffic-violation-chart/values.yaml
else
  # Update only the specific image tag
  sed -i "/repository:.*traffic-violation\/${TARGET}/{n;s|tag: \".*\"|tag: \"${TAG}\"|}"\
    traffic-violation-chart/values.yaml
fi

ok "values.yaml updated. Commit and push to trigger ArgoCD redeploy:"
echo ""
echo "  git add traffic-violation-chart/values.yaml"
echo "  git commit -m \"chore: bump image tags to ${TAG}\""
echo "  git push origin main"

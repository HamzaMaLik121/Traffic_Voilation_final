#!/usr/bin/env bash
# ═════════════════════════════════════════════════════════════════════
#  bootstrap-kind-platform.sh
#
#  One-click local platform for the Traffic Violation Detection System:
#    • KinD cluster, 3 nodes (1 control-plane + 2 workers)
#    • ingress-nginx          (HTTP ingress into the cluster)
#    • metrics-server         (kubectl top / HPA support)
#    • kube-prometheus-stack  (Prometheus + Grafana + Alertmanager)
#    • Trivy Operator         (continuous image/config vulnerability scans)
#    • ArgoCD                 (GitOps delivery)
#
#  Usage:
#    ./bootstrap-kind-platform.sh            # install everything
#    ./bootstrap-kind-platform.sh --destroy  # tear the cluster down
#
#  Idempotent: safe to re-run. Each stage checks whether it already
#  exists before doing anything, so a failed run can just be re-run.
#
#  Requires (installed automatically if missing, Linux/macOS):
#    docker, kubectl, kind, helm
#
#  Tested against: kind v0.32.0 (Kubernetes v1.31.x node image),
#  kube-prometheus-stack (Prometheus Community), trivy-operator (Aqua),
#  ArgoCD (stable manifests), ingress-nginx.
# ═════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Config (override via env vars if you want) ──────────────────────
CLUSTER_NAME="${CLUSTER_NAME:-traffic-platform}"
KIND_NODE_IMAGE="${KIND_NODE_IMAGE:-kindest/node:v1.31.6}"
KIND_VERSION="${KIND_VERSION:-v0.32.0}"

MONITORING_NS="monitoring"
TRIVY_NS="trivy-system"
ARGOCD_NS="argocd"
INGRESS_NS="ingress-nginx"
APP_NS="traffic-violation"

GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:-admin123}"

# ── Pretty logging ───────────────────────────────────────────────────
c_reset='\033[0m'; c_blue='\033[1;34m'; c_green='\033[1;32m'; c_yellow='\033[1;33m'; c_red='\033[1;31m'
log()  { echo -e "${c_blue}▶${c_reset} $*"; }
ok()   { echo -e "${c_green}✔${c_reset} $*"; }
warn() { echo -e "${c_yellow}⚠${c_reset} $*"; }
err()  { echo -e "${c_red}✘${c_reset} $*" >&2; }

# ── Teardown mode ────────────────────────────────────────────────────
if [[ "${1:-}" == "--destroy" ]]; then
    log "Deleting KinD cluster '${CLUSTER_NAME}'..."
    kind delete cluster --name "${CLUSTER_NAME}" || true
    ok "Cluster deleted."
    exit 0
fi

# ═════════════════════════════════════════════════════════════════════
#  STAGE 0 — Prerequisite tools
# ═════════════════════════════════════════════════════════════════════
log "Checking prerequisites..."

OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH_RAW="$(uname -m)"
case "$ARCH_RAW" in
    x86_64) ARCH="amd64" ;;
    aarch64|arm64) ARCH="arm64" ;;
    *) err "Unsupported architecture: $ARCH_RAW"; exit 1 ;;
esac

need_install() { ! command -v "$1" >/dev/null 2>&1; }

if need_install docker; then
    err "Docker is not installed or not on PATH. Install Docker Desktop / Docker Engine first: https://docs.docker.com/get-docker/"
    exit 1
else
    ok "docker found: $(docker --version)"
fi

if ! docker info >/dev/null 2>&1; then
    err "Docker daemon is not running. Start Docker and re-run this script."
    exit 1
fi
ok "Docker daemon is running."

if need_install kind; then
    log "Installing kind ${KIND_VERSION}..."
    curl -fsSL -o /tmp/kind "https://kind.sigs.k8s.io/dl/${KIND_VERSION}/kind-${OS}-${ARCH}"
    chmod +x /tmp/kind
    sudo mv /tmp/kind /usr/local/bin/kind
    ok "kind installed: $(kind version)"
else
    ok "kind found: $(kind version)"
fi

if need_install kubectl; then
    log "Installing kubectl..."
    KVER="$(curl -fsSL https://dl.k8s.io/release/stable.txt)"
    curl -fsSL -o /tmp/kubectl "https://dl.k8s.io/release/${KVER}/bin/${OS}/${ARCH}/kubectl"
    chmod +x /tmp/kubectl
    sudo mv /tmp/kubectl /usr/local/bin/kubectl
    ok "kubectl installed: $(kubectl version --client --short 2>/dev/null || kubectl version --client)"
else
    ok "kubectl found: $(kubectl version --client --short 2>/dev/null || kubectl version --client)"
fi

if need_install helm; then
    log "Installing helm..."
    curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
    ok "helm installed: $(helm version --short)"
else
    ok "helm found: $(helm version --short)"
fi

# ═════════════════════════════════════════════════════════════════════
#  STAGE 1 — KinD cluster (3 nodes: 1 control-plane + 2 workers)
# ═════════════════════════════════════════════════════════════════════
KIND_CONFIG_FILE="$(mktemp)"
cat > "${KIND_CONFIG_FILE}" <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: ${CLUSTER_NAME}
nodes:
  - role: control-plane
    image: ${KIND_NODE_IMAGE}
    kubeadmConfigPatches:
      - |
        kind: InitConfiguration
        nodeRegistration:
          kubeletExtraArgs:
            node-labels: "ingress-ready=true"
    extraPortMappings:
      # ingress-nginx will land on this node via nodeSelector below;
      # map host 80/443 straight to it so http(s)://localhost just works.
      - containerPort: 80
        hostPort: 80
        protocol: TCP
      - containerPort: 443
        hostPort: 443
        protocol: TCP
  - role: worker
    image: ${KIND_NODE_IMAGE}
  - role: worker
    image: ${KIND_NODE_IMAGE}
networking:
  apiServerAddress: "127.0.0.1"
  disableDefaultCNI: false
EOF

if kind get clusters 2>/dev/null | grep -qx "${CLUSTER_NAME}"; then
    ok "KinD cluster '${CLUSTER_NAME}' already exists — skipping creation."
else
    log "Creating KinD cluster '${CLUSTER_NAME}' (1 control-plane + 2 workers, node image ${KIND_NODE_IMAGE})..."
    kind create cluster --config "${KIND_CONFIG_FILE}"
    ok "Cluster created."
fi
rm -f "${KIND_CONFIG_FILE}"

kubectl cluster-info --context "kind-${CLUSTER_NAME}"
kubectl get nodes -o wide

# ═════════════════════════════════════════════════════════════════════
#  STAGE 2 — ingress-nginx (KinD-flavored manifest: hostPort on control-plane)
# ═════════════════════════════════════════════════════════════════════
log "Installing ingress-nginx..."
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml

log "Waiting for ingress-nginx admission webhook + controller to be ready (this can take a minute)..."
kubectl wait --namespace "${INGRESS_NS}" \
    --for=condition=ready pod \
    --selector=app.kubernetes.io/component=controller \
    --timeout=180s || warn "ingress-nginx controller not ready yet — it may still be pulling images. Check with: kubectl get pods -n ${INGRESS_NS}"
ok "ingress-nginx installed."

# ═════════════════════════════════════════════════════════════════════
#  STAGE 3 — metrics-server (needed for kubectl top + HPA; KinD needs
#  kubelet-insecure-tls since KinD's kubelet certs aren't publicly signed)
# ═════════════════════════════════════════════════════════════════════
log "Installing metrics-server..."
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

kubectl patch deployment metrics-server -n kube-system --type='json' -p='[
  {"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}
]' 2>/dev/null || warn "metrics-server patch may already be applied."
ok "metrics-server installed."

# ═════════════════════════════════════════════════════════════════════
#  STAGE 4 — Helm repos
# ═════════════════════════════════════════════════════════════════════
log "Adding Helm repositories..."
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null
helm repo add grafana https://grafana.github.io/helm-charts >/dev/null
helm repo add aqua https://aquasecurity.github.io/helm-charts/ >/dev/null
helm repo update >/dev/null
ok "Helm repos added and updated."

# ═════════════════════════════════════════════════════════════════════
#  STAGE 5 — kube-prometheus-stack (Prometheus + Grafana + Alertmanager)
# ═════════════════════════════════════════════════════════════════════
kubectl create namespace "${MONITORING_NS}" --dry-run=client -o yaml | kubectl apply -f - >/dev/null

if helm status kube-prometheus-stack -n "${MONITORING_NS}" >/dev/null 2>&1; then
    ok "kube-prometheus-stack already installed — skipping."
else
    log "Installing kube-prometheus-stack (Prometheus + Grafana + Alertmanager)..."
    helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
        --namespace "${MONITORING_NS}" \
        --set grafana.adminPassword="${GRAFANA_ADMIN_PASSWORD}" \
        --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false \
        --set prometheus.prometheusSpec.podMonitorSelectorNilUsesHelmValues=false \
        --set prometheus.prometheusSpec.retention=7d \
        --set prometheus.prometheusSpec.resources.requests.cpu=200m \
        --set prometheus.prometheusSpec.resources.requests.memory=512Mi \
        --wait --timeout 10m
    ok "kube-prometheus-stack installed."
fi

# ═════════════════════════════════════════════════════════════════════
#  STAGE 6 — Trivy Operator (continuous vuln + config scanning)
# ═════════════════════════════════════════════════════════════════════
kubectl create namespace "${TRIVY_NS}" --dry-run=client -o yaml | kubectl apply -f - >/dev/null

if helm status trivy-operator -n "${TRIVY_NS}" >/dev/null 2>&1; then
    ok "trivy-operator already installed — skipping."
else
    log "Installing Trivy Operator..."
    helm install trivy-operator aqua/trivy-operator \
        --namespace "${TRIVY_NS}" \
        --set="trivy.ignoreUnfixed=true" \
        --set="operator.scannerReportTTL=" \
        --set serviceMonitor.enabled=true \
        --set serviceMonitor.labels.release=kube-prometheus-stack \
        --wait --timeout 5m
    ok "Trivy Operator installed. Vulnerability reports populate automatically as workloads run:"
    echo "    kubectl get vulnerabilityreports -A"
fi

# ═════════════════════════════════════════════════════════════════════
#  STAGE 7 — ArgoCD (GitOps)
# ═════════════════════════════════════════════════════════════════════
kubectl create namespace "${ARGOCD_NS}" --dry-run=client -o yaml | kubectl apply -f - >/dev/null

if kubectl get deployment argocd-server -n "${ARGOCD_NS}" >/dev/null 2>&1; then
    ok "ArgoCD already installed — skipping."
else
    log "Installing ArgoCD..."
    kubectl apply -n "${ARGOCD_NS}" --server-side --force-conflicts -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
    log "Waiting for ArgoCD server to be ready (this can take a minute)..."
    kubectl wait --namespace "${ARGOCD_NS}" \
        --for=condition=available deployment/argocd-server \
        --timeout=300s
    ok "ArgoCD installed."
fi

# Expose ArgoCD + Grafana via Ingress so nothing needs port-forwarding
log "Applying Ingress routes for ArgoCD and Grafana..."
cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: argocd-ingress
  namespace: ${ARGOCD_NS}
  annotations:
    nginx.ingress.kubernetes.io/backend-protocol: "HTTPS"
    nginx.ingress.kubernetes.io/ssl-passthrough: "true"
spec:
  ingressClassName: nginx
  rules:
    - host: argocd.local.test
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: argocd-server
                port:
                  number: 443
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: grafana-ingress
  namespace: ${MONITORING_NS}
spec:
  ingressClassName: nginx
  rules:
    - host: grafana.local.test
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: kube-prometheus-stack-grafana
                port:
                  number: 80
EOF
ok "Ingress routes applied (see access instructions at the end)."

# ═════════════════════════════════════════════════════════════════════
#  STAGE 8 — Application namespace (empty, ready for your app manifests)
# ═════════════════════════════════════════════════════════════════════
kubectl create namespace "${APP_NS}" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
ok "Namespace '${APP_NS}' ready for the traffic-violation-detection deployment."

# ═════════════════════════════════════════════════════════════════════
#  DONE — print access info
# ═════════════════════════════════════════════════════════════════════
ARGOCD_INITIAL_PW="$(kubectl -n "${ARGOCD_NS}" get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' 2>/dev/null | base64 -d || echo '(secret already rotated/removed)')"

echo
echo -e "${c_green}═══════════════════════════════════════════════════════════════${c_reset}"
echo -e "${c_green} Platform is up.${c_reset}"
echo -e "${c_green}═══════════════════════════════════════════════════════════════${c_reset}"
echo
echo "Cluster:   ${CLUSTER_NAME}  (3 nodes: 1 control-plane + 2 workers)"
echo "Context:   kind-${CLUSTER_NAME}"
echo
echo "── Add these to /etc/hosts (or C:\\Windows\\System32\\drivers\\etc\\hosts) ──"
echo "  127.0.0.1  argocd.local.test"
echo "  127.0.0.1  grafana.local.test"
echo
echo "── ArgoCD ──────────────────────────────────────────────────────"
echo "  URL:      https://argocd.local.test"
echo "  User:     admin"
echo "  Password: ${ARGOCD_INITIAL_PW}"
echo "  (fallback if hosts file isn't set: kubectl port-forward -n ${ARGOCD_NS} svc/argocd-server 8080:443)"
echo
echo "── Grafana ─────────────────────────────────────────────────────"
echo "  URL:      http://grafana.local.test"
echo "  User:     admin"
echo "  Password: ${GRAFANA_ADMIN_PASSWORD}"
echo "  (fallback: kubectl port-forward -n ${MONITORING_NS} svc/kube-prometheus-stack-grafana 3000:80)"
echo
echo "── Prometheus ──────────────────────────────────────────────────"
echo "  kubectl port-forward -n ${MONITORING_NS} svc/kube-prometheus-stack-prometheus 9090:9090"
echo
echo "── Trivy Operator ──────────────────────────────────────────────"
echo "  kubectl get vulnerabilityreports -A"
echo "  kubectl get configauditreports -A"
echo
echo "── Application namespace ───────────────────────────────────────"
echo "  ${APP_NS}  (deploy your traffic-violation-detection manifests / Argo Application here)"
echo
echo "── Teardown ─────────────────────────────────────────────────────"
echo "  ./$(basename "$0") --destroy"
echo

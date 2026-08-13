#!/usr/bin/env bash
# ==============================================================================
# Traffic DevOps - One Click KinD DevOps Platform
#
# Creates:
#   - KinD cluster: 1 control-plane + 3 workers
#   - Cluster name: traffic-devops
#   - Kubernetes platform:
#       * Argo CD
#       * Trivy CLI + Trivy Operator
#       * OWASP Dependency-Check CLI
#       * Prometheus
#       * Grafana
#       * Alertmanager
#       * Node Exporter / kube-state-metrics (via kube-prometheus-stack)
#       * metrics-server
#       * local-path persistent storage
#   - Docker restart policy + systemd boot recovery
#
# Intended for Ubuntu/Debian Linux (e.g. AWS EC2 Ubuntu).
#
# Usage:
#   chmod +x traffic-devops.sh
#   sudo ./traffic-devops.sh
#
# Destroy:
#   sudo ./traffic-devops.sh --destroy
#
# IMPORTANT:
#   An EC2 stop powers off the whole VM, so containers cannot literally keep
#   running while the VM is off. This script makes them automatically return
#   when the instance boots again.
# ==============================================================================

set -Eeuo pipefail

# ----------------------------- Configuration ---------------------------------
CLUSTER_NAME="${CLUSTER_NAME:-traffic-devops}"
DISPLAY_NAME="Traffic DevOps"

# Stable Kubernetes node image. Change via:
#   KIND_NODE_IMAGE=kindest/node:v1.32.x sudo ./traffic-devops.sh
KIND_NODE_IMAGE="${KIND_NODE_IMAGE:-kindest/node:v1.31.6}"
KIND_VERSION="${KIND_VERSION:-v0.32.0}"

ARGOCD_NS="argocd"
MONITORING_NS="monitoring"
TRIVY_NS="trivy-system"
APP_NS="traffic-violation"

GRAFANA_ADMIN_USER="${GRAFANA_ADMIN_USER:-admin}"
GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:-admin123}"

# Persistent storage sizes. local-path provisioner stores data inside the KinD
# node filesystem, which survives a Docker container restart.
GRAFANA_STORAGE="${GRAFANA_STORAGE:-2Gi}"
PROMETHEUS_STORAGE="${PROMETHEUS_STORAGE:-5Gi}"
ALERTMANAGER_STORAGE="${ALERTMANAGER_STORAGE:-2Gi}"

SYSTEMD_UNIT="/etc/systemd/system/traffic-devops-kind.service"
BOOT_SCRIPT="/usr/local/bin/traffic-devops-kind-recover"

# ------------------------------- Logging -------------------------------------
c_reset='\033[0m'
c_blue='\033[1;34m'
c_green='\033[1;32m'
c_yellow='\033[1;33m'
c_red='\033[1;31m'

log()  { echo -e "${c_blue}▶${c_reset} $*"; }
ok()   { echo -e "${c_green}✔${c_reset} $*"; }
warn() { echo -e "${c_yellow}⚠${c_reset} $*"; }
err()  { echo -e "${c_red}✘${c_reset} $*" >&2; }
die()  { err "$*"; exit 1; }

cleanup() {
  rm -f "${KIND_CONFIG_FILE:-}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# --------------------------- Helper functions --------------------------------
retry() {
  local attempts="$1"
  local delay="$2"
  shift 2
  local n=1
  until "$@"; do
    if (( n >= attempts )); then
      return 1
    fi
    sleep "$delay"
    ((n++))
  done
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

run_as_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

# -------------------------------- Destroy ------------------------------------
if [[ "${1:-}" == "--destroy" ]]; then
  [[ "${EUID}" -eq 0 ]] || die "Run destroy mode with sudo: sudo $0 --destroy"

  log "Disabling boot recovery service..."
  systemctl disable --now traffic-devops-kind.service >/dev/null 2>&1 || true
  rm -f "${SYSTEMD_UNIT}" "${BOOT_SCRIPT}" || true
  systemctl daemon-reload >/dev/null 2>&1 || true

  log "Deleting KinD cluster '${CLUSTER_NAME}'..."
  kind delete cluster --name "${CLUSTER_NAME}" || true

  ok "Traffic DevOps cluster destroyed."
  exit 0
fi

# ----------------------------- Root check ------------------------------------
[[ "${EUID}" -eq 0 ]] || die "Run this script with sudo: sudo $0"

# ------------------------ OS / architecture ----------------------------------
[[ -f /etc/os-release ]] || die "Cannot detect Linux distribution."
# shellcheck disable=SC1091
source /etc/os-release

case "${ID:-}" in
  ubuntu|debian) ;;
  *)
    die "This script targets Ubuntu/Debian. Detected: ${ID:-unknown}"
    ;;
esac

case "$(uname -m)" in
  x86_64)  ARCH="amd64" ;;
  aarch64) ARCH="arm64" ;;
  arm64)   ARCH="arm64" ;;
  *) die "Unsupported architecture: $(uname -m)" ;;
esac

log "Starting ${DISPLAY_NAME} platform setup..."
log "Cluster: ${CLUSTER_NAME}"
log "Nodes: 1 control-plane + 3 workers"

# ------------------------------ Packages -------------------------------------
log "Installing base packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y \
  ca-certificates \
  curl \
  gnupg \
  lsb-release \
  apt-transport-https \
  unzip \
  jq \
  git

# ------------------------------- Docker --------------------------------------
if ! command_exists docker; then
  log "Installing Docker..."
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker
else
  ok "Docker already installed: $(docker --version)"
  systemctl enable --now docker
fi

if ! docker info >/dev/null 2>&1; then
  die "Docker daemon is not available."
fi

# Make the current non-root user able to run Docker after re-login.
REAL_USER="${SUDO_USER:-}"
if [[ -n "${REAL_USER}" && "${REAL_USER}" != "root" ]]; then
  usermod -aG docker "${REAL_USER}" || true
fi

ok "Docker is running."

# --------------------------- Docker Compose v2 -------------------------------
# Install the official Docker Compose plugin if it is missing.
if ! docker compose version >/dev/null 2>&1; then
  log "Installing Docker Compose v2..."

  apt-get update -y
  apt-get install -y docker-compose-plugin

  # Ubuntu/Debian package availability can vary, so fall back to the official
  # Docker CLI plugin binary when the package is not available.
  if ! docker compose version >/dev/null 2>&1; then
    log "Package unavailable; installing official Docker Compose CLI plugin..."

    COMPOSE_VERSION="$(
      curl -fsSL https://api.github.com/repos/docker/compose/releases/latest         | jq -r '.tag_name'
    )"
    [[ -n "${COMPOSE_VERSION}" && "${COMPOSE_VERSION}" != "null" ]]       || die "Could not determine Docker Compose version."

    install -d -m 0755 /usr/local/lib/docker/cli-plugins
    curl -fL       "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-${ARCH}"       -o /usr/local/lib/docker/cli-plugins/docker-compose
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
  fi
fi

ok "Docker Compose: $(docker compose version)"

# ------------------------------- KinD ----------------------------------------
if ! command_exists kind; then
  log "Installing KinD ${KIND_VERSION}..."
  curl -fsSL -o /tmp/kind \
    "https://kind.sigs.k8s.io/dl/${KIND_VERSION}/kind-linux-${ARCH}"
  install -m 0755 /tmp/kind /usr/local/bin/kind
  rm -f /tmp/kind
fi
ok "KinD: $(kind version | head -n1)"

# -------------------------------- kubectl -------------------------------------
if ! command_exists kubectl; then
  log "Installing kubectl..."
  KVER="$(curl -fsSL https://dl.k8s.io/release/stable.txt)"
  curl -fsSL -o /tmp/kubectl \
    "https://dl.k8s.io/release/${KVER}/bin/linux/${ARCH}/kubectl"
  install -m 0755 /tmp/kubectl /usr/local/bin/kubectl
  rm -f /tmp/kubectl
fi
ok "kubectl: $(kubectl version --client --output=yaml 2>/dev/null | awk -F': ' '/gitVersion:/ {print $2; exit}')"

# --------------------------------- Helm ---------------------------------------
if ! command_exists helm; then
  log "Installing Helm..."
  curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi
ok "Helm: $(helm version --short)"

# ------------------------------- Trivy CLI -----------------------------------
if ! command_exists trivy; then
  log "Installing Trivy CLI..."
  apt-get install -y wget
  install -d -m 0755 /etc/apt/keyrings
  curl -fsSL https://aquasecurity.github.io/trivy-repo/deb/public.key \
    | gpg --dearmor -o /etc/apt/keyrings/trivy.gpg
  echo "deb [signed-by=/etc/apt/keyrings/trivy.gpg] https://aquasecurity.github.io/trivy-repo/deb generic main" \
    > /etc/apt/sources.list.d/trivy.list
  apt-get update -y
  apt-get install -y trivy
fi
ok "Trivy CLI: $(trivy --version | head -n1)"

# ----------------------- OWASP Dependency-Check CLI ---------------------------
if ! command_exists dependency-check.sh; then
  log "Installing Java + OWASP Dependency-Check CLI..."
  apt-get install -y openjdk-17-jre-headless

  DC_VERSION="$(
    curl -fsSL       -H 'Accept: application/vnd.github+json'       https://api.github.com/repos/jeremylong/DependencyCheck/releases/latest       | jq -r '.tag_name'       | sed 's/^v//'
  )"

  [[ -n "${DC_VERSION}" && "${DC_VERSION}" != "null" ]]     || die "Could not determine latest OWASP Dependency-Check version."

  DC_ARCHIVE="/tmp/dependency-check-${DC_VERSION}-release.zip"
  DC_TMP="/tmp/owasp-dependency-check-${DC_VERSION}"

  curl -fL -o "${DC_ARCHIVE}"     "https://github.com/jeremylong/DependencyCheck/releases/download/v${DC_VERSION}/dependency-check-${DC_VERSION}-release.zip"

  rm -rf "${DC_TMP}" /opt/dependency-check
  mkdir -p "${DC_TMP}"
  unzip -q "${DC_ARCHIVE}" -d "${DC_TMP}"
  rm -f "${DC_ARCHIVE}"

  DC_DIR="$(find "${DC_TMP}" -mindepth 1 -maxdepth 2 -type d -name 'dependency-check*' | head -n1 || true)"
  if [[ -z "${DC_DIR}" ]]; then
    DC_DIR="${DC_TMP}"
  fi

  mkdir -p /opt/dependency-check
  cp -a "${DC_DIR}/." /opt/dependency-check/
  rm -rf "${DC_TMP}"

  ln -sf /opt/dependency-check/bin/dependency-check.sh /usr/local/bin/dependency-check.sh
  ln -sf /opt/dependency-check/bin/dependency-check.sh /usr/local/bin/dependency-check
fi

ok "OWASP Dependency-Check installed: /opt/dependency-check"

# ----------------------------- KinD cluster ----------------------------------
KIND_CONFIG_FILE="$(mktemp)"

cat > "${KIND_CONFIG_FILE}" <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: ${CLUSTER_NAME}
nodes:
  - role: control-plane
    image: ${KIND_NODE_IMAGE}
    extraPortMappings:
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
  - role: worker
    image: ${KIND_NODE_IMAGE}
EOF

if kind get clusters 2>/dev/null | grep -qx "${CLUSTER_NAME}"; then
  ok "KinD cluster '${CLUSTER_NAME}' already exists."
else
  log "Creating KinD cluster '${CLUSTER_NAME}'..."
  kind create cluster \
    --config "${KIND_CONFIG_FILE}" \
    --wait 5m
  ok "KinD cluster created."
fi

# ---------------------- Docker restart + recovery ----------------------------
log "Configuring Docker restart policies for KinD nodes..."
for node in $(kind get nodes --name "${CLUSTER_NAME}"); do
  docker update --restart unless-stopped "${node}" >/dev/null
done
ok "KinD node containers will restart automatically with Docker."

# ----------------------- Wait for Kubernetes API ------------------------------
retry 60 5 kubectl --context "kind-${CLUSTER_NAME}" cluster-info >/dev/null 2>&1 \
  || die "Kubernetes API did not become ready."

kubectl config use-context "kind-${CLUSTER_NAME}" >/dev/null

if [[ -n "${REAL_USER}" && "${REAL_USER}" != "root" ]]; then
  REAL_HOME="$(getent passwd "${REAL_USER}" | cut -d: -f6)"
  if [[ -n "${REAL_HOME}" && -f /root/.kube/config ]]; then
    install -d -m 0700 -o "${REAL_USER}" -g "${REAL_USER}" "${REAL_HOME}/.kube"
    cp -f /root/.kube/config "${REAL_HOME}/.kube/config"
    chown "${REAL_USER}:${REAL_USER}" "${REAL_HOME}/.kube/config"
    chmod 0600 "${REAL_HOME}/.kube/config"
  fi
fi

kubectl get nodes -o wide

# ---------------------- Local persistent storage ------------------------------
log "Installing local-path persistent storage..."
if ! kubectl get storageclass local-path >/dev/null 2>&1; then
  kubectl apply -f \
    https://raw.githubusercontent.com/rancher/local-path-provisioner/master/deploy/local-path-storage.yaml
fi

kubectl patch storageclass local-path \
  -p '{"metadata":{"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}' \
  >/dev/null 2>&1 || true

kubectl rollout status deployment/local-path-provisioner \
  -n local-path-storage --timeout=180s

ok "Persistent storage is ready."

# ----------------------------- metrics-server -------------------------------
log "Installing metrics-server..."
kubectl apply -f \
  https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

kubectl patch deployment metrics-server -n kube-system --type='json' \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]' \
  >/dev/null 2>&1 || true

kubectl rollout status deployment/metrics-server \
  -n kube-system --timeout=180s || warn "metrics-server is still starting."

# -------------------------------- Helm repos ----------------------------------
log "Configuring Helm repositories..."
helm repo add prometheus-community \
  https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
helm repo add aqua \
  https://aquasecurity.github.io/helm-charts/ >/dev/null 2>&1 || true
helm repo update >/dev/null

# --------------------- Prometheus / Grafana / Alertmanager --------------------
kubectl create namespace "${MONITORING_NS}" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null

log "Installing/upgrading kube-prometheus-stack..."
helm upgrade --install kube-prometheus-stack \
  prometheus-community/kube-prometheus-stack \
  --namespace "${MONITORING_NS}" \
  --set grafana.adminUser="${GRAFANA_ADMIN_USER}" \
  --set grafana.adminPassword="${GRAFANA_ADMIN_PASSWORD}" \
  --set grafana.persistence.enabled=true \
  --set grafana.persistence.storageClassName=local-path \
  --set grafana.persistence.size="${GRAFANA_STORAGE}" \
  --set prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.spec.storageClassName=local-path \
  --set prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.spec.resources.requests.storage="${PROMETHEUS_STORAGE}" \
  --set alertmanager.alertmanagerSpec.storage.volumeClaimTemplate.spec.storageClassName=local-path \
  --set alertmanager.alertmanagerSpec.storage.volumeClaimTemplate.spec.resources.requests.storage="${ALERTMANAGER_STORAGE}" \
  --set prometheus.prometheusSpec.retention=7d \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false \
  --set prometheus.prometheusSpec.podMonitorSelectorNilUsesHelmValues=false \
  --wait \
  --timeout 10m

ok "Prometheus + Grafana + Alertmanager installed."

# ----------------------------- ingress-nginx ---------------------------------
log "Installing ingress-nginx (KinD provider)..."
kubectl apply -f \
  https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.10.1/deploy/static/provider/kind/deploy.yaml

# KinD provider manifest requires the control-plane node to be labelled
log "Labelling control-plane node for ingress-nginx..."
kubectl label node "${CLUSTER_NAME}-control-plane" ingress-ready=true --overwrite

kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=120s

ok "ingress-nginx installed."

# ----------------------------- Trivy Operator --------------------------------
kubectl create namespace "${TRIVY_NS}" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null

log "Installing/upgrading Trivy Operator..."
helm upgrade --install trivy-operator \
  aqua/trivy-operator \
  --namespace "${TRIVY_NS}" \
  --set trivy.ignoreUnfixed=true \
  --set serviceMonitor.enabled=true \
  --set serviceMonitor.labels.release=kube-prometheus-stack \
  --wait \
  --timeout 10m

ok "Trivy Operator installed."

# --------------------------------- Argo CD ------------------------------------
kubectl create namespace "${ARGOCD_NS}" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null

log "Installing/upgrading Argo CD..."
kubectl apply -n "${ARGOCD_NS}" \
  --server-side --force-conflicts \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

kubectl rollout status deployment/argocd-server \
  -n "${ARGOCD_NS}" --timeout 300s

ok "Argo CD installed."

# --------------------------- Application namespace ---------------------------
kubectl create namespace "${APP_NS}" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null

# ----------------------- Boot recovery systemd unit ---------------------------
log "Installing boot recovery service..."

cat > "${BOOT_SCRIPT}" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail

CLUSTER_NAME="${CLUSTER_NAME}"

# Wait for Docker.
for _ in {1..60}; do
  if docker info >/dev/null 2>&1; then
    break
  fi
  sleep 5
done

# Start any stopped KinD node containers.
for node in \$(kind get nodes --name "\${CLUSTER_NAME}" 2>/dev/null || true); do
  if docker inspect -f '{{.State.Status}}' "\${node}" 2>/dev/null | grep -q '^exited$'; then
    docker start "\${node}" >/dev/null 2>&1 || true
  fi
  docker update --restart unless-stopped "\${node}" >/dev/null 2>&1 || true
done

# Wait for the Kubernetes API to recover.
for _ in {1..60}; do
  if kubectl --context "kind-\${CLUSTER_NAME}" cluster-info >/dev/null 2>&1; then
    exit 0
  fi
  sleep 5
done

exit 0
EOF

chmod 0755 "${BOOT_SCRIPT}"

cat > "${SYSTEMD_UNIT}" <<EOF
[Unit]
Description=Traffic DevOps KinD Cluster Recovery
Wants=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=${BOOT_SCRIPT}
RemainAfterExit=yes
TimeoutStartSec=8min

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable traffic-devops-kind.service >/dev/null
systemctl restart traffic-devops-kind.service || true
ok "Boot recovery service enabled."

# ----------------------------- Final checks -----------------------------------
log "Checking workloads..."

kubectl wait --for=condition=Ready node --all --timeout=180s || true

echo
echo "=============================================================="
echo " ${DISPLAY_NAME} - READY"
echo "=============================================================="
echo
echo "Cluster:        ${CLUSTER_NAME}"
echo "Nodes:"
kubectl get nodes --no-headers | awk '{printf "  %-30s %s\n", $1, $2}'
echo
echo "Argo CD:"
kubectl get pods -n "${ARGOCD_NS}" --no-headers || true
echo
echo "Monitoring:"
kubectl get pods -n "${MONITORING_NS}" --no-headers || true
echo
echo "Trivy:"
kubectl get pods -n "${TRIVY_NS}" --no-headers || true
echo
echo "=============================================================="
echo " Useful commands"
echo "=============================================================="
echo
echo "All pods:"
echo "  kubectl get pods -A"
echo
echo "All nodes:"
echo "  kubectl get nodes -o wide"
echo
echo "Argo CD:"
echo "  kubectl get pods -n argocd"
echo "  kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d; echo"
echo "  kubectl -n argocd port-forward --address 0.0.0.0 svc/argocd-server 8080:443"
echo
echo "Grafana:"
echo "  kubectl -n monitoring get pods -l app.kubernetes.io/name=grafana"
echo "  kubectl -n monitoring port-forward --address 0.0.0.0 svc/kube-prometheus-stack-grafana 3000:80"
echo "  Login: ${GRAFANA_ADMIN_USER} / ${GRAFANA_ADMIN_PASSWORD}"
echo
echo "Prometheus:"
echo "  kubectl -n monitoring port-forward --address 0.0.0.0 svc/kube-prometheus-stack-prometheus 9090:9090"
echo
echo "Trivy reports:"
echo "  kubectl get vulnerabilityreports -A"
echo "  kubectl get configauditreports -A"
echo
echo "OWASP Dependency-Check:"
echo "  dependency-check.sh --help"
echo "  dependency-check.sh --scan /path/to/your/project --format HTML --out ./dependency-check-report"
echo
echo "EC2 stop/start recovery:"
echo "  systemctl status traffic-devops-kind.service"
echo "  docker ps --filter label=io.x-k8s.kind.cluster=${CLUSTER_NAME}"
echo
echo "Destroy everything:"
echo "  sudo $0 --destroy"
echo
ok "${DISPLAY_NAME} installation completed."

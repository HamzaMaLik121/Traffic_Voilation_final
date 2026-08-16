#!/usr/bin/env bash
set -euo pipefail

# Simple DevOps lab for Ubuntu/Debian:
# Docker + kubectl + Kind + Helm + Kubernetes + Argo CD
# + ingress-nginx + Prometheus/Grafana + metrics-server.
#
# Intentionally NOT installing Trivy Operator or OWASP Dependency-Check:
# they add extra pods/scanning work and are better added later if needed.

CLUSTER_NAME="traffic-devops"
KIND_NODES=2   # 1 control-plane + 1 worker; change to 3 for 1+2

if [[ $EUID -ne 0 ]]; then
  echo "Run: sudo $0"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

echo "==> Installing base packages"
apt-get update -y
apt-get install -y ca-certificates curl gnupg git jq

echo "==> Installing Docker"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

echo "==> Installing kubectl"
if ! command -v kubectl >/dev/null 2>&1; then
  KVER="$(curl -fsSL https://dl.k8s.io/release/stable.txt)"
  curl -fsSL -o /usr/local/bin/kubectl \
    "https://dl.k8s.io/release/${KVER}/bin/linux/amd64/kubectl"
  chmod +x /usr/local/bin/kubectl
fi

echo "==> Installing Kind"
if ! command -v kind >/dev/null 2>&1; then
  KIND_VERSION="$(curl -fsSL https://api.github.com/repos/kubernetes-sigs/kind/releases/latest | jq -r .tag_name)"
  curl -fsSL -o /usr/local/bin/kind \
    "https://kind.sigs.k8s.io/dl/${KIND_VERSION}/kind-linux-amd64"
  chmod +x /usr/local/bin/kind
fi

echo "==> Installing Helm"
if ! command -v helm >/dev/null 2>&1; then
  curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi

echo "==> Adding current user to Docker group"
REAL_USER="${SUDO_USER:-}"
if [[ -n "$REAL_USER" && "$REAL_USER" != "root" ]]; then
  usermod -aG docker "$REAL_USER"
fi

echo "==> Creating Kind cluster"
cat >/tmp/${CLUSTER_NAME}-kind.yaml <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: ${CLUSTER_NAME}
nodes:
- role: control-plane
  extraPortMappings:
  - containerPort: 80
    hostPort: 80
    protocol: TCP
  - containerPort: 443
    hostPort: 443
    protocol: TCP
- role: worker
EOF

if ! kind get clusters | grep -qx "${CLUSTER_NAME}"; then
  kind create cluster --config /tmp/${CLUSTER_NAME}-kind.yaml
else
  echo "Kind cluster already exists."
fi

kubectl cluster-info
kubectl wait --for=condition=Ready node --all --timeout=180s

echo "==> Installing ingress-nginx"
kubectl apply -f \
  https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.14.1/deploy/static/provider/kind/deploy.yaml

kubectl label node "${CLUSTER_NAME}-control-plane" ingress-ready=true --overwrite || true

kubectl wait -n ingress-nginx \
  --for=condition=Ready pod \
  -l app.kubernetes.io/component=controller \
  --timeout=180s

echo "==> Installing Argo CD"
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -n argocd \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

kubectl rollout status deployment/argocd-server \
  -n argocd --timeout=300s

echo "==> Installing lightweight monitoring"
helm repo add prometheus-community \
  https://prometheus-community.github.io/helm-charts
helm repo update

kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -

cat >/tmp/monitoring-values.yaml <<'EOF'
grafana:
  persistence:
    enabled: true
    size: 1Gi

prometheus:
  prometheusSpec:
    retention: 2d
    retentionSize: 1GB
    storageSpec:
      volumeClaimTemplate:
        spec:
          resources:
            requests:
              storage: 2Gi

alertmanager:
  enabled: false

kube-state-metrics:
  enabled: true

nodeExporter:
  enabled: true
EOF

helm upgrade --install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  -f /tmp/monitoring-values.yaml \
  --wait \
  --timeout 10m

echo "==> Installing metrics-server"
kubectl apply -f \
  https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

# Kind often needs insecure TLS for metrics-server.
kubectl patch deployment metrics-server -n kube-system --type='json' \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]' 2>/dev/null || true

echo "==> Creating application namespace"
kubectl create namespace traffic-violation --dry-run=client -o yaml | kubectl apply -f -

rm -f /tmp/${CLUSTER_NAME}-kind.yaml /tmp/monitoring-values.yaml

echo
echo "=============================================="
echo " READY"
echo "=============================================="
echo "Cluster:"
kind get clusters
echo
kubectl get nodes
echo
echo "Argo CD:"
kubectl get pods -n argocd
echo
echo "Monitoring:"
kubectl get pods -n monitoring
echo
echo "Ingress:"
kubectl get pods -n ingress-nginx
echo
echo "Useful commands:"
echo "  kubectl get pods -A"
echo "  kubectl top nodes"
echo "  kubectl get ingress -A"
echo
echo "Argo CD temporary access:"
echo "  kubectl port-forward svc/argocd-server -n argocd 8080:443"
echo
echo "IMPORTANT: log out/in after installation so your user gets Docker-group access."
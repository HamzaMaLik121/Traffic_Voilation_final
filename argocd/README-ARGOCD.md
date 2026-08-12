# ArgoCD Deployment Guide — Traffic Violation Detection System

This guide covers the full flow:
1. Bootstrap the EC2 + KinD cluster (one script)
2. Create the AWS credentials secret
3. Apply the ArgoCD Application manifest
4. Watch the deployment and access the app

---

## Files in this folder

| File | Purpose |
|------|---------|
| `argocd-app.yaml` | ArgoCD `Application` CR — tells ArgoCD which repo/branch/path to sync and where to deploy |
| `argocd-aws-secret.yaml` | Kubernetes `Secret` template for AWS credentials (fill in your keys before applying) |
| `README-ARGOCD.md` | This guide |

---

## Architecture recap

ArgoCD watches your GitHub repo (`main` branch) and automatically syncs the Helm chart at `traffic-violation-chart/` into the `traffic-violation` namespace on your KinD cluster. Every `git push` to `main` triggers a re-sync within ~3 minutes.

```
GitHub (main branch)
      │
      │  ArgoCD polls every 3 min (or webhook)
      ▼
ArgoCD (argocd namespace)
      │
      │  helm install / helm upgrade
      ▼
traffic-violation namespace
  └── Pod: worker + api + dashboard (3 containers, 1 PVC)
```

---

## Step 0 — On your local machine: push code to GitHub

Run these commands from your project root **before** SSHing into EC2:

```bash
cd /path/to/Traffic_Voilation_final

git add argocd/
git commit -m "feat: add ArgoCD Application manifest and deployment guide"
git push origin main
```

---

## Step 1 — SSH into your EC2 instance

```bash
ssh -i your-key.pem ubuntu@<EC2_PUBLIC_IP>
```

---

## Step 2 — Clone the repo on EC2

```bash
git clone https://github.com/HamzaMaLik121/Traffic_Voilation_final.git
cd Traffic_Voilation_final
```

If you already cloned it before, just pull the latest:

```bash
cd Traffic_Voilation_final
git pull origin main
```

---

## Step 3 — Bootstrap the cluster (one script, ~10 min)

This installs Docker, KinD (4-node cluster), kubectl, Helm, ArgoCD, Prometheus/Grafana, Trivy Operator, and metrics-server in one shot.

```bash
chmod +x bootstrap-kind-platform.sh
sudo ./bootstrap-kind-platform.sh
```

When it finishes you will see:

```
✔ Argo CD installed.
✔ Traffic DevOps installation completed.
```

Verify everything is running:

```bash
kubectl get nodes
kubectl get pods -n argocd
```

All ArgoCD pods should be `Running` before continuing.

---

## Step 4 — Get the ArgoCD admin password

```bash
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d; echo
```

Save that password — you will use it to log into the ArgoCD UI.

---

## Step 5 — Create the AWS credentials Secret

The worker container pulls ML models and videos from your S3 bucket
(`traffic-violation-project-data-models`) on first boot. It needs AWS credentials.

**Recommended — create the secret directly (keys never touch any file):**

```bash
# Make sure the namespace exists first
kubectl create namespace traffic-violation --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic traffic-violation-aws-credentials \
  --namespace traffic-violation \
  --from-literal=AWS_ACCESS_KEY_ID=YOUR_REAL_KEY_ID \
  --from-literal=AWS_SECRET_ACCESS_KEY=YOUR_REAL_SECRET_KEY
```

Replace `YOUR_REAL_KEY_ID` and `YOUR_REAL_SECRET_KEY` with your actual AWS credentials.

Verify the secret was created:

```bash
kubectl get secret traffic-violation-aws-credentials -n traffic-violation
```

---

## Step 6 — Apply the ArgoCD Application manifest

```bash
kubectl apply -f argocd/argocd-app.yaml
```

This registers the app with ArgoCD. ArgoCD will immediately start a sync —
pulling the Helm chart from GitHub and deploying it to the cluster.

---

## Step 7 — Watch the deployment

```bash
# Watch ArgoCD sync status
kubectl get application traffic-violation -n argocd -w

# Watch the pod come up (worker + api + dashboard = 1 pod, 3 containers)
kubectl get pods -n traffic-violation -w

# Follow worker logs (S3 model download + pipeline start)
kubectl logs -n traffic-violation deploy/traffic-violation -c worker -f

# Follow api logs
kubectl logs -n traffic-violation deploy/traffic-violation -c api -f

# Follow dashboard logs
kubectl logs -n traffic-violation deploy/traffic-violation -c dashboard -f
```

The worker's startup probe allows up to 30 minutes for the first S3 model
download. Normal pull time is 2–5 minutes. Once the worker is ready, api
and dashboard become ready automatically.

---

## Step 8 — Access the services

### ArgoCD UI

```bash
# Port-forward ArgoCD (run in background or a separate terminal)
kubectl -n argocd port-forward --address 0.0.0.0 svc/argocd-server 8080:443
```

Then open `https://<EC2_PUBLIC_IP>:8080` in your browser.
- Username: `admin`
- Password: (from Step 4)

> Allow port 8080 in your EC2 Security Group inbound rules.

### Traffic Violation Dashboard (Streamlit)

```bash
kubectl -n traffic-violation port-forward --address 0.0.0.0 svc/traffic-violation 8501:8501
```

Open `http://<EC2_PUBLIC_IP>:8501`

### Traffic Violation API

```bash
kubectl -n traffic-violation port-forward --address 0.0.0.0 svc/traffic-violation 5000:5000
```

Open `http://<EC2_PUBLIC_IP>:5000/health`

### Grafana (monitoring)

```bash
kubectl -n monitoring port-forward --address 0.0.0.0 svc/kube-prometheus-stack-grafana 3000:80
```

Open `http://<EC2_PUBLIC_IP>:3000`
- Username: `admin`
- Password: `admin123`

---

## Step 9 — Update the deployment (GitOps flow)

This is the core GitOps loop. Every change goes through Git — never `kubectl apply` directly.

```bash
# On your LOCAL machine — make a change (e.g. bump image tag)
# Edit traffic-violation-chart/values.yaml, then:

git add traffic-violation-chart/values.yaml
git commit -m "chore: bump worker image tag to 20260813-1200"
git push origin main

# ArgoCD detects the change within ~3 minutes and auto-syncs.
# Watch it happen:
kubectl get application traffic-violation -n argocd -w
```

To force an immediate sync without waiting:

```bash
# Install ArgoCD CLI (optional)
curl -sSL -o /usr/local/bin/argocd \
  https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64
chmod +x /usr/local/bin/argocd

argocd login localhost:8080 --username admin --password <PASSWORD> --insecure
argocd app sync traffic-violation
```

---

## Troubleshooting

### ArgoCD shows "OutOfSync" after applying

Normal on first apply — it is syncing. Wait ~30 seconds and refresh.
If it stays OutOfSync, check:

```bash
kubectl describe application traffic-violation -n argocd
```

### Worker pod stuck in Init / not ready

The worker is downloading models from S3 — this takes 2–5 minutes.
The startup probe gives it up to 30 minutes. Check the logs:

```bash
kubectl logs -n traffic-violation deploy/traffic-violation -c worker -f
```

If you see AWS errors, your credentials secret is wrong:

```bash
# Delete and recreate with correct keys
kubectl delete secret traffic-violation-aws-credentials -n traffic-violation
kubectl create secret generic traffic-violation-aws-credentials \
  --namespace traffic-violation \
  --from-literal=AWS_ACCESS_KEY_ID=CORRECT_KEY \
  --from-literal=AWS_SECRET_ACCESS_KEY=CORRECT_SECRET
# Then restart the pod
kubectl rollout restart deploy/traffic-violation -n traffic-violation
```

### StorageClass error on PVC

The `values.yaml` uses `storageClassName: standard` (KinD default).
If you are on EKS, change it:

```bash
# In argocd-app.yaml under helm.values, change:
storage:
  storageClassName: "gp2"   # or "gp3" for newer EKS clusters
```

Then `git push` and ArgoCD will re-sync automatically.

### Port-forward drops after SSH session ends

Run port-forwards with `nohup` or in a `tmux`/`screen` session:

```bash
tmux new -s portforwards
kubectl -n argocd port-forward --address 0.0.0.0 svc/argocd-server 8080:443
# Ctrl+B then D to detach
```

---

## EC2 Security Group — required inbound rules

| Port | Protocol | Source | Purpose |
|------|----------|--------|---------|
| 22 | TCP | Your IP | SSH |
| 8080 | TCP | Your IP | ArgoCD UI |
| 8501 | TCP | Your IP | Streamlit Dashboard |
| 5000 | TCP | Your IP | Flask API |
| 3000 | TCP | Your IP | Grafana |
| 9090 | TCP | Your IP | Prometheus (optional) |

---

## Quick reference — all commands in order

```bash
# 1. Clone + enter repo
git clone https://github.com/HamzaMaLik121/Traffic_Voilation_final.git
cd Traffic_Voilation_final

# 2. Bootstrap cluster + ArgoCD (~10 min)
chmod +x bootstrap-kind-platform.sh
sudo ./bootstrap-kind-platform.sh

# 3. Get ArgoCD password
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d; echo

# 4. Create AWS credentials secret
kubectl create namespace traffic-violation --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic traffic-violation-aws-credentials \
  --namespace traffic-violation \
  --from-literal=AWS_ACCESS_KEY_ID=YOUR_KEY \
  --from-literal=AWS_SECRET_ACCESS_KEY=YOUR_SECRET

# 5. Deploy via ArgoCD
kubectl apply -f argocd/argocd-app.yaml

# 6. Watch
kubectl get pods -n traffic-violation -w
kubectl logs -n traffic-violation deploy/traffic-violation -c worker -f

# 7. Port-forward to access services
kubectl -n argocd port-forward --address 0.0.0.0 svc/argocd-server 8080:443 &
kubectl -n traffic-violation port-forward --address 0.0.0.0 svc/traffic-violation 8501:8501 &
kubectl -n traffic-violation port-forward --address 0.0.0.0 svc/traffic-violation 5000:5000 &
```

# ArgoCD Deployment Guide — Traffic Violation Detection System

## Files in this folder

| File | Purpose |
|------|---------|
| `deploy.sh` | **One-shot deploy script** — run this after bootstrap, handles everything |
| `argocd-app.yaml` | ArgoCD `Application` CR — watched by `deploy.sh` |
| `ecr-refresh-cronjob.yaml` | CronJob that refreshes ECR token every 10h automatically |
| `worker-aws-secret.yaml` | Secret template (placeholder only — `deploy.sh` creates the real one) |
| `README-ARGOCD.md` | This guide |

---

## Full deployment in 3 commands

```bash
# 1. SSH into EC2
ssh -i your-key.pem ubuntu@<EC2_PUBLIC_IP>

# 2. Clone repo + bootstrap cluster (~10 min)
git clone https://github.com/HamzaMaLik121/Traffic_Voilation_final.git
cd Traffic_Voilation_final
chmod +x bootstrap-kind-platform.sh
sudo ./bootstrap-kind-platform.sh

# 3. Deploy everything in one shot
bash argocd/deploy.sh \
  --access-key  AKIAXXXXXXXXXXXXXXXXX \
  --secret-key  "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

That's it. `deploy.sh` handles:
- Creates `traffic-violation` namespace
- Creates AWS credentials secret (for worker S3 pull)
- Logs into ECR and creates `ecr-credentials` imagePullSecret
- Deploys the ECR token refresh CronJob (auto-refreshes every 10h)
- Applies `argocd-app.yaml` — ArgoCD takes over from here
- Waits for sync and prints access URLs + ArgoCD password

---

## Architecture

```
GitHub (main branch)
      │  ArgoCD polls every 3 min
      ▼
ArgoCD → deploys Helm chart → traffic-violation namespace
                                  ├── worker  (YOLOv8 pipeline, pulls models from S3)
                                  ├── api     (Flask REST + MJPEG stream)
                                  └── dashboard (Streamlit UI)

ECR token refresh CronJob runs every 10h → no manual ECR login needed
```

---

## GitOps update flow (future deploys)

Every change goes through Git. No `kubectl apply` needed after first deploy.

```bash
# On your local machine — edit anything, then:
git add .
git commit -m "your change"
git push origin main
# ArgoCD picks it up within ~3 minutes automatically
```

---

## Access the services

Run port-forwards in a `tmux` session so they survive SSH disconnect:

```bash
tmux new -s ports
kubectl -n argocd port-forward --address 0.0.0.0 svc/argocd-server 8080:443 &
kubectl -n traffic-violation port-forward --address 0.0.0.0 svc/traffic-violation 8501:8501 &
kubectl -n traffic-violation port-forward --address 0.0.0.0 svc/traffic-violation 5000:5000 &
# Ctrl+B then D to detach
```

| Service | URL |
|---------|-----|
| Dashboard | `http://<EC2_IP>:8501` |
| API | `http://<EC2_IP>:5000` |
| ArgoCD UI | `https://<EC2_IP>:8080` |
| Grafana | `http://<EC2_IP>:3000` (admin / admin123) |

EC2 Security Group must allow inbound TCP on ports: 22, 80, 8080, 8501, 5000, 3000

---

## EC2 stop/start (instance restart)

The bootstrap script installs a systemd service that automatically restarts
the KinD cluster when EC2 boots. After the instance starts again:

```bash
# Wait ~2 min for cluster to recover, then check
kubectl get pods -A

# If ECR token expired (>12h downtime), refresh it:
bash argocd/ecr-login.sh
```

---

## Troubleshooting

### Worker not pulling models from S3
```bash
kubectl logs -n traffic-violation -c worker \
  $(kubectl get pod -n traffic-violation -o name | head -1)
```
If you see "AWS credentials not found" — recreate the secret:
```bash
kubectl delete secret traffic-violation-aws-credentials -n traffic-violation
kubectl create secret generic traffic-violation-aws-credentials \
  --namespace traffic-violation \
  --from-literal=AWS_ACCESS_KEY_ID=YOUR_KEY \
  --from-literal=AWS_SECRET_ACCESS_KEY=YOUR_SECRET
kubectl rollout restart deployment/traffic-violation -n traffic-violation
```

### ErrImagePull / ImagePullBackOff
ECR token expired. Refresh it:
```bash
bash argocd/ecr-login.sh
kubectl rollout restart deployment/traffic-violation -n traffic-violation
```

### ArgoCD OutOfSync
```bash
kubectl patch application traffic-violation -n argocd \
  --type merge \
  -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD"}}}'
```

### Check everything at once
```bash
kubectl get all,pvc,secret,configmap,ingress -n traffic-violation
kubectl get events -n traffic-violation --sort-by='.lastTimestamp' | tail -20
```

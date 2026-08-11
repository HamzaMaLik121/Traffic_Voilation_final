# Where these files go in your `Traffic_Voilation_final` repo

```
Traffic_Voilation_final/                     ← your existing repo root
│
├── bootstrap-kind-platform.sh                ← COPY to repo root (new file)
│
├── dashboard/
│   └── app/
│       └── dashboard.py                      ← REPLACE this existing file
│                                                 with dashboard.py from this zip
│
└── traffic-violation-chart/                  ← COPY this whole folder
    │                                            to repo root (new folder)
    ├── Chart.yaml
    ├── values.yaml
    ├── files/
    │   └── lane_config.json
    └── templates/
        ├── NOTES.txt
        ├── _helpers.tpl
        ├── configmap-lane-config.yaml
        ├── deployment.yaml
        ├── ingress.yaml
        ├── namespace.yaml
        ├── pvc.yaml
        ├── secret-aws.yaml
        └── servicemonitor.yaml
```

## Architecture: sidecar pattern

worker, api, and dashboard run as **3 containers in 1 Pod** (1 Deployment,
`replicas: 1`), sharing a single PVC via `subPath` mounts. No NFS server,
no RWX StorageClass — just KinD's default local-path provisioner.

This is simpler than a separate-Deployments design and fits this app
well because worker can only ever run as 1 replica anyway (single SQLite
writer, single video pipeline) — so independent scaling of api/dashboard
was never actually usable here. The trade-off: all 3 containers restart
and get scheduled together as one unit.

## What each file is

| File/folder | Action | Purpose |
|---|---|---|
| `bootstrap-kind-platform.sh` | Copy to repo root | Creates the KinD cluster (3 nodes) + installs ingress-nginx, metrics-server, Prometheus/Grafana, Trivy Operator, ArgoCD |
| `dashboard.py` | **Replace** `dashboard/app/dashboard.py` | Fixes the MJPEG live-feed URL to use the `STREAM_URL` env var instead of guessing a Docker-Compose-only port |
| `traffic-violation-chart/` | Copy whole folder to repo root | Helm chart deploying your app as 1 Pod / 3 sidecar containers |

## Run order

```bash
# 1. Build the cluster + platform tooling
chmod +x bootstrap-kind-platform.sh
./bootstrap-kind-platform.sh

# 2. Build your 3 app images (from repo root)
docker build -t traffic-worker:latest    ./worker
docker build -t traffic-api:latest       ./api
docker build -t traffic-dashboard:latest ./dashboard

# 3. Load them into the KinD cluster
kind load docker-image traffic-worker:latest    --name traffic-platform
kind load docker-image traffic-api:latest       --name traffic-platform
kind load docker-image traffic-dashboard:latest --name traffic-platform

# 4. Deploy the app via Helm (no `helm dependency update` needed —
#    this version has no sub-chart)
cd traffic-violation-chart
helm install traffic-violation . \
  --set aws.accessKeyId=YOUR_KEY \
  --set aws.secretAccessKey=YOUR_SECRET

# 5. Watch it come up (all 3 containers are in ONE pod)
kubectl get pods -n traffic-violation -w
kubectl logs -n traffic-violation deploy/traffic-violation -c worker -f
```

Then add `127.0.0.1 traffic.local.test` to your `/etc/hosts` and open
`http://traffic.local.test` in a browser.

## Note on `podSecurityContext.runAsNonRoot`

Currently `false` in `values.yaml` — some CV libraries (EasyOCR cache,
model writes) expect root as the worker image is currently built. If
you want this hardened, it needs a change to `worker/Dockerfile`
(non-root user + correct file ownership), not just the chart.

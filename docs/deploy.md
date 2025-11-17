# Deployment Guide

## Prerequisites

- `rockcraft` installed
- `docker` installed
- `juju` installed and configured
- Access to a Kubernetes cluster

## Deploy Temporal Server

Before deploying the worker, you need a Temporal server running. You can deploy it using Juju:

```bash
juju add-model temporal

# Deploy Temporal server
juju deploy temporal-k8s --channel 1.23/edge

# Wait for deployment to complete
juju wait-for application temporal-k8s --query='status=="active"'

# Get Temporal server address
juju status temporal-k8s

# Database
juju deploy postgresql-k8s --channel 14/stable --trust
juju relate temporal-k8s:db postgresql-k8s:database
juju relate temporal-k8s:visibility postgresql-k8s:database

# Admin
juju deploy temporal-admin-k8s --channel 1.23/edge
juju relate temporal-k8s:admin temporal-admin-k8s:admin

# UI
juju deploy temporal-ui-k8s  --channel 1.23/edge
juju integrate temporal-k8s:ui temporal-ui-k8s:ui

# Expose UI
kubectl port-forward -n temporal pod/temporal-ui-k8s-0 8080:8080
```

Once deployed, note the Temporal server address (typically the service IP or hostname). You'll need this when deploying the worker.

## Build and Push ROCK Image

```bash
# Generate lock file
uv lock

# Build ROCK image
make rock-build

# Load into Docker
make rock-load

# Tag for registry
make rock-tag
```

And make sure the image is import and available on the k8s registry.

## Deploy Worker with Juju

Get the Temporal server address from your deployment. If both the Temporal server and worker are in the same Kubernetes cluster, use the internal service address:

Deploy the worker:

```bash
# Deploy worker
juju deploy temporal-worker-k8s catcher-agent-worker --channel stable \
    --resource temporal-worker-image=ghcr.io/jneo8/catcher-agent-worker:0.1.0 \
    --config host="temporal-k8s.temporal.svc.cluster.local:7233" \
    --config namespace=default \
    --config queue=catcher-agent-queue \
    --config log-level=info

# Check deployment status
juju status catcher-agent-worker

# View worker logs
juju debug-log --include catcher-agent-worker --tail

# Scale to multiple workers (optional)
juju scale-application catcher-agent-worker 3
```

# Add Gemini API key to worker

```bash
juju add-secret gemini-api-key gemini-api-key={your-api-key}

# Output: secret:<secret_id1>

juju grant-secret gemini-api-key catcher-agent-worker
juju config catcher-agent-worker environment=@./environment.yaml
```

`environment.yaml`

```yaml
juju:
  secret-id: <secret_id1>
```

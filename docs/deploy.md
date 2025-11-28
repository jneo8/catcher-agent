# Local Deployment Guide

## Prerequisites

- `rockcraft` installed
- `charmcraft` installed
- `docker` installed
- `juju` installed and configured
- Access to a Kubernetes cluster

## Deploy COS-lite

Follow the instruction on official document to deploy cos-lite: https://charmhub.io/cos-lite.

## Deploy Temporal Server

Before deploying the worker, you need a Temporal server running. You can deploy it using Juju.

You can follow the official document to deploy : https://charmhub.io/temporal-k8s/docs/t-deploy-server
or follow below instruction:

```bash
juju add-model temporal

# Deploy Temporal server
juju deploy temporal-k8s --channel 1.23/edge --config num-history-shards=4

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

## Deploy catcher-agent temporal worker

### Build and Push ROCK Image

```bash
cd ./catcher-agent-worker

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

### Deploy Worker with Juju

Get the Temporal server address from your deployment. If both the Temporal server and worker are in the same Kubernetes cluster, use the internal service address:

Deploy the worker:

```bash
# Deploy worker
juju deploy temporal-worker-k8s catcher-agent-worker --channel stable --resource temporal-worker-image=ghcr.io/jneo8/catcher-agent-worker:0.1.0 --config host="temporal-k8s.temporal.svc.cluster.local:7233" --config namespace=default --config queue=catcher-agent-queue --config log-level=info
```

```sh
juju run temporal-admin-k8s/0 cli args="operator namespace create --namespace default --retention 3d" --wait 1m
```

### Add Gemini API key to worker

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

## Deploy Catcher-Agent-Receiver-Operator

The catcher-agent-receiver-operator is a FastAPI-based webhook receiver that accepts Alertmanager notifications and triggers the catcher agent workflow. It runs as a Juju charm on Kubernetes.

### Build and Push the ROCK Image

```bash
cd ./catcher-agent-receiver-operator

# Generate requirements.txt from pyproject.toml
uv lock
make requirements

# Build ROCK image
make rock-build

# Load into Docker
make rock-load

# Tag for registry
make rock-tag
```

And make sure the image is import and available on the k8s registry.

### Build the Charm

```bash
# Build charm package
make charm-build
```

This will create a `catcher-agent-receiver-operator_amd64.charm` file.

### Deploy the Charm

Deploy the charm with the app image as a resource:

> This tutorial deploy the receiver in the same juju model as temporal.
> You can switch to different model but remember to change the namespace in the address.

```bash
juju switch temporal

# Deploy with specific image version
juju deploy ./catcher-agent-receiver-operator_amd64.charm \
    --resource app-image=ghcr.io/jneo8/catcher-agent-receiver-operator:0.1
```

### Access the Webhook Service

The service exposes several endpoints:

- `GET /` - Root endpoint (returns service status)
- `GET /health` - Health check endpoint
- `POST /webhook/alertmanager` - Alertmanager webhook endpoint

To access the service, you can use port-forwarding:

```bash
# Get the pod name
kubectl get pods -n <model-name> | grep catcher-agent-receiver

# Port forward to local machine
kubectl port-forward -n temporal svc/catcher-agent-receiver-operator 8080:8080

# Test the endpoints
curl http://localhost:8080/
curl http://localhost:8080/health
```

### Configure Alertmanager

> Please make sure you have cos-lite deployed before this step.

Configure Alertmanager to send notifications to the webhook endpoint:

```yaml
# alertmanager.yml
receivers:
  - name: 'catcher-agent'
    webhook_configs:
      - url: 'http://catcher-agent-receiver-operator.temporal.svc.cluster.local:8080/webhook/alertmanager'
        send_resolved: true

route:
  receiver: 'catcher-agent'
  group_by: ['alertname']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 1h
```

Then using below command to see the request received by the receiver:

```sh
kubectl logs -f -n temporal catcher-agent-receiver-operator-0 -c app
```

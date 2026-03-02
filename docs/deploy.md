# Local Deployment Guide

## Prerequisites

- `rockcraft` installed
- `charmcraft` installed
- `docker` installed
- `juju` installed and configured
- Access to a Kubernetes cluster

## Deploy COS-lite

Follow the instruction on official document to deploy cos-lite: https://charmhub.io/cos-lite.

### Configuring Storage for COS-lite Components

To require more storage for Prometheus, Loki, and Alertmanager, you can use an overlay file during deployment. Create a `cos-storage-overlay.yaml` file with the desired storage configurations:

```yaml
bundle: kubernetes
applications:
  prometheus:
    storage:
      database: 10G
  loki:
    storage:
      # This stores the index (metadata)
      active-index-directory: 2G
      # This stores the actual log data (chunks)
      loki-chunks: 10G
  alertmanager:
    storage:
      data: 2G
```

Then, deploy `cos-lite` using the overlay file:

```bash
juju deploy cos-lite --trust --overlay @./cos-storage-overlay.yaml
```

This will deploy `cos-lite` with the specified storage requirements for its components.

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

## Deploy ein-agent temporal worker

### Build and Push ROCK Image

```bash
cd ./rocks/ein-agent-worker

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
juju deploy temporal-worker-k8s ein-agent-worker --channel stable --resource temporal-worker-image=ghcr.io/jneo8/ein-agent-worker:0.1.0 --config host="temporal-k8s.temporal.svc.cluster.local:7233" --config namespace=default --config queue=ein-agent-queue --config log-level=info
```

```sh
juju run temporal-admin-k8s/0 cli args="operator namespace create --namespace default --retention 3d" --wait 1m
```

### Add Gemini API key to worker

```bash
juju add-secret gemini-api-key gemini-api-key={your-api-key}

# Output: secret:<secret_id1>

juju grant-secret gemini-api-key ein-agent-worker
juju config ein-agent-worker environment=@./environment.yaml
```

`environment.yaml`

```yaml
juju:
  secret-id: <secret_id1>
```

## Offline/Air-gapped Deployment

When deploying in restricted network environments, the worker may fail to connect to `openaipublic.blob.core.windows.net`. This is caused by **tiktoken** (the tokenizer library used by LiteLLM) attempting to download encoding files.

To disable tiktoken network requests, set the following environment variable:

```yaml
TIKTOKEN_CACHE_DIR: ""
```

## Using Ein-Agent-CLI

The `ein-agent-cli` is a command-line tool for querying Alertmanager and triggering incident correlation workflows in Temporal.

For detailed usage and examples, please refer to the [ein-agent-cli/README.md](../ein-agent-cli/README.md) file.
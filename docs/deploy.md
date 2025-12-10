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

## Using Ein-Agent-CLI

The ein-agent-cli is a command-line tool that queries Alertmanager and triggers incident correlation workflows in Temporal.

### Installation

```bash
cd ./ein-agent-cli

# Install dependencies using uv
uv sync

# Or install in development mode
uv pip install -e .
```

### Basic Usage

Query Alertmanager and trigger workflows:

```bash
# Run with default settings (queries local Alertmanager)
uv run python -m ein_agent_cli

# Query remote Alertmanager
uv run python -m ein_agent_cli \
    -a http://alertmanager.example.com:9093 \
    --temporal-host temporal-k8s.temporal.svc.cluster.local:7233

# Dry run to see what would be triggered without actually triggering
uv run python -m ein_agent_cli --dry-run

# Skip confirmation prompt and trigger automatically
uv run python -m ein_agent_cli -y
```

### Filtering Alerts

Filter alerts by name or fingerprint:

```bash
# Include only specific alerts by name
uv run python -m ein_agent_cli \
    -i KubePodNotReady \
    -i KubePodCrashLooping

# Include specific alerts by fingerprint
uv run python -m ein_agent_cli -i 07d5a192e71c

# Mix alert names and fingerprints
uv run python -m ein_agent_cli \
    -i KubePodNotReady \
    -i 07d5a192e71c

# Custom blacklist (exclude specific alerts)
uv run python -m ein_agent_cli -b TargetDown -b Watchdog

# Disable default blacklist
uv run python -m ein_agent_cli -b ''
```

### Filtering by Status

```bash
# Only firing alerts (default)
uv run python -m ein_agent_cli --status firing

# Only resolved alerts
uv run python -m ein_agent_cli --status resolved

# All alerts regardless of status
uv run python -m ein_agent_cli --status all
```

### Display Options

```bash
# Show full labels in the alert table
uv run python -m ein_agent_cli --show-labels

# Example output without --show-labels:
# Shows: #, Alert Name, Status, Severity, Namespace, Fingerprint

# Example output with --show-labels:
# Shows: #, Alert Name, Status, Severity, Namespace, Fingerprint, Labels
```

### Configuration

Configure Temporal connection:

```bash
# Set Temporal host, namespace, and queue
uv run python -m ein_agent_cli \
    --temporal-host localhost:7233 \
    --temporal-namespace default \
    --temporal-queue ein-agent-queue
```

Configure MCP servers to use:

```bash
# Specify MCP servers (default: kubernetes, grafana)
uv run python -m ein_agent_cli \
    -m kubernetes \
    -m grafana \
    -m prometheus
```

### Complete Example

```bash
# Query Alertmanager, filter alerts, review, and trigger workflow
uv run python -m ein_agent_cli \
    -a http://10.100.100.12/cos-alertmanager \
    --temporal-host temporal-k8s.temporal.svc.cluster.local:7233 \
    --temporal-namespace default \
    --status firing \
    -i KubePodNotReady \
    -i KubePodCrashLooping \
    -b Watchdog \
    -m kubernetes \
    -m grafana \
    --show-labels

# Automated workflow trigger (no confirmation prompt)
uv run python -m ein_agent_cli \
    -a http://10.100.100.12/cos-alertmanager \
    --temporal-host temporal-k8s.temporal.svc.cluster.local:7233 \
    -i KubePodNotReady \
    -y
```

### Getting Help

```bash
# Show all available options
uv run python -m ein_agent_cli --help
```

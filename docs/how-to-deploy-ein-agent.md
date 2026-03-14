# Local Deployment Guide

## Prerequisites

- `rockcraft` installed
- `charmcraft` installed
- `docker` installed
- `juju` installed and configured
- Access to a Kubernetes cluster

## Deploy COS-lite

Follow the instruction on official document to deploy cos-lite: https://charmhub.io/cos-lite.

### Configuring Storage and Channels for COS-lite

To configure storage for Prometheus, Loki, and Alertmanager, and set the channels for all COS components, use an overlay file during deployment. Create a `cos-lite-overlay.yaml` file:

```yaml
bundle: kubernetes
applications:
  alertmanager:
    channel: 2/stable
    storage:
      data: 2G
  catalogue:
    channel: 2/stable
  grafana:
    channel: 2/stable
  loki:
    channel: 2/stable
    storage:
      # This stores the index (metadata)
      active-index-directory: 2G
      # This stores the actual log data (chunks)
      loki-chunks: 10G
  prometheus:
    channel: 2/stable
    storage:
      database: 10G
```

Then, deploy `cos-lite` using the overlay file:

```bash
juju deploy cos-lite --trust --overlay @./cos-lite-overlay.yaml
```

This will deploy `cos-lite` with:
- All components (alertmanager, catalogue, grafana, loki, prometheus) from the `2/stable` channel
- Specified storage requirements for Prometheus, Loki, and Alertmanager

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

### Create Temporal Namespace

Create the default namespace if it doesn't exist:

```bash
juju run temporal-admin-k8s/0 -m temporal cli args="operator namespace create --namespace default --retention 3d" --wait 1m
```

### Configure Kubernetes ServiceAccount for UTCP

Create a ServiceAccount with read-only permissions for the AI agent to troubleshoot Kubernetes:

```bash
# Create ServiceAccount
kubectl create serviceaccount ein-agent -n default

# Grant read-only permissions
kubectl create clusterrolebinding ein-agent-viewer \
    --clusterrole=view \
    --serviceaccount=default:ein-agent

# Generate kubeconfig with long-lived token (1 year)
CONTEXT=$(kubectl config current-context)
CLUSTER=$(kubectl config view -o jsonpath="{.contexts[?(@.name=='$CONTEXT')].context.cluster}")
SERVER=$(kubectl config view -o jsonpath="{.clusters[?(@.name=='$CLUSTER')].cluster.server}")
CA_DATA=$(kubectl config view --raw -o jsonpath="{.clusters[?(@.name=='$CLUSTER')].cluster.certificate-authority-data}")
TOKEN=$(kubectl create token ein-agent -n default --duration=8760h)  # 1 year

# Create kubeconfig file
cat > ein-agent-kubeconfig.yaml <<EOF
apiVersion: v1
kind: Config
clusters:
- cluster:
    certificate-authority-data: $CA_DATA
    server: $SERVER
  name: $CLUSTER
contexts:
- context:
    cluster: $CLUSTER
    user: ein-agent
  name: ein-agent-context
current-context: ein-agent-context
users:
- name: ein-agent
  user:
    token: $TOKEN
EOF

# Verify kubeconfig works
kubectl --kubeconfig=ein-agent-kubeconfig.yaml get pods -n default
```

### Add Secrets to Juju

Create Juju secrets for LLM API key, Kubernetes kubeconfig, and Grafana token:

```bash
# 1. Gemini API key
juju add-secret -m temporal gemini-api-key api-key={your-gemini-api-key}
# Output: secret:<secret_id1>

# 2. Kubernetes kubeconfig (base64-encoded)
bash -c 'KUBECONFIG_B64=$(cat ein-agent-kubeconfig.yaml | base64 -w 0) && juju add-secret -m temporal kubernetes-auth kubeconfig-content="$KUBECONFIG_B64"'
# Output: secret:<secret_id2>

# 3. Grafana service account token
juju add-secret -m temporal grafana-auth token={your-grafana-service-account-token}
# Output: secret:<secret_id3>
```

### Configure Worker Environment

Create an `environment.yaml` file with your configuration:

```yaml
env:
  # UTCP Service Configuration
  - name: UTCP_SERVICES
    value: kubernetes,grafana,ceph

  # Kubernetes UTCP Configuration
  # NOTE: Kubernetes ONLY supports kubeconfig auth (no bearer token support)
  - name: UTCP_KUBERNETES_OPENAPI_URL
    value: https://kubernetes.default.svc.cluster.local/openapi/v2
  - name: UTCP_KUBERNETES_AUTH_TYPE
    value: kubeconfig  # REQUIRED: Must be kubeconfig
  - name: UTCP_KUBERNETES_ENABLED
    value: "true"
  - name: UTCP_KUBERNETES_VERSION
    value: "1.35"
  - name: UTCP_KUBERNETES_INSECURE
    value: "true"  # For clusters with self-signed certificates

  # Grafana UTCP Configuration
  # NOTE: Grafana uses bearer token (service account token)
  - name: UTCP_GRAFANA_OPENAPI_URL
    value: https://grafana.cos.svc.cluster.local:3000/api/swagger.json
  - name: UTCP_GRAFANA_AUTH_TYPE
    value: bearer  # Service account token
  - name: UTCP_GRAFANA_ENABLED
    value: "true"
  - name: UTCP_GRAFANA_VERSION
    value: "12"
  - name: UTCP_GRAFANA_INSECURE
    value: "true"  # For self-signed certificates

  # Ceph UTCP Configuration
  - name: UTCP_CEPH_OPENAPI_URL
    value: https://ceph-mgr.ceph.svc.cluster.local:8443/api/openapi.json
  - name: UTCP_CEPH_AUTH_TYPE
    value: jwt
  - name: UTCP_CEPH_ENABLED
    value: "true"
  - name: UTCP_CEPH_VERSION
    value: tentacle

  # Agent model
  - name: EIN_AGENT_MODEL
    value: "gemini/gemini-3-flash-preview"

  # Alertmanager
  - name: ALERTMANAGER_URL
    value: http://alertmanager.cos.svc.cluster.local:9093

juju:
  # Gemini API key
  - secret-id: <secret_id1>
    name: GEMINI_API_KEY
    key: api-key

  # Kubernetes kubeconfig (base64-encoded) - REQUIRED for K8s
  - secret-id: <secret_id2>
    name: UTCP_KUBERNETES_KUBECONFIG_CONTENT
    key: kubeconfig-content

  # Grafana service account token - REQUIRED for Grafana
  - secret-id: <secret_id3>
    name: UTCP_GRAFANA_TOKEN
    key: token
```

### Deploy Worker

Deploy the worker with your ROCK image:

```bash
juju deploy temporal-worker-k8s ein-agent-worker -m temporal \
  --channel stable \
  --resource temporal-worker-image=ghcr.io/jneo8/ein-agent-worker:0.1.0 \
  --config host="temporal-k8s.temporal.svc.cluster.local:7233" \
  --config namespace=default \
  --config queue=ein-agent-queue \
  --config log-level=info
```

### Grant Secrets and Configure Environment

Grant the secrets to the worker and apply the environment configuration:

```bash
# Grant all secrets to worker
juju grant-secret -m temporal gemini-api-key ein-agent-worker
juju grant-secret -m temporal kubernetes-auth ein-agent-worker
juju grant-secret -m temporal grafana-auth ein-agent-worker

# Apply environment configuration
juju config ein-agent-worker -m temporal environment=@./environment.yaml
```

Wait for the worker to become active:

```bash
juju status -m temporal ein-agent-worker
```

### UTCP Service Configuration

UTCP (Universal Tool Calling Protocol) generates tools dynamically from OpenAPI specifications. Each service requires:

| Variable | Description |
|----------|-------------|
| `UTCP_SERVICES` | Comma-separated list of services to enable |
| `UTCP_{SERVICE}_OPENAPI_URL` | URL to the service's OpenAPI spec |
| `UTCP_{SERVICE}_AUTH_TYPE` | Authentication: `kubeconfig`, `bearer`, `api_key`, `jwt` |
| `UTCP_{SERVICE}_VERSION` | Optional: spec version (e.g., `1.35`, `tentacle`) |
| `UTCP_{SERVICE}_ENABLED` | Optional: enable/disable service (default: true) |
| `UTCP_{SERVICE}_INSECURE` | Optional: skip TLS verification (default: false) |

**Supported Services:**
- **kubernetes**: Requires `kubeconfig` auth (kubeconfig passed via Juju secret)
- **grafana**: Requires `bearer` auth (service account token via Juju secret)
- **ceph**: Requires `jwt` auth (Ceph dashboard JWT token)

### OpenAPI Spec Loading: Local Files vs Live URLs

UTCP supports loading OpenAPI specs from either **local files** or **live URLs**. Local files take priority - if a local spec file exists, it will be used instead of fetching from the live URL.

**Loading Priority:**
1. Check for local spec file at `specs/{service_name}/{version}.json`
2. If found → Load from local file (faster, works offline)
3. If not found → Fetch from `UTCP_{SERVICE}_OPENAPI_URL`

**Local Spec Directory Structure:**
```
rocks/ein-agent-worker/specs/
├── kubernetes/
│   └── 1.35.json
├── grafana/
│   └── 12.json
└── ceph/
    └── tentacle.json
```

**Using Local Spec Files:**

1. Download the spec to the appropriate directory:
   ```bash
   # Example: Download Kubernetes OpenAPI spec
   curl -k "https://<K8S_SERVER>/openapi/v2" -o specs/kubernetes/1.35.json
   ```

2. Set the version in your environment configuration:
   ```yaml
   - name: UTCP_KUBERNETES_VERSION
     value: "1.35"
   ```

3. The worker will automatically use the local file when it exists.

**Forcing Live URL Loading:**

To always fetch from the live URL, either:
- Remove the local spec file, OR
- Set `UTCP_{SERVICE}_VERSION` to a version that doesn't have a local file

**Log Output:**

Local file loading:
```
[kubernetes] Loading OpenAPI spec from LOCAL file: .../specs/kubernetes/1.35.json
```

Live URL loading:
```
[kubernetes] Loading OpenAPI spec from LIVE URL: https://10.x.x.x:6443/openapi/v2
```

## Offline/Air-gapped Deployment

When deploying in restricted network environments, the worker may fail to connect to `openaipublic.blob.core.windows.net`. This is caused by **tiktoken** (the tokenizer library used by LiteLLM) attempting to download encoding files.

To disable tiktoken network requests, set the following environment variable:

```yaml
TIKTOKEN_CACHE_DIR: ""
```

## Using Ein-Agent-CLI

The `ein-agent-cli` is a command-line tool for starting interactive human-in-the-loop investigation workflows in Temporal.

For detailed usage and examples, please refer to the [ein-agent-cli/README.md](../ein-agent-cli/README.md) file.

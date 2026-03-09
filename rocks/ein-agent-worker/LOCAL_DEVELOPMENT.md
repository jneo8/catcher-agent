# Local Development Guide

This guide explains how to run the ein-agent-worker locally for development and testing.

## Prerequisites

- Python 3.12+
- uv package manager
- Access to a Temporal server (local or remote)
- (Optional) Kubernetes cluster access for UTCP integration
- (Optional) Gemini API key or other LLM provider credentials

## Quick Start

1. **Set up environment variables**

   Copy the example script and configure your credentials:
   ```bash
   cp run-worker-local.sh run-worker-local.sh.local
   chmod +x run-worker-local.sh.local
   ```

   Edit `run-worker-local.sh.local` and replace placeholder values:
   - `GEMINI_API_KEY`: Your Gemini API key
   - `UTCP_KUBERNETES_OPENAPI_URL`: Your Kubernetes API server URL
   - `UTCP_KUBERNETES_TOKEN`: ServiceAccount token for Kubernetes access
   - `ALERTMANAGER_URL`: Your Alertmanager URL

2. **Install dependencies**

   ```bash
   uv sync
   ```

3. **Run the worker**

   ```bash
   ./run-worker-local.sh.local
   ```

## Configuration

### Environment Variables

Configure all required environment variables:

```bash
# LLM Provider
export GEMINI_API_KEY="your-api-key"
export EIN_AGENT_MODEL="gemini/gemini-3-flash-preview"

# Kubernetes UTCP Configuration
export UTCP_KUBERNETES_OPENAPI_URL="https://<K8S_SERVER>:6443/openapi/v2"
export UTCP_KUBERNETES_TOKEN="<token from kubectl create token>"
export UTCP_KUBERNETES_INSECURE="true"  # For self-signed certificates

# Temporal Configuration
export TEMPORAL_HOST="localhost:7233"
export TEMPORAL_NAMESPACE="default"
export TEMPORAL_QUEUE="ein-agent-queue"

# Alertmanager (Optional)
export ALERTMANAGER_URL="http://your-alertmanager-url/cos-alertmanager"
```

Supported LLM models via LiteLLM:
- Gemini: `gemini/gemini-3-flash-preview`, `gemini/gemini-1.5-pro`
- OpenAI: `gpt-4o`, `gpt-4-turbo`
- Other LiteLLM-supported providers

### Kubernetes ServiceAccount Setup

To enable Kubernetes UTCP tools, create a ServiceAccount with appropriate permissions:

```bash
# Create ServiceAccount
kubectl create serviceaccount ein-agent -n default

# Create ClusterRoleBinding (cluster-admin for full access)
kubectl create clusterrolebinding ein-agent-admin \
    --clusterrole=cluster-admin \
    --serviceaccount=default:ein-agent

# Generate token (valid for 24 hours)
kubectl create token ein-agent -n default --duration=24h

# Get the Kubernetes API server URL
kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}'
```

## Development Workflow

1. **Make code changes** in `ein_agent_worker/` directory

2. **Test locally** by running the worker:
   ```bash
   ./run-worker-local.sh.local
   ```

3. **Monitor logs** - the worker will output logs showing:
   - UTCP service initialization
   - Workflow execution
   - Activity execution
   - Agent responses

## Troubleshooting

### Worker won't start

- Check that Temporal server is accessible: `telnet localhost 7233`
- Verify Python version: `python --version` (must be 3.12+)
- Ensure dependencies are installed: `uv sync`

### UTCP tools not loading

- Verify Kubernetes token is valid: `kubectl --token=$UTCP_KUBERNETES_TOKEN get nodes`
- Check OpenAPI URL is accessible: `curl -k $UTCP_KUBERNETES_OPENAPI_URL`
- Review worker logs for UTCP initialization errors

### LLM errors

- Verify API key is set: `echo $GEMINI_API_KEY`
- Check model name is correct for your provider
- Ensure you have API quota/credits available

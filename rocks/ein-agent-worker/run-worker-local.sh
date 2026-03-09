#!/bin/bash
set -e

# Gemini API Key
export GEMINI_API_KEY="${GEMINI_API_KEY:-your-gemini-api-key-here}"

# =============================================================================
# UTCP Service Configuration
# =============================================================================
# See CLAUDE.md for instructions on setting up Kubernetes ServiceAccount and token

export UTCP_SERVICES="kubernetes,grafana"

# Kubernetes UTCP Configuration (direct API access with bearer token)
# To get these values, run: make setup-k8s-token (or see CLAUDE.md)
export UTCP_KUBERNETES_OPENAPI_URL="${UTCP_KUBERNETES_OPENAPI_URL:-https://your-k8s-server:6443/openapi/v2}"
export UTCP_KUBERNETES_AUTH_TYPE="bearer"
export UTCP_KUBERNETES_TOKEN="${UTCP_KUBERNETES_TOKEN:-your-kubernetes-token-here}"
export UTCP_KUBERNETES_INSECURE="true"
export UTCP_KUBERNETES_ENABLED="true"
export UTCP_KUBERNETES_VERSION="1.35"

# Grafana UTCP Configuration (aggregated API server)
export UTCP_GRAFANA_OPENAPI_URL="${UTCP_GRAFANA_OPENAPI_URL:-https://your-grafana-server/openapi/v2}"
export UTCP_GRAFANA_AUTH_TYPE="bearer"
export UTCP_GRAFANA_TOKEN="${UTCP_GRAFANA_TOKEN:-your-grafana-token-here}"
export UTCP_GRAFANA_INSECURE="true"
export UTCP_GRAFANA_ENABLED="true"
export UTCP_GRAFANA_VERSION="12"

# =============================================================================
# Temporal Configuration
# =============================================================================
export TEMPORAL_HOST="${TEMPORAL_HOST:-localhost:7233}"
export TEMPORAL_NAMESPACE="${TEMPORAL_NAMESPACE:-default}"
export TEMPORAL_QUEUE="${TEMPORAL_QUEUE:-ein-agent-queue}"

# =============================================================================
# Other Configuration
# =============================================================================

# Alert manager
export ALERTMANAGER_URL="${ALERTMANAGER_URL:-http://your-alertmanager-url/cos-alertmanager}"

# Model config
export EIN_AGENT_MODEL="${EIN_AGENT_MODEL:-gemini/gemini-3-flash-preview}"

# DSPy Prompt Optimization (see docs/dspy-prompt-optimization.md)
export EIN_COLLECT_TRAINING_DATA="true"
export EIN_TRAINING_DATA_PATH="./training_data"
export EIN_PROMPT_STORE_PATH="./prompts"
export EIN_PROMPT_VERSION="latest"

# =============================================================================
# Start Worker
# =============================================================================
echo "Starting Ein Agent Worker..."
echo "Temporal: $TEMPORAL_HOST"
echo "Queue: $TEMPORAL_QUEUE"
echo "UTCP Services: $UTCP_SERVICES"

# Run the worker
cd "$(dirname "$0")"
uv run -m ein_agent_worker.worker

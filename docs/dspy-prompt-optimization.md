# DSPy Prompt Optimization Guide

This guide explains how to use DSPy to optimize agent prompts in ein-agent.

## Overview

The DSPy integration allows you to:
1. Collect training data from agent interactions
2. Optimize prompts using DSPy's BootstrapFewShot
3. Evaluate optimized prompts on test data
4. Deploy optimized prompts for runtime use

## Prerequisites

The DSPy optimization tools are located in the `rocks/ein-agent-worker` directory.

```bash
# Navigate to the worker directory
cd rocks/ein-agent-worker

# Install dependencies
uv sync
```

## Workflow

### Step 1: Collect Training Data

Enable data collection on the **worker**:

```bash
# Set these environment variables on the worker before starting it
export EIN_COLLECT_TRAINING_DATA=true
export EIN_TRAINING_DATA_PATH=./training_data/logs  # Optional, defaults to ./training_data/logs
```

When the worker processes workflows, agent interactions will be saved automatically to date-organized subdirectories (e.g., `./training_data/logs/2026-01-26/...`).

### Step 2: Export Training Data

Export collected interactions as DSPy-compatible examples into a curated dataset:

```bash
# Export for a specific agent (defaults to ./training_data/datasets/)
uv run ein-agent-dspy export --agent compute_specialist

# Export with custom output and outcome filter
uv run ein-agent-dspy export -a project_manager -o ./training_data/datasets/ --outcome success
```

**Available agents:**
- `investigation_agent` - Main orchestrator (HITL workflow)
- `compute_specialist` - Kubernetes/compute domain expert
- `storage_specialist` - Ceph/storage domain expert
- `network_specialist` - Network domain expert
- `project_manager` - Incident report synthesizer (IncidentCorrelationWorkflow)

### Step 3: Compile (Optimize) Prompts

Run DSPy BootstrapFewShot optimization:

# With validation set and custom settings
uv run ein-agent-dspy compile \
    -a project_manager \
    -t ./training_data/datasets/project_manager.json \
    --output ./optimized_prompts \
    --version v2 \
    --max-demos 6 \
    --model gemini/gemini-3-flash-preview
```

**Options:**
- `--trainset, -t` - Path to training data JSON (required)
- `--valset, -v` - Path to validation data JSON (optional)
- `--output, -o` - Output directory (default: `./optimized_prompts`)
- `--version` - Version identifier (default: `v1`)
- `--max-demos` - Maximum bootstrapped examples (default: 4)
- `--model, -m` - LLM model (default: `gemini/gemini-2.0-flash-exp`)

### Step 4: Evaluate Prompts

Evaluate the optimized module on a test set:

```bash
uv run ein-agent-dspy evaluate \
    --agent compute_specialist \
    --testset ./training_data/datasets/compute_specialist.json

# With custom model
uv run ein-agent-dspy evaluate \
    -a investigation_agent \
    -t ./training_data_exported/test.json \
    --model gemini/gemini-3-flash-preview
```

### Step 5: Deploy Optimized Prompts

Copy the optimized prompt to the prompt store:

```bash
uv run ein-agent-dspy deploy \
    --agent compute_specialist \
    --prompt ./optimized_prompts/v1/compute_specialist.txt \
    --version v1

# With custom store path
uv run ein-agent-dspy deploy \
    -a compute_specialist \
    -p ./optimized/compute.txt \
    --version v1 \
    --store-path /app/prompts
```

### Step 6: Use Optimized Prompts at Runtime

Set environment variables to use the optimized prompts:

```bash
export EIN_PROMPT_STORE_PATH=/app/prompts
export EIN_PROMPT_VERSION=v1  # or "latest", "baseline"
```

The worker will automatically load prompts from the store with fallback to baseline.

## Training Data Format

The exported JSON files have this structure:

```json
[
  {
    "inputs": {
      "investigation_request": "Investigate pod CrashLoopBackOff",
      "domain": "compute",
      "shared_context": ""
    },
    "labels": {
      "findings": "Pod <POD_NAME> is in CrashLoopBackOff...",
      "root_cause": "OOMKilled - memory limit exceeded",
      "confidence": 0.9,
      "context_update": "pod:<POD_NAME>: OOMKilled"
    }
  }
]
```

## Environment Variables Reference

### Worker Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `EIN_COLLECT_TRAINING_DATA` | Enable interaction logging during workflow execution | `false` |
| `EIN_TRAINING_DATA_PATH` | Directory for collected interaction data | `./training_data/logs` |
| `EIN_PROMPT_STORE_PATH` | Prompt storage directory for loading optimized prompts | `/app/prompts` |
| `EIN_PROMPT_VERSION` | Prompt version to load at runtime | `latest` |

### CLI Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DSPY_TASK_MODEL` | LLM model for DSPy compile/evaluate | `gemini/gemini-3-flash-preview` |
| `EIN_PROMPT_STORE_PATH` | Prompt storage directory for deploy command | `/app/prompts` |

## Example End-to-End Workflow

```bash
# 1. Start worker with data collection enabled
# (On the worker machine/container)
export EIN_COLLECT_TRAINING_DATA=true
export EIN_TRAINING_DATA_PATH=/shared/training_data
# start the worker...

# 2. Run workflows from CLI (on your local machine)
ein-agent-cli investigate --temporal-host localhost:7233
# ... interact with the agent ...

# 2. Export collected data
cd rocks/ein-agent-worker
uv run ein-agent-dspy export -a compute_specialist

# 3. Compile optimized prompts
uv run ein-agent-dspy compile \
    -a compute_specialist \
    -t ./training_data/datasets/compute_specialist.json \
    --version v1

# 4. Evaluate
uv run ein-agent-dspy evaluate \
    -a compute_specialist \
    -t ./training_data/datasets/compute_specialist.json

# 6. Deploy
uv run ein-agent-dspy deploy \
    -a compute_specialist \
    -p ./optimized_prompts/v1/compute_specialist.txt \
    --version v1

# 7. Use optimized prompts
export EIN_PROMPT_VERSION=v1
# Restart worker to pick up changes
```

## Troubleshooting

**No interactions found:**
- Ensure `EIN_COLLECT_TRAINING_DATA=true` was set during workflow execution
- Check `EIN_TRAINING_DATA_PATH` points to the correct directory
- Ensure `ein-agent-dspy` is run from `rocks/ein-agent-worker`

**Low optimization scores:**
- Increase training data size
- Try increasing `--max-demos`
- Ensure training data has diverse examples

**Prompts not loading:**
- Verify `EIN_PROMPT_STORE_PATH` is accessible
- Check the version directory exists with `.txt` files
- The system falls back to hardcoded baseline if files are missing

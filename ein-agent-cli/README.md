# Ein Agent CLI

The `ein-agent-cli` is a command-line interface for the Ein Agent system, enabling users to start interactive human-in-the-loop investigation workflows within Temporal.

## Features

-   Start interactive investigation sessions with an AI agent.
-   Connect to existing investigation workflows.

## Installation

Assuming you have `uv` installed:

```bash
cd ein-agent-cli
uv sync
```

## Usage

To run the CLI from the `ein-agent-cli` directory:

```bash
uv run python -m ein_agent_cli [OPTIONS]
```

### Start an Interactive Investigation

```bash
# Start interactive investigation with default settings
uv run python -m ein_agent_cli investigate

# Connect to specific Temporal instance
uv run python -m ein_agent_cli investigate --temporal-host localhost:7233
```

### Connect to an Existing Session

```bash
# Reconnect to a running investigation workflow
uv run python -m ein_agent_cli connect --workflow-id hitl-investigation-20231025-120000
```

### Configuration

Configure Temporal connection:

```bash
# Set Temporal host, namespace, and queue
uv run python -m ein_agent_cli investigate \
    --temporal-host localhost:7233 \
    --temporal-namespace default \
    --temporal-queue ein-agent-queue
```

### Getting Help

```bash
# Show all available options
uv run python -m ein_agent_cli --help
```

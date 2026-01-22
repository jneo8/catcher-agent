"""Ein Agent CLI commands - entrypoint."""

import asyncio
from typing import List, Optional

import typer

from ein_agent_cli import orchestrator
from ein_agent_cli.hitl_orchestrator import run_hitl_workflow, connect_hitl_workflow
from ein_agent_cli.models import WorkflowConfig, HITLWorkflowConfig

app = typer.Typer(help="Ein Agent CLI - Incident investigation and correlation")


@app.command()
def connect(
    workflow_id: str = typer.Option(
        ...,
        "--workflow-id",
        "-w",
        help="Workflow ID to connect to",
    ),
    temporal_host: Optional[str] = typer.Option(
        None,
        "--temporal-host",
        help="Temporal server host:port",
    ),
    temporal_namespace: Optional[str] = typer.Option(
        None,
        "--temporal-namespace",
        help="Temporal namespace",
    ),
    temporal_queue: Optional[str] = typer.Option(
        None,
        "--temporal-queue",
        help="Temporal task queue",
    ),
):
    """Connect to an existing interactive investigation session.

    This command allows you to reconnect to a running investigation workflow
    if your session was interrupted or if you want to attach to a workflow
    started by another user or process.

    Examples:

      # Connect to a specific workflow
      ein-agent-cli connect --workflow-id hitl-investigation-20231025-120000

      # Connect with custom Temporal settings
      ein-agent-cli connect -w hitl-123 --temporal-host localhost:7233
    """
    config = HITLWorkflowConfig.from_cli_args(
        temporal_host=temporal_host,
        temporal_namespace=temporal_namespace,
        temporal_queue=temporal_queue,
        workflow_id=workflow_id,
        model=None,
        max_turns=50,
    )

    asyncio.run(connect_hitl_workflow(config))


@app.command()
def run_incident_workflow(
    alertmanager_url: str = typer.Option(
        "http://localhost:9093",
        "--alertmanager-url",
        "-a",
        help="Alertmanager URL",
    ),
    include: Optional[List[str]] = typer.Option(
        None,
        "--include",
        "-i",
        help="Alert names or fingerprints to include (whitelist). If not specified, all alerts are included.",
    ),
    mcp_servers: List[str] = typer.Option(
        ["kubernetes", "grafana"],
        "--mcp-server",
        "-m",
        help="MCP server names to use",
    ),
    temporal_host: str = typer.Option(
        None,
        "--temporal-host",
        help="Temporal server host:port",
    ),
    temporal_namespace: str = typer.Option(
        None,
        "--temporal-namespace",
        help="Temporal namespace",
    ),
    temporal_queue: str = typer.Option(
        None,
        "--temporal-queue",
        help="Temporal task queue",
    ),
    workflow_id: Optional[str] = typer.Option(
        None,
        "--workflow-id",
        help="Custom workflow ID",
    ),
    status: str = typer.Option(
        "firing",
        "--status",
        help="Filter alerts by status (firing/resolved/all)",
    ),
    blacklist: Optional[List[str]] = typer.Option(
        None,
        "--blacklist",
        "-b",
        help="Alert names to exclude (default: Watchdog). Use --blacklist '' to disable",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Query and filter alerts but don't trigger workflow",
    ),
    show_labels: bool = typer.Option(
        False,
        "--show-labels",
        help="Show full labels in the alert table",
    ),
    no_prompt: bool = typer.Option(
        False,
        "--no-prompt",
        "-y",
        help="Skip confirmation prompt and trigger workflow automatically",
    ),
):
    """Query Alertmanager and trigger incident correlation workflow.

    This command will:
    1. Query Alertmanager API for alerts
    2. Filter alerts by blacklist (default: Watchdog)
    3. Filter alerts by whitelist (if --include specified) - accepts alert names or fingerprints
    4. Filter alerts by status (firing/resolved/all)
    5. Trigger IncidentCorrelationWorkflow in Temporal

    Examples:

      # Run with default settings (blacklists Watchdog, includes all others)
      ein-agent-cli run-incident-workflow

      # Include only specific alerts by name
      ein-agent-cli run-incident-workflow -i KubePodNotReady -i KubePodCrashLooping

      # Include specific alerts by fingerprint
      ein-agent-cli run-incident-workflow -i a1b2c3d4e5f6 -i 1a2b3c4d5e6f

      # Mix alert names and fingerprints
      ein-agent-cli run-incident-workflow -i KubePodNotReady -i a1b2c3d4e5f6

      # Custom blacklist (exclude TargetDown and Watchdog)
      ein-agent-cli run-incident-workflow -b TargetDown -b Watchdog

      # Disable blacklist
      ein-agent-cli run-incident-workflow -b ''

      # Query remote Alertmanager
      ein-agent-cli run-incident-workflow -a http://alertmanager.example.com:9093

      # Dry run to see what would be triggered
      ein-agent-cli run-incident-workflow --dry-run

      # Skip confirmation prompt and trigger automatically
      ein-agent-cli run-incident-workflow -y
    """
    # Create workflow configuration from CLI arguments
    config = WorkflowConfig.from_cli_args(
        alertmanager_url=alertmanager_url,
        include=include,
        mcp_servers=mcp_servers,
        temporal_host=temporal_host,
        temporal_namespace=temporal_namespace,
        temporal_queue=temporal_queue,
        workflow_id=workflow_id,
        status=status,
        blacklist=blacklist,
        dry_run=dry_run,
        show_labels=show_labels,
        no_prompt=no_prompt,
    )

    # Run orchestrator with validated configuration
    asyncio.run(orchestrator.run_incident_workflow(config))


@app.command()
def investigate(
    temporal_host: Optional[str] = typer.Option(
        None,
        "--temporal-host",
        help="Temporal server host:port",
    ),
    temporal_namespace: Optional[str] = typer.Option(
        None,
        "--temporal-namespace",
        help="Temporal namespace",
    ),
    temporal_queue: Optional[str] = typer.Option(
        None,
        "--temporal-queue",
        help="Temporal task queue",
    ),
    workflow_id: Optional[str] = typer.Option(
        None,
        "--workflow-id",
        help="Custom workflow ID",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        "-m",
        help="LLM model to use (e.g., gemini/gemini-2.5-flash)",
    ),
    max_turns: int = typer.Option(
        50,
        "--max-turns",
        help="Maximum agent turns before stopping",
    ),
):
    """Start an interactive investigation session.

    This command starts a conversational investigation workflow where you can:
    - Chat with an AI investigation agent
    - Ask the agent to fetch and investigate alerts
    - Provide context and guidance as the investigation progresses
    - Get root cause analysis and remediation suggestions

    The agent has access to:
    - Alertmanager for fetching alerts
    - Domain specialists (Compute, Storage, Network) for deep technical analysis
    - MCP tools (Kubernetes, Grafana, etc.) for infrastructure queries

    Examples:

      # Start interactive investigation with default settings
      ein-agent-cli investigate

      # Use a specific model
      ein-agent-cli investigate -m gemini/gemini-2.0-flash

      # Connect to specific Temporal instance
      ein-agent-cli investigate --temporal-host localhost:7233

    Interactive Commands:
      /quit, /exit, /q  - End the conversation
      /status           - Show workflow status
      /history          - Show conversation history
    """
    config = HITLWorkflowConfig.from_cli_args(
        temporal_host=temporal_host,
        temporal_namespace=temporal_namespace,
        temporal_queue=temporal_queue,
        workflow_id=workflow_id,
        model=model,
        max_turns=max_turns,
    )

    asyncio.run(run_hitl_workflow(config))

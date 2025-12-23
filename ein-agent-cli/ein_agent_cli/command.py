"""Ein Agent CLI commands - entrypoint."""

import asyncio
from typing import List, Optional

import typer

from ein_agent_cli import orchestrators
from ein_agent_cli.models import IncidentWorkflowConfig, HumanInLoopConfig

app = typer.Typer(help="Ein Agent CLI - Incident investigation and correlation")



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
        "active",
        "--status",
        help="Filter alerts by status (firing/resolved/active/all)",
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
    2. Filter alerts by whitelist (if --include specified) - accepts alert names or fingerprints
    3. Filter alerts by status (firing/resolved/all)
    4. Trigger IncidentCorrelationWorkflow in Temporal

    Examples:

      # Run with default settings (includes all others)
      ein-agent-cli run-incident-workflow

      # Include only specific alerts by name
      ein-agent-cli run-incident-workflow -i KubePodNotReady -i KubePodCrashLooping

      # Include specific alerts by fingerprint
      ein-agent-cli run-incident-workflow -i a1b2c3d4e5f6 -i 1a2b3c4d5e6f

      # Mix alert names and fingerprints
      ein-agent-cli run-incident-workflow -i KubePodNotReady -i a1b2c3d4e5f6

      # Query remote Alertmanager
      ein-agent-cli run-incident-workflow -a http://alertmanager.example.com:9093

      # Dry run to see what would be triggered
      ein-agent-cli run-incident-workflow --dry-run

      # Skip confirmation prompt and trigger automatically
      ein-agent-cli run-incident-workflow -y
    """
    # Create workflow configuration from CLI arguments
    config = IncidentWorkflowConfig.from_cli_args(
        alertmanager_url=alertmanager_url,
        include=include,
        mcp_servers=mcp_servers,
        temporal_host=temporal_host,
        temporal_namespace=temporal_namespace,
        temporal_queue=temporal_queue,
        workflow_id=workflow_id,
        status=status,
        dry_run=dry_run,
        show_labels=show_labels,
        no_prompt=no_prompt,
    )

    # Run orchestrator with validated configuration
    asyncio.run(orchestrators.run_incident_workflow(config))


@app.command()
def human_in_loop(
    alertmanager_url: str = typer.Option(
        "http://localhost:9093",
        "--alertmanager-url",
        "-a",
        help="Alertmanager URL",
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
    poll_interval: int = typer.Option(
        2,
        "--poll-interval",
        help="Status poll interval in seconds",
    ),
    max_iterations: int = typer.Option(
        50,
        "--max-iterations",
        help="Maximum workflow iterations",
    ),
):
    """Interactive human-in-the-loop workflow execution with multi-workflow support.

    This command enables you to work with AI agents in an interactive, conversational manner.
    The agent will execute tasks using MCP servers configured on the worker and will ask
    for your input when it needs help with decisions, tool execution, or clarifications.

    You can manage multiple workflows simultaneously and switch between them on the fly.

    MCP servers are configured on the worker side via environment variables.
    See the worker documentation for MCP server configuration.

    During the session:
    - Simply type your responses to interact with the agent
    - Type '/help' to see available commands
    - Type '/switch' to switch between running workflows
    - Type '/new' to create a new workflow
    - Type '/refresh' to get the latest workflow status
    - Type '/workflows' to list all workflows

    Examples:

      # Basic usage - you'll be prompted for your task
      ein-agent-cli human-in-loop

      # Switch between workflows during a session
      ein-agent-cli human-in-loop
      # Then type: /switch (and select from running workflows)

      # Create multiple workflows
      ein-agent-cli human-in-loop
      # Type your first task, then later: /new <new task>

      # Custom Temporal configuration
      ein-agent-cli human-in-loop \\
          --temporal-host temporal.example.com:7233 \\
          --temporal-namespace production
    """
    # Create configuration from CLI arguments
    config = HumanInLoopConfig.from_cli_args(
        user_prompt="",  # Empty user prompt - will be provided interactively
        temporal_host=temporal_host,
        temporal_namespace=temporal_namespace,
        temporal_queue=temporal_queue,
        workflow_id=workflow_id,
        poll_interval=poll_interval,
        max_iterations=max_iterations,
        alertmanager_url=alertmanager_url,
    )

    # Run orchestrator
    asyncio.run(orchestrators.run_human_in_loop(config))

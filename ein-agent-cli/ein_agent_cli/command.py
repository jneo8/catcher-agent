"""Ein Agent CLI commands - entrypoint."""

import asyncio
from typing import Optional

import typer

from ein_agent_cli.hitl_orchestrator import run_hitl_workflow, connect_hitl_workflow
from ein_agent_cli.models import HITLWorkflowConfig

app = typer.Typer(help="Ein Agent CLI - Interactive investigation")


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
        max_turns=50,
    )

    asyncio.run(connect_hitl_workflow(config))


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
    - UTCP tools (Kubernetes, Grafana, Ceph) for infrastructure queries

    Examples:

      # Start interactive investigation with default settings
      ein-agent-cli investigate

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
        max_turns=max_turns,
    )

    asyncio.run(run_hitl_workflow(config))

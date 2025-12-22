"""Temporal workflow integration."""

from datetime import datetime
from typing import Dict, List, Optional

from temporalio.client import Client as TemporalClient

from ein_agent_cli import console
from ein_agent_cli.alertmanager import convert_alertmanager_alert
from ein_agent_cli.models import (
    TemporalWorkflowParams,
    TemporalConfig,
    UserAction,
    WorkflowStatus,
)


async def trigger_incident_workflow(params: TemporalWorkflowParams) -> str:
    """Trigger IncidentCorrelationWorkflow in Temporal.

    Args:
        params: Temporal workflow parameters

    Returns:
        Workflow ID

    Raises:
        Exception: If workflow trigger fails
    """
    console.print_dim(f"Connecting to Temporal: {params.config.host}, namespace={params.config.namespace}")

    client = await TemporalClient.connect(
        params.config.host,
        namespace=params.config.namespace,
    )

    # Convert alerts to workflow format
    workflow_alerts = [convert_alertmanager_alert(alert) for alert in params.alerts]

    # Generate workflow ID if not provided
    workflow_id = params.workflow_id
    if not workflow_id:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        workflow_id = f"incident-correlation-{timestamp}"

    console.print_info(f"Starting workflow: {workflow_id}")
    console.print_dim(f"Alerts: {len(workflow_alerts)}")
    console.print_dim(f"MCP servers: {params.mcp_servers}")

    # Start workflow
    handle = await client.start_workflow(
        "IncidentCorrelationWorkflow",
        workflow_alerts,
        id=workflow_id,
        task_queue=params.config.queue,
        memo={"mcp_servers": params.mcp_servers},
    )

    console.print_success(f"✓ Workflow started: {workflow_id}")
    return workflow_id


# Human-in-the-loop workflow functions
# NOTE: Using signals instead of updates as a workaround for Temporal operator version limitations.
# The Juju Temporal operator (v1.23.1) doesn't support workflow updates (requires Temporal 1.25.0+).
# See: https://github.com/canonical/temporal-k8s-operator/issues/118
# TODO: Switch to execute_update when operator supports Temporal 1.25.0+

async def trigger_human_in_loop_workflow(
    query: str,
    mcp_servers: List[str],
    config: TemporalConfig,
    workflow_id: Optional[str] = None,
    context: Optional[Dict[str, str]] = None,
) -> str:
    """Trigger HumanInLoopWorkflow in Temporal.

    Args:
        query: Task query or description
        mcp_servers: List of MCP server names
        config: Temporal configuration
        workflow_id: Custom workflow ID
        context: Additional context dictionary

    Returns:
        Workflow ID

    Raises:
        Exception: If workflow trigger fails
    """
    console.print_dim(f"Connecting to Temporal: {config.host}, namespace={config.namespace}")

    client = await TemporalClient.connect(
        config.host,
        namespace=config.namespace,
    )

    # Generate workflow ID if not provided
    if not workflow_id:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        workflow_id = f"human-in-loop-{timestamp}"

    console.print_info(f"Starting workflow: {workflow_id}")
    console.print_dim(f"Query: {query}")
    console.print_dim(f"MCP servers: {mcp_servers}")

    # Start workflow (it will be in pending state initially)
    handle = await client.start_workflow(
        "HumanInLoopWorkflow",
        id=workflow_id,
        task_queue=config.queue,
        memo={"mcp_servers": mcp_servers, "query": query},
    )

    console.print_success(f"✓ Workflow started: {workflow_id}")
    return workflow_id


async def start_workflow_execution(
    client: TemporalClient,
    workflow_id: str,
    query: str,
    mcp_servers: List[str],
    context: Dict[str, str],
) -> str:
    """Send start_execution signal to workflow.

    Args:
        client: Temporal client
        workflow_id: Workflow ID to signal
        query: Task query or description
        mcp_servers: MCP server names
        context: Additional context

    Returns:
        Acknowledgment message

    Raises:
        Exception: If signal fails
    """
    handle = client.get_workflow_handle(workflow_id)

    execution_input = {
        "query": query,
        "mcp_servers": mcp_servers,
        "context": context,
    }

    # NOTE: Using signal instead of execute_update (workaround for Temporal 1.23.1)
    await handle.signal(
        "start_execution",
        execution_input,
    )

    return "Execution signal sent"


async def provide_user_action(
    client: TemporalClient,
    workflow_id: str,
    action: UserAction,
) -> str:
    """Send provide_action signal to workflow.

    Args:
        client: Temporal client
        workflow_id: Workflow ID to signal
        action: User action

    Returns:
        Acknowledgment message

    Raises:
        Exception: If signal fails
    """
    handle = client.get_workflow_handle(workflow_id)

    # NOTE: Using signal instead of execute_update (workaround for Temporal 1.23.1)
    await handle.signal(
        "provide_action",
        action.model_dump(),
    )

    return "Action signal sent"


async def get_workflow_status(
    client: TemporalClient,
    workflow_id: str,
) -> WorkflowStatus:
    """Query workflow for current status.

    Args:
        client: Temporal client
        workflow_id: Workflow ID to query

    Returns:
        WorkflowStatus instance

    Raises:
        Exception: If query fails
    """
    handle = client.get_workflow_handle(workflow_id)

    status_dict = await handle.query("get_status")

    return WorkflowStatus(**status_dict)


async def end_workflow(
    client: TemporalClient,
    workflow_id: str,
) -> None:
    """Send end_workflow signal to workflow.

    Args:
        client: Temporal client
        workflow_id: Workflow ID to signal

    Raises:
        Exception: If signal fails
    """
    handle = client.get_workflow_handle(workflow_id)

    await handle.signal("end_workflow")

"""Temporal workflow integration."""

from datetime import datetime

from temporalio.client import Client as TemporalClient

from ein_agent_cli import console
from ein_agent_cli.alertmanager import convert_alertmanager_alert
from ein_agent_cli.models import TemporalWorkflowParams


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

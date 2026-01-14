"""Temporal workflow integration."""

from datetime import datetime

import temporalio.common
from temporalio.client import Client as TemporalClient

from ein_agent_cli import console
from ein_agent_cli.alertmanager import convert_alertmanager_alert
from ein_agent_cli.models import TemporalWorkflowParams


async def trigger_incident_workflow(params: TemporalWorkflowParams) -> str:
    """Trigger MultiAgentCorrelationWorkflow in Temporal.

    Args:
        params: Temporal workflow parameters

    Returns:
        Workflow ID

    Raises:
        Exception: If workflow trigger fails
    """
    client = await TemporalClient.connect(
        params.config.host,
        namespace=params.config.namespace
    )

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    # Convert alerts to workflow format
    workflow_alerts = [convert_alertmanager_alert(alert) for alert in params.alerts]

    # Generate workflow ID if not provided
    workflow_id = params.workflow_id
    if not workflow_id:
        # Use a meaningful ID prefix
        workflow_id = f"incident-correlation-{timestamp}"

    console.print_info(f"Starting workflow: {workflow_id}")
    console.print_dim(f"Alerts: {len(workflow_alerts)}")

    try:
        # Start workflow
        handle = await client.start_workflow(
            "MultiAgentCorrelationWorkflow",
            workflow_alerts,
            id=workflow_id,
            task_queue=params.config.queue,
            id_reuse_policy=temporalio.common.WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        )
    except Exception as e:
        console.print_error(f"Failed to start workflow: {e}")
        raise

    console.print_success(f"✓ Workflow started: {workflow_id}")
    return workflow_id

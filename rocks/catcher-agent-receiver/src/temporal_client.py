"""Temporal workflow client for triggering alert investigation workflows."""

import uuid
from typing import Any, Dict, Optional

from loguru import logger
from temporalio.client import Client as TemporalClient

from alert_registry import AlertPromptRegistry
from models import Alert


def prepare_alert_data(alert: Alert) -> Dict[str, Any]:
    """Prepare alert data dictionary for template rendering.

    Args:
        alert: Alert object from Alertmanager webhook

    Returns:
        Dictionary containing alert data for template rendering
    """
    alert_name = alert.labels.get("alertname", "unknown")
    return {
        "alertname": alert_name,
        "status": alert.status,
        "labels": alert.labels,
        "annotations": alert.annotations,
        "starts_at": alert.starts_at,
        "ends_at": alert.ends_at,
        "fingerprint": alert.fingerprint or "",
        "generator_url": alert.generator_url,
    }


async def trigger_workflow(
    temporal_client: TemporalClient,
    alert_name: str,
    rendered_prompt: str,
    mcp_servers: list[str],
    task_queue: str,
    fingerprint: Optional[str] = None,
) -> str:
    """Trigger a Temporal workflow for an alert.

    Args:
        temporal_client: Temporal client instance
        alert_name: Name of the alert
        rendered_prompt: Rendered prompt template
        mcp_servers: List of MCP server names to enable
        task_queue: Temporal task queue name
        fingerprint: Optional alert fingerprint for workflow ID

    Returns:
        Workflow ID

    Raises:
        Exception: If workflow triggering fails
    """
    workflow_id = f"{alert_name}-{fingerprint or uuid.uuid4().hex[:8]}"

    logger.info(f"Triggering workflow for {alert_name} with ID: {workflow_id}")
    logger.info(f"MCP servers: {mcp_servers}")

    await temporal_client.start_workflow(
        "HelloWorkflow",
        rendered_prompt,
        id=workflow_id,
        task_queue=task_queue,
        memo={"mcp_servers": mcp_servers},
    )

    logger.info(f"Successfully triggered workflow {workflow_id} for alert {alert_name}")
    return workflow_id


async def process_alert(
    alert: Alert,
    alert_registry: AlertPromptRegistry,
    temporal_client: Optional[TemporalClient],
    temporal_queue: str,
) -> Optional[Dict[str, Any]]:
    """Process a single alert and trigger workflow if applicable.

    Args:
        alert: Alert object from Alertmanager webhook
        alert_registry: Alert prompt registry
        temporal_client: Temporal client instance (None if unavailable)
        temporal_queue: Temporal task queue name

    Returns:
        Dict with workflow info if successful, None if skipped
    """
    alert_name = alert.labels.get("alertname", "unknown")

    logger.info(f"Processing alert: {alert_name}")
    logger.info(f"  Status: {alert.status}")
    logger.info(f"  Labels: {alert.labels}")
    logger.info(f"  Starts At: {alert.starts_at}")

    # Check if alert has registered prompt mapping
    if not alert_registry.has_alert(alert_name):
        logger.warning(f"Alert '{alert_name}' has no registered prompt mapping, skipping")
        return None

    # Check if Temporal client is available
    if not temporal_client:
        logger.error(f"Temporal client not available, cannot trigger workflow for {alert_name}")
        return None

    # Get alert configuration
    config = alert_registry.get_config(alert_name)
    if not config:
        logger.warning(f"Failed to get config for {alert_name}")
        return None

    try:
        # Prepare alert data and render prompt
        alert_data = prepare_alert_data(alert)
        rendered_prompt = config.render_prompt(alert_data)
        logger.info(f"Rendered prompt for {alert_name} (length: {len(rendered_prompt)} chars)")

        # Trigger workflow
        workflow_id = await trigger_workflow(
            temporal_client=temporal_client,
            alert_name=alert_name,
            rendered_prompt=rendered_prompt,
            mcp_servers=config.mcp_servers,
            task_queue=temporal_queue,
            fingerprint=alert.fingerprint,
        )

        return {
            "alert_name": alert_name,
            "workflow_id": workflow_id,
            "mcp_servers": config.mcp_servers,
        }

    except Exception as e:
        logger.error(f"Failed to process alert {alert_name}: {e}")
        return None

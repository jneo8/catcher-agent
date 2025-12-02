"""FastAPI application for receiving Alertmanager webhooks."""

import os
import sys
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from loguru import logger
from temporalio.client import Client as TemporalClient

from alert_registry import AlertPromptRegistry
from models import AlertmanagerWebhook
from temporal_client import process_alert


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Configure application lifespan events."""
    # Startup: Configure logging
    logger.remove()  # Remove default handler
    logger.add(
        sys.stdout,
        format="{time:YYYY-MM-DDTHH:mm:ss.SSS}Z [{extra[service]}] {level}: {message}",
        level="INFO",
    )
    logger.configure(extra={"service": "catcher-agent"})
    logger.info("Application startup")

    # Load alert prompt registry
    alert_prompts_file = os.getenv("ALERT_PROMPTS_FILE", "/etc/catcher-agent/alert-prompts.yaml")
    try:
        app.state.alert_registry = AlertPromptRegistry.from_yaml(alert_prompts_file)
        logger.info(f"Loaded {len(app.state.alert_registry.list_alerts())} alert configurations")
    except FileNotFoundError:
        logger.warning(f"Alert prompts file not found: {alert_prompts_file}")
        logger.warning("No alert-to-prompt mappings will be available")
        app.state.alert_registry = AlertPromptRegistry()
    except Exception as e:
        logger.error(f"Failed to load alert prompts: {e}")
        logger.warning("Starting with empty alert registry")
        app.state.alert_registry = AlertPromptRegistry()

    # Initialize Temporal client
    temporal_host = os.getenv("TEMPORAL_HOST", "localhost:7233")
    temporal_namespace = os.getenv("TEMPORAL_NAMESPACE", "default")
    temporal_queue = os.getenv("TEMPORAL_QUEUE", "catcher-agent-queue")

    app.state.temporal_client: Optional[TemporalClient] = None
    app.state.temporal_queue = temporal_queue

    try:
        app.state.temporal_client = await TemporalClient.connect(
            temporal_host,
            namespace=temporal_namespace,
        )
        logger.info(f"Connected to Temporal server at {temporal_host}, namespace={temporal_namespace}")
        logger.info(f"Workflows will be submitted to queue: {temporal_queue}")
    except Exception as e:
        logger.error(f"Failed to connect to Temporal server: {e}")
        logger.warning("Webhook will only log alerts without triggering workflows")

    yield

    # Shutdown
    logger.info("Application shutdown")


app = FastAPI(title="Catcher Agent Receiver", version="0.1.0", lifespan=lifespan)


@app.get("/")
async def root() -> Dict[str, str]:
    """Root endpoint."""
    return {"message": "Catcher Agent Receiver is running"}


@app.get("/health")
async def health() -> Dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


@app.post("/webhook/alertmanager")
async def alertmanager_webhook(payload: AlertmanagerWebhook, request: Request) -> Dict[str, Any]:
    """Receive and process Prometheus Alertmanager webhook notifications.

    Args:
        payload: The Alertmanager webhook payload
        request: FastAPI request object to access app state

    Returns:
        A response indicating the webhook was received and processed
    """
    try:
        logger.info(f"Received Alertmanager webhook: {payload.group_key}")
        logger.info(f"Status: {payload.status}")
        logger.info(f"Receiver: {payload.receiver}")
        logger.info(f"Number of alerts: {len(payload.alerts)}")

        alert_registry: AlertPromptRegistry = request.app.state.alert_registry
        temporal_client: Optional[TemporalClient] = request.app.state.temporal_client
        temporal_queue: str = request.app.state.temporal_queue

        # Process all alerts
        triggered_workflows = []
        for idx, alert in enumerate(payload.alerts):
            result = await process_alert(
                alert=alert,
                alert_registry=alert_registry,
                temporal_client=temporal_client,
                temporal_queue=temporal_queue,
            )
            if result:
                triggered_workflows.append(result)

        skipped_count = len(payload.alerts) - len(triggered_workflows)

        return {
            "status": "success",
            "message": "Webhook processed successfully",
            "group_key": payload.group_key,
            "alert_count": len(payload.alerts),
            "triggered_workflows": len(triggered_workflows),
            "skipped_alerts": skipped_count,
            "workflows": triggered_workflows,
        }

    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing webhook: {str(e)}")

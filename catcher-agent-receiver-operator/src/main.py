"""Main application with webhook endpoint for Alertmanager notifications."""

import sys
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from loguru import logger

from models import AlertmanagerWebhook


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
async def alertmanager_webhook(payload: AlertmanagerWebhook) -> Dict[str, Any]:
    """Receive and process Prometheus Alertmanager webhook notifications.

    Args:
        payload: The Alertmanager webhook payload

    Returns:
        A response indicating the webhook was received
    """
    try:
        logger.info(f"Received Alertmanager webhook: {payload.group_key}")
        logger.info(f"Status: {payload.status}")
        logger.info(f"Receiver: {payload.receiver}")
        logger.info(f"Number of alerts: {len(payload.alerts)}")

        for idx, alert in enumerate(payload.alerts):
            logger.info(f"Alert {idx + 1}:")
            logger.info(f"  Status: {alert.status}")
            logger.info(f"  Labels: {alert.labels}")
            logger.info(f"  Annotations: {alert.annotations}")
            logger.info(f"  Starts At: {alert.starts_at}")
            logger.info(f"  Generator URL: {alert.generator_url}")

        return {
            "status": "success",
            "message": "Webhook received successfully",
            "group_key": payload.group_key,
            "alert_count": len(payload.alerts),
        }
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing webhook: {str(e)}")

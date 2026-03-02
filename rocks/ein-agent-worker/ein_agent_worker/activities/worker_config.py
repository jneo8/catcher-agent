"""Worker configuration activities.

These activities load configuration from the worker's environment,
allowing workflows to access worker-side settings.
"""

import os
from typing import Any

from temporalio import activity

from ein_agent_worker.models.hitl import DEFAULT_MODEL
from ein_agent_worker.utcp.config import UTCPConfig


@activity.defn
async def load_utcp_config() -> list[dict[str, Any]]:
    """Load UTCP service configurations from environment.

    Returns:
        List of service config dicts with keys:
        - name: Service name
        - openapi_url: URL to OpenAPI spec
        - auth_type: Authentication type
        - enabled: Whether service is enabled
        - version: Spec version
        - dynamic: Whether to generate tools dynamically
    """
    config = UTCPConfig.from_env()
    services = []

    for svc in config.enabled_services:
        services.append({
            "name": svc.name,
            "openapi_url": svc.openapi_url,
            "auth_type": svc.auth_type,
            "enabled": svc.enabled,
            "version": svc.version,
            "dynamic": svc.dynamic,
        })

    activity.logger.info(f"Loaded {len(services)} UTCP service(s): {[s['name'] for s in services]}")
    return services


@activity.defn
async def load_worker_model() -> str:
    """Load the LLM model configuration from environment.

    Returns:
        The configured model name from EIN_AGENT_MODEL env var,
        or DEFAULT_MODEL if not set.
    """
    model = os.getenv("EIN_AGENT_MODEL", DEFAULT_MODEL)
    activity.logger.info(f"Loaded worker model configuration: {model}")
    return model

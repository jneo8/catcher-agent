"""Worker configuration activities.

These activities load configuration from the worker's environment,
allowing workflows to access worker-side settings.
"""

import os

from temporalio import activity

from ein_agent_worker.models.hitl import DEFAULT_MODEL


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

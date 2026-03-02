"""Temporal worker for Ein Agent."""

import asyncio
import logging
import os
from datetime import timedelta
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.worker import Worker

from ein_agent_worker.models.gemini_litellm_provider import GeminiCompatibleLitellmProvider
from ein_agent_worker.models.hitl import DEFAULT_MODEL
from ein_agent_worker.activities.alertmanager import fetch_alerts_activity
from ein_agent_worker.activities.worker_config import load_worker_model, load_utcp_config
from ein_agent_worker.workflows.incident_correlation_workflow import IncidentCorrelationWorkflow
from ein_agent_worker.workflows.human_in_the_loop import HumanInTheLoopWorkflow
from temporalio.contrib.openai_agents import OpenAIAgentsPlugin, ModelActivityParameters

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Start the Temporal worker."""
    # Get config from environment (injected by temporal-worker-k8s-operator)
    host = os.getenv("TEMPORAL_HOST", "localhost:7233")
    namespace = os.getenv("TEMPORAL_NAMESPACE", "default")
    queue = os.getenv("TEMPORAL_QUEUE", "ein-agent-queue")
    model = os.getenv("EIN_AGENT_MODEL", DEFAULT_MODEL)

    logger.info(f"Using LLM model: {model}")

    # Create Temporal client
    client = await Client.connect(
        host,
        namespace=namespace,
        plugins=[
            OpenAIAgentsPlugin(
                model_params=ModelActivityParameters(
                    start_to_close_timeout=timedelta(seconds=60),
                    # Disable automatic retries - let the AI agent handle failures
                    # This allows the agent to see tool errors and decide whether to
                    # fix parameters or try a different approach
                    retry_policy=RetryPolicy(
                        maximum_attempts=1,  # Only try once, no automatic retries
                    ),
                ),
                # Use Gemini-compatible provider that handles message ordering
                model_provider=GeminiCompatibleLitellmProvider(),
            )
        ],
    )

    # Create worker
    worker = Worker(
        client,
        task_queue=queue,
        workflows=[
            IncidentCorrelationWorkflow,
            HumanInTheLoopWorkflow,
        ],
        activities=[load_worker_model, load_utcp_config, fetch_alerts_activity],
    )

    logger.info("Worker started successfully on queue: %s", queue)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
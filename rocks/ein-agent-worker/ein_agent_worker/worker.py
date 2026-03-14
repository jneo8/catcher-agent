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
from ein_agent_worker.workflows.human_in_the_loop import HumanInTheLoopWorkflow
from ein_agent_worker.utcp.config import UTCPConfig
from ein_agent_worker.utcp.loader import ToolLoader
from ein_agent_worker.utcp import registry as utcp_registry
from ein_agent_worker.utcp.temporal_utcp import get_utcp_activities
from temporalio.contrib.openai_agents import OpenAIAgentsPlugin, ModelActivityParameters

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def initialize_utcp_clients() -> None:
    """Initialize UTCP clients at worker startup.

    This runs outside the Temporal workflow sandbox, so network I/O is allowed.
    Clients are stored in the registry for workflows to access.
    """
    config = UTCPConfig.from_env()

    if not config.enabled_services:
        logger.info("No UTCP services configured")
        return

    logger.info(f"Initializing {len(config.enabled_services)} UTCP service(s)")
    loader = ToolLoader()

    for svc in config.enabled_services:
        try:
            client = await loader.create_client(
                service_name=svc.name,
                openapi_url=svc.openapi_url,
                auth_type=svc.auth_type,
                token=svc.token,
                insecure=svc.insecure,
                version=svc.version,
            )
            # Register client along with its config (for approval policy)
            utcp_registry.register_client(svc.name, client, config=svc)
        except Exception as e:
            logger.error(f"Failed to initialize UTCP client for {svc.name}: {e}")


async def main():
    """Start the Temporal worker."""
    # Get config from environment (injected by temporal-worker-k8s-operator)
    host = os.getenv("TEMPORAL_HOST", "localhost:7233")
    namespace = os.getenv("TEMPORAL_NAMESPACE", "default")
    queue = os.getenv("TEMPORAL_QUEUE", "ein-agent-queue")
    model = os.getenv("EIN_AGENT_MODEL", DEFAULT_MODEL)

    logger.info(f"Using LLM model: {model}")

    # Initialize UTCP clients at startup (before workflows run)
    # This allows network I/O outside the Temporal sandbox
    await initialize_utcp_clients()

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
            HumanInTheLoopWorkflow,
        ],
        activities=[
            load_worker_model,
            load_utcp_config,
            fetch_alerts_activity,
            *get_utcp_activities(),
        ],
    )

    logger.info("Worker started successfully on queue: %s", queue)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
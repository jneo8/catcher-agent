"""Temporal worker for Ein Agent."""

import asyncio
import logging
import os
from datetime import timedelta
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.worker import Worker

from agents.extensions.models.litellm_provider import LitellmProvider
from ein_agent_worker.mcp_providers import MCPConfig, MCPProviderRegistry
from ein_agent_worker.workflows.single_alert_investigation import SingleAlertInvestigationWorkflow
from ein_agent_worker.workflows.incident_correlation import IncidentCorrelationWorkflow
from temporalio.contrib.openai_agents import OpenAIAgentsPlugin, ModelActivityParameters

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Start the Temporal worker."""
    # Get config from environment (injected by temporal-worker-k8s-operator)
    host = os.getenv("TEMPORAL_HOST", "localhost:7233")
    namespace = os.getenv("TEMPORAL_NAMESPACE", "default")
    queue = os.getenv("TEMPORAL_QUEUE", "ein-agent-queue")

    # Load MCP configuration from environment
    mcp_config = MCPConfig()

    # Get all registered MCP server providers
    mcp_providers = MCPProviderRegistry.get_all_providers(mcp_config)

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
                # The Gemini needs to define GEMINI_API_KEY environment variable
                model_provider=LitellmProvider(),
                mcp_server_providers=mcp_providers,
            )
        ],
    )

    # Create worker
    worker = Worker(
        client,
        task_queue=queue,
        workflows=[SingleAlertInvestigationWorkflow, IncidentCorrelationWorkflow],
    )

    logger.info("Worker started successfully on queue: %s", queue)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())

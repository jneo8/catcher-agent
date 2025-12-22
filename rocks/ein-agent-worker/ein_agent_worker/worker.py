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
from ein_agent_worker.workflows.incident_correlation import (
    IncidentCorrelationWorkflow,
    InitialRcaWorkflow,
    CorrectiveRcaWorkflow,
)
from ein_agent_worker.workflows.human_in_loop import HumanInLoopWorkflow
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

    # Get default retry policy from MCP configuration
    # IMPORTANT: For human-in-the-loop workflows, we want MCP errors to surface
    # quickly to the agent so it can ask the user for help, rather than retrying
    # endlessly. Set max_attempts to 1 to disable retries for MCP activities.
    # The agent itself will handle MCP failures and ask users for help.
    default_retry_policy = mcp_config.get_default_temporal_retry_policy()

    # Override max_attempts to 1 for MCP activities to fail fast
    # This allows the agent to see errors and ask for user help immediately
    mcp_retry_policy = RetryPolicy(
        maximum_attempts=1,  # Fail fast - let agent handle errors
        initial_interval=default_retry_policy.initial_interval,
        backoff_coefficient=default_retry_policy.backoff_coefficient,
        maximum_interval=default_retry_policy.maximum_interval,
    )

    logger.info(
        "Using MCP retry policy: max_attempts=%d (fail-fast for human-in-loop workflows)",
        mcp_retry_policy.maximum_attempts
    )

    # Create Temporal client
    client = await Client.connect(
        host,
        namespace=namespace,
        plugins=[
            OpenAIAgentsPlugin(
                model_params=ModelActivityParameters(
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=mcp_retry_policy,
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
        workflows=[
            SingleAlertInvestigationWorkflow,
            IncidentCorrelationWorkflow,
            InitialRcaWorkflow,
            CorrectiveRcaWorkflow,
            HumanInLoopWorkflow,
        ],
    )

    logger.info("Worker started successfully on queue: %s", queue)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())

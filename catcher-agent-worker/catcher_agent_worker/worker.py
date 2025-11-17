"""Temporal worker for Catcher Agent."""

import asyncio
import os
from datetime import timedelta
from temporalio.client import Client
from temporalio.worker import Worker

from agents.extensions.models.litellm_provider import LitellmProvider
from catcher_agent_worker.workflows.helloworld import HelloWorkflow
from temporalio.contrib.openai_agents import OpenAIAgentsPlugin, ModelActivityParameters


async def main():
    """Start the Temporal worker."""
    # Get config from environment (injected by temporal-worker-k8s-operator)
    host = os.getenv("TEMPORAL_HOST", "localhost:7233")
    namespace = os.getenv("TEMPORAL_NAMESPACE", "default")
    queue = os.getenv("TEMPORAL_QUEUE", "catcher-agent-queue")

    API_KEY = os.getenv("GEMINI_API_KEY")

    # Create Temporal client
    client = await Client.connect(
        host,
        namespace=namespace,
        plugins=[
            OpenAIAgentsPlugin(
                model_params=ModelActivityParameters(
                    start_to_close_timeout=timedelta(seconds=60),
                ),
                model_provider=LitellmProvider(),
            )
        ],
    )

    # Create worker
    worker = Worker(
        client,
        task_queue=queue,
        workflows=[HelloWorkflow],
    )

    print(f"Worker started successfully on queue: {queue}")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())

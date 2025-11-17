"""Simple Hello World workflow for testing."""

from temporalio import workflow
from agents import Agent, Runner


@workflow.defn
class HelloWorkflow:
    """A simple workflow that returns a greeting."""

    @workflow.run
    async def run(self, prompt: str) -> str:
        """
        Run the workflow.

        Args:
            name: The name to greet

        Returns:
            A greeting message
        """
        agent = Agent(
            name="Assistant",
            instructions="",
            model="gemini/gemini-2.0-flash-lite",
        )
        result = await Runner.run(agent, input=prompt)
        workflow.logger.info("HelloWorkflow completed")
        return result.final_output

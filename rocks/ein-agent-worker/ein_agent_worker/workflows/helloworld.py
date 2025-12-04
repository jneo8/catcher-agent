"""Simple Hello World workflow for testing."""

from temporalio import workflow
from temporalio.contrib import openai_agents
from agents import Agent, Runner


@workflow.defn
class HelloWorkflow:
    """A simple workflow that returns a greeting."""

    @workflow.run
    async def run(self, prompt: str) -> str:
        """
        Run the workflow.

        Args:
            prompt: The user prompt/query

        Returns:
            The agent's response
        """
        # Dynamically reference MCP servers that were registered with the worker
        # Get the list of configured servers from workflow memo
        mcp_servers = []

        # Read MCP server names from memo (passed when workflow started)
        mcp_servers = workflow.memo_value("mcp_servers", default=[])

        if mcp_servers:
            for mcp_server in mcp_servers:
                try:
                    # Reference the MCP server by name (case-sensitive)
                    server = openai_agents.workflow.stateless_mcp_server(mcp_server)
                    mcp_servers.append(server)
                    workflow.logger.info("Loaded MCP server: %s", mcp_server)
                except Exception as e:
                    workflow.logger.warning("Failed to load MCP server '%s': %s", mcp_server, e)

        # Build agent instructions
        instructions = "You are an infrastructure assistant. Use the available tools when the user's request involves infrastructure management."

        agent = Agent(
            name="Assistant",
            instructions=instructions,
            model="gemini/gemini-2.5-pro",
            mcp_servers=mcp_servers,
        )

        result = await Runner.run(agent, input=prompt)
        workflow.logger.info("HelloWorkflow completed")
        return result.final_output

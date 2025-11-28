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
        available_mcps = []

        # Read MCP server names from memo (passed when workflow started)
        server_names = workflow.memo_value("mcp_servers", default=[])

        if server_names:
            for server_name in server_names:
                try:
                    # Reference the MCP server by name (case-sensitive)
                    server = openai_agents.workflow.stateless_mcp_server(server_name)
                    mcp_servers.append(server)
                    available_mcps.append(server_name)
                    workflow.logger.info("Loaded MCP server: %s", server_name)
                except Exception as e:
                    workflow.logger.warning("Failed to load MCP server '%s': %s", server_name, e)

        # Build agent instructions based on available MCP servers
        if available_mcps:
            instructions = f"""You are an infrastructure assistant with access to {', '.join(available_mcps)} tools.
Use the available tools when the user's request involves infrastructure management."""
            workflow.logger.info("Agent initialized with %d MCP server(s): %s", len(available_mcps), ", ".join(available_mcps))
        else:
            instructions = "You are a helpful assistant."
            workflow.logger.info("Agent initialized without MCP servers")

        agent = Agent(
            name="Assistant",
            instructions=instructions,
            model="gemini/gemini-2.0-flash-lite",
            mcp_servers=mcp_servers,
        )

        result = await Runner.run(agent, input=prompt)
        workflow.logger.info("HelloWorkflow completed")
        return result.final_output

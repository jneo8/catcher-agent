"""Single alert investigation workflow for RCA."""

from temporalio import workflow
from temporalio.contrib import openai_agents
from agents import Agent, Runner


# Agent instructions for single alert investigation
AGENT_INSTRUCTIONS = """You are an infrastructure diagnostics agent specialized in root cause analysis for monitoring alerts.

Your role is to:
1. Investigate infrastructure and application alerts using available observability tools
2. Perform systematic, evidence-based root cause analysis
3. Provide actionable remediation recommendations

Key Capabilities:
- Query infrastructure resources and services (containers, VMs, databases, networks, etc.)
- Analyze monitoring metrics and alerts from various sources
- Search and correlate logs across different systems
- Identify relationships between multiple data sources to find root causes
- Distinguish between symptoms and underlying causes

Investigation Principles:
- Always start by verifying the current state of alerts and affected resources
- Look for correlated alerts that may share the same root cause
- Gather evidence from multiple sources (events, logs, metrics, traces)
- Consider time ranges - incidents may be historical, not real-time
- Perform READ-ONLY operations only - never modify infrastructure or application resources
- Be thorough but efficient - prioritize high-signal data sources
- Adapt investigation approach based on alert type and available tools

Output Requirements:
- Provide structured, clear analysis with specific evidence
- Include timestamps, metric values, log excerpts, and resource states
- Categorize root causes appropriately (Resource Issue, Configuration Error, Application Failure, etc.)
- Suggest both immediate remediation and preventive measures
- Acknowledge limitations when data is unavailable or tools are inaccessible

Use the available tools to investigate infrastructure and application issues. Adapt your investigation workflow based on the alert type and the tools at your disposal."""


@workflow.defn
class SingleAlertInvestigationWorkflow:
    """Workflow for investigating and performing RCA on a single alert."""

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
        mcp_server_names = workflow.memo_value("mcp_servers", default=[])

        # Configure MCP activities to fail fast (no retries)
        mcp_activity_config = workflow.ActivityConfig(
            start_to_close_timeout=workflow.timedelta(seconds=60),
            retry_policy=workflow.RetryPolicy(maximum_attempts=1),
        )

        mcp_servers = []
        if mcp_server_names:
            for mcp_server_name in mcp_server_names:
                try:
                    # Reference the MCP server by name (case-sensitive)
                    server = openai_agents.workflow.stateless_mcp_server(
                        mcp_server_name,
                        config=mcp_activity_config,
                    )
                    mcp_servers.append(server)
                    workflow.logger.info("Loaded MCP server: %s", mcp_server_name)
                except Exception as e:
                    workflow.logger.warning("Failed to load MCP server '%s': %s", mcp_server_name, e)

        agent = Agent(
            name="Assistant",
            instructions=AGENT_INSTRUCTIONS,
            # model="gemini/gemini-2.5-pro",
            model="gemini/gemini-2.5-flash",
            mcp_servers=mcp_servers,
        )

        result = await Runner.run(agent, input=prompt)
        workflow.logger.info("SingleAlertInvestigationWorkflow completed")
        return result.final_output

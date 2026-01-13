"""Corrective RCA workflow for Pass 2 analysis."""

from typing import Any, Dict

from temporalio import workflow
from agents import Agent, Runner

from .prompts import (
    AGENT_INSTRUCTIONS,
    CORRECTIVE_RCA_INSTRUCTIONS,
    CORRECTIVE_RCA_PROMPT_TEMPLATE,
)
from .utils import load_mcp_servers


@workflow.defn
class CorrectiveRcaWorkflow:
    """Performs the second-pass, corrective RCA with context from other agents.

    This workflow receives:
    - The original alert
    - The draft RCA from Pass 1
    - Draft RCAs from all other agents

    It re-evaluates the initial assessment in light of the new context and produces
    a final RCA with proper causal attribution.
    """

    @workflow.run
    async def run(
        self,
        alert: Dict[str, Any],
        draft_rca: str,
        all_other_draft_rcas: str
    ) -> str:
        """Run Pass 2: Corrective RCA with context and return the final result.

        Args:
            alert: Alert dictionary
            draft_rca: The draft RCA from Pass 1 for this alert
            all_other_draft_rcas: Concatenated draft RCAs from all other alerts

        Returns:
            Final RCA report as JSON string
        """
        alertname = alert.get("alertname", "unknown")
        workflow.logger.info(f"Starting Pass 2 RCA for {alertname}")

        # Build corrective RCA prompt
        prompt = CORRECTIVE_RCA_PROMPT_TEMPLATE.format(
            draft_rca=draft_rca,
            all_other_draft_rcas=all_other_draft_rcas,
            alertname=alertname,
        )

        # Load MCP servers
        mcp_servers = load_mcp_servers()

        # Create corrective RCA agent
        agent = Agent(
            name="CorrectiveRCAAnalyst",
            instructions=AGENT_INSTRUCTIONS,
            model="gemini/gemini-2.5-flash",
            mcp_servers=mcp_servers,
        )

        # Run corrective analysis
        result = await Runner.run(agent, input=prompt)

        workflow.logger.info(f"Completed Pass 2 RCA for {alertname}")
        return result.final_output

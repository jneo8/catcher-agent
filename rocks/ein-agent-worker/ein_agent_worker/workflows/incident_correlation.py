"""Incident correlation orchestrator workflow.

This workflow orchestrates two-pass parallel RCA analysis:
- Pass 1: Run all initial RCA workflows in parallel (independent analysis)
- Pass 2: Run all corrective RCA workflows in parallel (with cross-agent context)
- Final: Correlate all RCAs into incident groups
"""

import asyncio
import json
from typing import Any, Dict, List

from temporalio import workflow
from agents import Agent, Runner

from .initial_rca import InitialRcaWorkflow
from .corrective_rca import CorrectiveRcaWorkflow
from .prompts import (
    FINAL_CORRELATION_INSTRUCTIONS,
    FINAL_CORRELATION_PROMPT_TEMPLATE,
)
from .utils import load_mcp_servers


@workflow.defn
class IncidentCorrelationWorkflow:
    """Orchestrates two-pass parallel RCA agents for incident correlation.

    Architecture:
    1. Pass 1: Run InitialRcaWorkflow for each alert in parallel
    2. Pass 2: Run CorrectiveRcaWorkflow for each alert in parallel with context
    3. Final: Correlate all RCAs and group into incidents
    """

    @workflow.run
    async def run(self, alerts: List[Dict[str, Any]]) -> str:
        """Run the two-pass incident correlation workflow.

        Args:
            alerts: List of alert dictionaries

        Returns:
            Final incident correlation report as JSON string
        """
        alert_count = len(alerts)
        workflow.logger.info(f"Orchestrating {alert_count} RCA agents in two passes.")

        # --- Pass 1: Run all initial RCA workflows in parallel ---
        workflow.logger.info("Starting Pass 1: Independent RCA for all alerts...")
        pass1_workflows = []

        for i, alert in enumerate(alerts):
            workflow_id = f"{workflow.info().workflow_id}-pass1-{i}"
            pass1_workflows.append(
                workflow.execute_child_workflow(
                    InitialRcaWorkflow.run,
                    args=[alert],
                    id=workflow_id,
                    task_queue=workflow.info().task_queue,
                    memo={"mcp_servers": workflow.memo_value("mcp_servers", default=[])},
                )
            )

        # Wait for all Pass 1 workflows to complete
        draft_rcas: List[str] = await asyncio.gather(*pass1_workflows)
        workflow.logger.info(f"Pass 1 complete. Collected {len(draft_rcas)} initial RCA reports.")

        # --- Pass 2: Run all corrective RCA workflows in parallel with context ---
        workflow.logger.info("Starting Pass 2: Corrective RCA with cross-agent context...")
        pass2_workflows = []

        for i, alert in enumerate(alerts):
            # Prepare context: all other draft RCAs (excluding this agent's own draft)
            other_drafts = [rca for j, rca in enumerate(draft_rcas) if i != j]
            all_other_context = "\n---\n".join(other_drafts)

            workflow_id = f"{workflow.info().workflow_id}-pass2-{i}"
            pass2_workflows.append(
                workflow.execute_child_workflow(
                    CorrectiveRcaWorkflow.run,
                    args=[alert, draft_rcas[i], all_other_context],
                    id=workflow_id,
                    task_queue=workflow.info().task_queue,
                    memo={"mcp_servers": workflow.memo_value("mcp_servers", default=[])},
                )
            )

        # Wait for all Pass 2 workflows to complete
        final_rcas: List[str] = await asyncio.gather(*pass2_workflows)
        workflow.logger.info(f"Pass 2 complete. Collected {len(final_rcas)} final RCA reports.")

        # --- Final Correlation ---
        return await self._run_final_correlation(final_rcas, alert_count)

    async def _run_final_correlation(
        self,
        final_rcas: List[str],
        alert_count: int
    ) -> str:
        """Run the final correlation step on the corrected RCAs.

        Args:
            final_rcas: List of final RCA reports from Pass 2
            alert_count: Total number of alerts

        Returns:
            Final incident correlation report as JSON string
        """
        workflow.logger.info("--- Starting Final Correlation ---")

        # Format the final reports for the prompt
        final_rca_reports = []
        for i, rca_str in enumerate(final_rcas):
            try:
                rca_json = json.loads(rca_str)
                final_rca_reports.append(f"RCA Report {i+1}:\n{json.dumps(rca_json, indent=2)}")
            except (json.JSONDecodeError, TypeError):
                final_rca_reports.append(f"RCA Report {i+1} (Raw):\n{rca_str}")

        # Load MCP servers
        mcp_servers = load_mcp_servers()

        # Create correlation agent
        correlation_agent = Agent(
            name="FinalCorrelationAnalyst",
            instructions=FINAL_CORRELATION_INSTRUCTIONS,
            model="gemini/gemini-2.5-pro",
            mcp_servers=mcp_servers,
        )

        # Build correlation prompt
        prompt = FINAL_CORRELATION_PROMPT_TEMPLATE.format(
            final_rca_reports="\n\n".join(final_rca_reports),
            alert_count=alert_count
        )

        # Run correlation
        result = await Runner.run(correlation_agent, input=prompt)
        return result.final_output

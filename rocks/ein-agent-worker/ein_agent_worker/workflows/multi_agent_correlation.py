"""Multi-agent incident correlation workflow.

This workflow implements the dendrogram-based multi-agent architecture with:
- Phase 1: Single-round handoff investigation (MVP)
- Phase 2: Multi-round with CrossAlertContextAgent (future)

Architecture (Following Temporal + OpenAI Agents SDK Best Practices):
  Workflow (durable orchestration):
    - Agent initialization
    - Runner.run() orchestration
    - Agent handoffs
  Activities (I/O operations):
    - MCP server calls
    - External API calls

  MultiAlertLeader → SingleAlertLeader → Specialists
                                          ↓ (activities)
                                       MCP Servers

Uses OpenAI SDK handoffs for context preservation and dynamic routing.
"""

from typing import Any, Dict, List, Optional
from datetime import timedelta

from agents import Runner, RunConfig
from agents.extensions.models.litellm_provider import LitellmProvider
from temporalio import workflow

from ein_agent_worker.mcp_providers import MCPConfig, MCPServerConfig, load_mcp_config
from ein_agent_worker.models.investigation import MultiRoundConfig
from ein_agent_worker.workflows.agent_factory import initialize_agent_swarm
from ein_agent_worker.workflows.investigation_utils import (
    format_alert_list,
    log_investigation_path,
)


@workflow.defn
class MultiAgentCorrelationWorkflow:
    """Multi-alert correlation using dendrogram pattern with agent handoffs.

    Phase 1: Single-round investigation (enable_multi_round=False)
    Phase 2: Multi-round with cross-alert context (enable_multi_round=True)

    Following Temporal SDK best practices:
    - Agent orchestration happens IN WORKFLOW (durable execution)
    - I/O operations happen IN ACTIVITIES (called via MCP tools)
    """

    @workflow.run
    async def run(
        self,
        alerts: List[Dict[str, Any]],
        config: Optional[MultiRoundConfig] = None
    ) -> str:
        """Correlate multiple alerts and produce incident report.

        Args:
            alerts: List of alerts from Alertmanager
            config: Multi-round configuration (optional, defaults to single-round)

        Returns:
            Final incident report with causal attribution
        """
        config = config or MultiRoundConfig()
        alert_count = len(alerts)

        workflow.logger.info(
            f"Starting multi-agent correlation for {alert_count} alerts "
            f"(multi_round={config.enable_multi_round})"
        )

        # Get MCP config via activity (safe for workflow)
        mcp_config = await workflow.execute_activity(
            load_mcp_config,
            start_to_close_timeout=timedelta(seconds=10),
        )

        # Get model from workflow input (deterministic)
        model = config.model
        run_config = RunConfig(model_provider=LitellmProvider())

        # Initialize agents IN WORKFLOW CONTEXT (for durable execution)
        agents = initialize_agent_swarm(
            model=model,
            mcp_config=mcp_config,
            specialist_descriptions=config.specialist_descriptions
        )

        if config.enable_multi_round:
            # Phase 2: Multi-round investigation with CrossAlertContextAgent
            workflow.logger.info("Running multi-round investigation (Phase 2)")
            incident_report = await self._run_multi_round_investigation(
                agents, alerts, config, run_config
            )
        else:
            # Phase 1: Single-round investigation
            incident_report = await self._run_single_round_investigation(
                agents, alerts, run_config
            )

        workflow.logger.info("Multi-agent correlation complete")
        return incident_report

    async def _run_single_round_investigation(
        self,
        agents: Dict[str, Any],
        alerts: List[Dict[str, Any]],
        run_config: RunConfig
    ) -> str:
        """Phase 1: Single-round investigation (MVP).

        Agent orchestration runs IN WORKFLOW for durable execution.
        I/O operations (MCP calls) run as activities via MCP tools.

        Args:
            agents: Pre-initialized agent swarm
            alerts: List of alerts to investigate
            run_config: Runner configuration with model provider

        Returns:
            Final incident report
        """
        workflow.logger.info(f"Running single-round investigation for {len(alerts)} alerts")

        # Format alerts for agent (pure function, deterministic)
        alert_summary = format_alert_list(alerts)

        # Run MultiAlertLeader with handoff capability IN WORKFLOW
        # This is the key difference - agent orchestration is durable now
        result = await Runner.run(
            agents["MultiAlertLeader"],
            input=f"""Analyze these {len(alerts)} firing alerts and determine if they share a root cause:

{alert_summary}

Investigation Process:
1. Identify alerts or groups of related alerts.
2. For the first group, use `transfer_to_singlealertleader` to investigate.
3. **Wait** for the investigation results to return.
4. Repeat for subsequent alerts/groups ONE BY ONE.
5. After all investigations are finished, synthesize the findings and provide the final Incident Report.

This is a single-round investigation (no cross-alert context sharing).
""",
            max_turns=50,  # Plenty of room for handoffs
            run_config=run_config
        )

        # Log investigation path for debugging
        log_investigation_path(result, workflow.logger)

        workflow.logger.info("Single-round investigation complete")
        return result.final_output

    async def _run_multi_round_investigation(
        self,
        agents: Dict[str, Any],
        alerts: List[Dict[str, Any]],
        config: MultiRoundConfig,
        run_config: RunConfig
    ) -> str:
        """Phase 2: Multi-round investigation with CrossAlertContextAgent.

        Agent orchestration runs IN WORKFLOW for durable execution.
        This method implements iterative refinement with cross-alert context.

        Args:
            agents: Pre-initialized agent swarm
            alerts: List of alerts to investigate
            config: MultiRoundConfig with thresholds
            run_config: Runner configuration with model provider

        Returns:
            Final incident report
        """
        workflow.logger.info(
            f"Running multi-round investigation for {len(alerts)} alerts "
            f"(max_rounds={config.max_rounds}, confidence_threshold={config.confidence_threshold})"
        )

        # Format alerts for agent
        alert_summary = format_alert_list(alerts)

        # Round 1: Independent investigation (no cross-alert context)
        workflow.logger.info("=== Round 1: Independent investigation ===")

        result_round1 = await Runner.run(
            agents["MultiAlertLeader"],
            input=f"""Analyze these {len(alerts)} firing alerts (Round 1 - Independent Investigation):

{alert_summary}

For each alert or group of related alerts, handoff to SingleAlertLeader for detailed investigation.
After all investigations complete, synthesize findings into an incident report.

This is the first round. Focus on individual alert investigation without cross-alert assumptions.
""",
            max_turns=50,
            run_config=run_config
        )

        log_investigation_path(result_round1, workflow.logger)

        # TODO: Implement multi-round logic with CrossAlertContextAgent
        # For now, return Round 1 results
        # Phase 2 full implementation will include:
        # - Parse findings from round 1
        # - Check exit conditions
        # - Build cross-alert context
        # - Create CrossAlertContextAgent
        # - Run additional rounds with context agent
        # - Implement convergence detection

        workflow.logger.info("Multi-round investigation complete (Phase 1 MVP - single round only)")
        return result_round1.final_output

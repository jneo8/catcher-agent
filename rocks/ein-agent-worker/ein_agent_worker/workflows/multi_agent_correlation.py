"""Multi-agent incident correlation workflow.

This workflow implements the dendrogram-based multi-agent architecture with:
- Phase 1: Single-round handoff investigation (MVP)
- Phase 2: Multi-round with CrossAlertContextAgent (future)

Architecture (Following Temporal + OpenAI Agents SDK Best Practices):
  Workflow (durable orchestration):
    - Agent orchestration via InvestigationManager
  Activities (I/O operations):
    - MCP server calls
    - External API calls

  MultiAlertLeader → SingleAlertLeader → Specialists
                                          ↓ (activities)
                                       MCP Servers
"""

from typing import Any, Dict, List, Optional
from datetime import timedelta

from temporalio import workflow

from ein_agent_worker.mcp_providers import load_mcp_config
from ein_agent_worker.models.investigation import MultiRoundConfig
from ein_agent_worker.workflows.investigation_manager import InvestigationManager


@workflow.defn
class MultiAgentCorrelationWorkflow:
    """Multi-alert correlation using dendrogram pattern with agent handoffs.

    Phase 1: Single-round investigation (enable_multi_round=False)
    Phase 2: Multi-round with cross-alert context (enable_multi_round=True)

    Following Temporal SDK best practices:
    - Agent orchestration happens via InvestigationManager (durable execution)
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

        # Initialize InvestigationManager IN WORKFLOW CONTEXT
        manager = InvestigationManager(
            model=config.model,
            mcp_config=mcp_config,
            specialist_descriptions=config.specialist_descriptions
        )

        # Execute investigation (Phase 1 MVP for now)
        incident_report = await manager.run_investigation(alerts)

        workflow.logger.info("Multi-agent correlation complete")
        return incident_report
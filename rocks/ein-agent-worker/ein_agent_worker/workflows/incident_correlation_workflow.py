import asyncio
from datetime import timedelta
from typing import Any, Optional, Dict, List

from agents import Agent, Runner, RunConfig
from temporalio import workflow

from ein_agent_worker.models import InvestigationConfig, SharedContext
from ein_agent_worker.workflows.agents.investigation_project_manager import (
    new_investigation_project_manager_agent,
)
from ein_agent_worker.workflows.utils import (
    format_alert_list,
    format_single_alert,
    log_investigation_path,
)

with workflow.unsafe.imports_passed_through():
    from ein_agent_worker.models.gemini_litellm_provider import GeminiCompatibleLitellmProvider
    from ein_agent_worker.mcp_providers import MCPConfig, load_mcp_config
    from ein_agent_worker.activities.worker_config import load_worker_model
    from ein_agent_worker.workflows.agents.specialists import (
        DomainType,
        new_specialist_agent,
    )
    from ein_agent_worker.workflows.agents.shared_context_tools import (
        create_shared_context_tools,
    )
    from ein_agent_worker.dspy_optimization import AgentInteraction, InteractionCollector
    from ein_agent_worker.workflows.dspy_hooks import DSPyRecordingHooks


def _get_alert_identifier(alert: dict[str, Any], index: int) -> str:
    """Get a unique identifier for an alert (fingerprint or index-based)."""
    fingerprint = alert.get("fingerprint", "")
    if fingerprint:
        # Use first 8 chars of fingerprint for readability
        return fingerprint[:8]
    return str(index + 1)


def _get_alert_name(alert: dict[str, Any]) -> str:
    """Get the alert name from labels."""
    labels = alert.get("labels", {})
    return labels.get("alertname", "UnknownAlert")


@workflow.defn
class IncidentCorrelationWorkflow:
    """Correlate multiple alerts using a multi-agent swarm with shared context."""

    def __init__(self):
        self.model: str = ""
        self.mcp_config: MCPConfig | None = None
        self.run_config: Optional[RunConfig] = None
        self.shared_context: Optional[SharedContext] = None
        self.collector: InteractionCollector | None = None
        self.alerts: list[dict[str, Any]] = []

    @workflow.run
    async def run(
        self,
        alerts: list[dict[str, Any]],
        config: Optional[InvestigationConfig] = None,
    ) -> str:
        """Investigate alerts and produce incident report."""
        config = config or InvestigationConfig()
        self.alerts = alerts

        workflow.logger.info(f"Starting multi-agent investigation for {len(alerts)} alerts")

        # Load worker model configuration from environment
        self.model = await workflow.execute_activity(
            load_worker_model,
            start_to_close_timeout=timedelta(seconds=10),
        )
        workflow.logger.info(f"Using model: {self.model}")

        # Initialize
        self.run_config = RunConfig(model_provider=GeminiCompatibleLitellmProvider())
        self.collector = InteractionCollector()
        self.shared_context = SharedContext()

        self.mcp_config = await workflow.execute_activity(
            load_mcp_config,
            start_to_close_timeout=timedelta(seconds=10),
        )

        # Initialize Agents (PM gets handoffs to Specialists)
        agents = self._create_agents()
        project_manager = agents["InvestigationProjectManager"]

        # Prepare hooks and context for recording
        recording_hooks = DSPyRecordingHooks() if self.collector and self.collector.enabled else None
        run_context = {"shared_context": self.shared_context}

        alert_summary = format_alert_list(alerts)

        # Main Phase: Project Manager Orchestration
        workflow.logger.info("Starting Project Manager orchestration")
        
        result = await Runner.run(
            project_manager,
            input=f"""You have {len(alerts)} firing alerts. 

## ALERT SUMMARY
{alert_summary}

---
## YOUR TASK
1. Analyze the alerts above.
2. Call `get_shared_context` to see if any cross-cutting root causes were found on the blackboard.
3. **Investigation & Action:**
   - Use your handoff tools (e.g., `transfer_to_ComputeSpecialist`, `transfer_to_StorageSpecialist`, etc.) to delegate specific investigation tasks to domain specialists.
   - Coordinate the investigation by synthesizing findings from specialists.
   
4. Produce the Final Incident Report once you have identified the root cause and recommended actions.
""",
            max_turns=50,
            run_config=self.run_config,
            hooks=recording_hooks,
            context=run_context,
        )

        log_investigation_path(result, workflow.logger)

        # Log shared context summary
        workflow.logger.info(f"Shared Context Summary:\n{self.shared_context.format_summary()}")

        if not result.final_output:
            workflow.logger.warning("Investigation completed but returned empty output")
            return "Investigation completed but no final report was generated. Please check the logs."

        return result.final_output

    def _get_available_mcp_servers(self) -> List[str]:
        """Get list of available MCP server names."""
        return [server.name for server in self.mcp_config.enabled_servers]

    def _create_agents(self) -> Dict[str, Agent]:
        """Create the agent swarm: ProjectManager + Specialists.

        Returns:
            Dict of agents
        """
        agents = {}
        available_mcp_servers = self._get_available_mcp_servers()

        # 1. Create Domain Specialists
        specialists = {}
        for domain in DomainType:
            update_tool, get_tool, print_report_tool, group_findings_tool = create_shared_context_tools(
                self.shared_context,
                agent_name=f"{domain.value.title()}Specialist"
            )

            agent = new_specialist_agent(
                domain=domain,
                model=self.model,
                available_mcp_servers=available_mcp_servers,
                tools=[update_tool, get_tool, print_report_tool, group_findings_tool],
            )
            specialists[agent.name] = agent
            agents[agent.name] = agent

        # 2. Create InvestigationProjectManager
        _, get_tool, print_report_tool, group_findings_tool = create_shared_context_tools(
            self.shared_context,
            agent_name="InvestigationProjectManager"
        )
        project_manager = new_investigation_project_manager_agent(
            model=self.model,
            tools=[get_tool, print_report_tool, group_findings_tool],
        )
        agents["InvestigationProjectManager"] = project_manager

        # 3. Configure Handoffs
        # PM can hand off to any Specialist
        project_manager.handoffs = list(specialists.values())
        
        # Specialists hand off back to PM
        for specialist in specialists.values():
            specialist.handoffs = [project_manager]

        return agents

from datetime import timedelta
from typing import Any, Optional, Dict, List

from agents import Agent, Runner, RunConfig
from agents.extensions.models.litellm_provider import LitellmProvider
from temporalio import workflow
from ein_agent_worker.mcp_providers import MCPConfig, load_mcp_config
from ein_agent_worker.models import InvestigationConfig, SharedContext
from ein_agent_worker.workflows.agents.investigation_project_manager import (
    new_investigation_project_manager_agent,
)
from ein_agent_worker.workflows.agents.single_alert_investigator import (
    new_single_alert_investigator_agent,
)
from ein_agent_worker.workflows.agents.specialists import (
    DomainType,
    new_specialist_agent,
)
from ein_agent_worker.workflows.agents.shared_context_tools import (
    create_shared_context_tools,
)
from ein_agent_worker.workflows.utils import (
    format_alert_list,
    format_single_alert,
    log_investigation_path,
)


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
        self.mcp_config: Optional[MCPConfig] = None
        self.run_config: Optional[RunConfig] = None
        self.shared_context: Optional[SharedContext] = None
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

        # Initialize
        self.model = config.model
        self.run_config = RunConfig(model_provider=LitellmProvider())
        self.shared_context = SharedContext()

        self.mcp_config = await workflow.execute_activity(
            load_mcp_config,
            start_to_close_timeout=timedelta(seconds=10),
        )

        # Initialize Agents (PM gets handoffs to Investigators)
        agents, investigator_info = self._create_agents()
        project_manager = agents["InvestigationProjectManager"]

        # Phase 1: Parallel Initial Investigation (Code-Driven coverage)
        import asyncio
        
        # Filter for investigators
        investigators = [agent for name, agent in agents.items() if name.startswith("Investigator_")]
        
        workflow.logger.info(f"Phase 1: Running {len(investigators)} investigators in parallel...")
        initial_investigation_reports = await asyncio.gather(*[
            self._perform_initial_alert_investigation(agent)
            for agent in investigators
        ])
        
        results_text = "\n\n".join(initial_investigation_reports)
        alert_summary = format_alert_list(alerts)

        # Phase 2: Project Manager Synthesis (Hybrid: Synthesis + Optional Handoff)
        workflow.logger.info("Phase 2: Project Manager synthesis and follow-up")
        
        result = await Runner.run(
            project_manager,
            input=f"""You have {len(alerts)} firing alerts. Your team of investigators has just completed their initial pass.

## ALERT SUMMARY
{alert_summary}

---
## INITIAL INVESTIGATION REPORTS
{results_text}

---
## YOUR TASK
1. Review the initial reports above.
2. Call `get_shared_context` to see if any cross-cutting root causes were found on the blackboard.
3. **Synthesis & Action:**
   - If the current reports provide a complete picture, synthesize the Final Incident Report.
   - **Follow-up Opportunity:** If any report is incomplete, unclear, or you have specific questions about an alert, you SHOULD use your handoff tools (e.g., `transfer_to_investigator_...`) to ask that investigator for more details.
   
4. Produce the final report once you have all the information you need.
""",
            max_turns=50,
            run_config=self.run_config
        )

        log_investigation_path(result, workflow.logger)

        # Log shared context summary
        workflow.logger.info(f"Shared Context Summary:\n{self.shared_context.format_summary()}")

        if not result.final_output:
            workflow.logger.warning("Investigation completed but returned empty output")
            return "Investigation completed but no final report was generated. Please check the logs."

        return result.final_output

    async def _perform_initial_alert_investigation(self, investigator: Agent) -> str:
        """Run a single investigator for initial baseline analysis."""
        try:
            result = await Runner.run(
                investigator,
                input="Initiate initial investigation. Check shared context, consult specialists if needed, and return your findings.",
                run_config=self.run_config,
            )
            return f"--- INITIAL REPORT FROM {investigator.name} ---\n{result.final_output}"
        except Exception as e:
            workflow.logger.error(f"Initial investigation for {investigator.name} failed: {e}")
            return f"--- INITIAL REPORT FROM {investigator.name} ---\n(Investigation Failed: {e})"


    def _get_available_mcp_servers(self) -> List[str]:
        """Get list of available MCP server names."""
        return [server.name for server in self.mcp_config.enabled_servers]

    def _create_agents(self) -> tuple[Dict[str, Agent], List[Dict[str, str]]]:
        """Create the full agent swarm with one investigator per alert.

        Returns:
            Tuple of (agents dict, investigator info list)
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

        # 2. Create ONE SingleAlertInvestigator PER ALERT
        investigators = {}
        investigator_info = []

        for i, alert in enumerate(self.alerts):
            alert_id = _get_alert_identifier(alert, i)
            alert_name = _get_alert_name(alert)
            agent_name = f"Investigator_{alert_id}"

            # Create shared context tools for this investigator
            update_tool, get_tool, print_report_tool, group_findings_tool = create_shared_context_tools(
                self.shared_context,
                agent_name=agent_name
            )

            # Format the specific alert for this investigator's context
            alert_context = format_single_alert(alert, i + 1)

            investigator = new_single_alert_investigator_agent(
                model=self.model,
                tools=[update_tool, get_tool, print_report_tool, group_findings_tool],
                agent_name=agent_name,
                alert_context=alert_context,
            )
            investigators[agent_name] = investigator
            agents[agent_name] = investigator

            investigator_info.append({
                "index": i + 1,
                "alert_name": alert_name,
                "agent_name": agent_name,
                "fingerprint": alert.get("fingerprint", "N/A")[:8],
            })

        # 3. Create InvestigationProjectManager
        _, get_tool, print_report_tool, group_findings_tool = create_shared_context_tools(
            self.shared_context,
            agent_name="InvestigationProjectManager"
        )
        project_manager = new_investigation_project_manager_agent(
            model=self.model,
            tools=[get_tool, print_report_tool, group_findings_tool],
        )
        agents["InvestigationProjectManager"] = project_manager

        # 4. Configure Handoffs
        project_manager.handoffs = list(investigators.values())
        for investigator in investigators.values():
            investigator.handoffs = [project_manager] + list(specialists.values())
        for specialist in specialists.values():
            specialist.handoffs = list(investigators.values())

        return agents, investigator_info

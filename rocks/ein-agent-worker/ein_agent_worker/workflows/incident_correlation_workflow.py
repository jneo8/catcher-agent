"""Incident correlation workflow using multi-agent architecture with Router.

Architecture:
  MultiAlertLeader → SingleAlertLeader ↔ RouterAgent
                          ↓
                     Specialists
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional, Dict

from agents import Agent, Runner, RunConfig
from agents.extensions.models.litellm_provider import LitellmProvider
from temporalio import workflow

from ein_agent_worker.mcp_providers import MCPConfig, load_mcp_config
from ein_agent_worker.models.investigation import InvestigationConfig
from ein_agent_worker.workflows.agents.multi_alert_leader import (
    new_multi_alert_leader_agent,
)
from ein_agent_worker.workflows.agents.single_alert_leader import (
    new_single_alert_leader_agent,
)
from ein_agent_worker.workflows.agents.specialists import new_specialist_agent, get_domain_description
from ein_agent_worker.workflows.agents.router_agent import new_router_agent
from ein_agent_worker.workflows.utils import (
    format_alert_list,
    log_investigation_path,
)


@workflow.defn
class IncidentCorrelationWorkflow:
    """Correlate multiple alerts using a Router-assisted agent swarm."""

    def __init__(self):
        self.model: str = ""
        self.mcp_config: Optional[MCPConfig] = None
        self.run_config: Optional[RunConfig] = None

    @workflow.run
    async def run(
        self,
        alerts: list[dict[str, Any]],
        config: Optional[InvestigationConfig] = None,
    ) -> str:
        """Investigate alerts and produce incident report."""
        config = config or InvestigationConfig()

        workflow.logger.info(f"Starting Router-assisted investigation for {len(alerts)} alerts")

        # Initialize
        self.model = config.model
        self.run_config = RunConfig(model_provider=LitellmProvider())

        self.mcp_config = await workflow.execute_activity(
            load_mcp_config,
            start_to_close_timeout=timedelta(seconds=10),
        )

        # Initialize Agents with Router
        agents = self._create_agents_with_router()
        
        alert_summary = format_alert_list(alerts)
        
        # Run Investigation (MultiAlertLeader drives the process)
        # Note: We rely on agent handoffs now, guided by the Router.
        result = await Runner.run(
            agents["MultiAlertLeader"],
            input=f"""Analyze these {len(alerts)} firing alerts and determine if they share a root cause:

{alert_summary}

Investigation Process:
1. Identify alerts or groups of related alerts.
2. For each alert/group, handoff to `SingleAlertLeader`.
3. `SingleAlertLeader` will consult the `RouterAgent` to decide which Specialists to call.
4. After all investigations are finished, synthesize the findings and provide the final Incident Report.

This is a single-round investigation with Router assistance.
""",
            max_turns=50,
            run_config=self.run_config
        )
        
        log_investigation_path(result, workflow.logger)
        return result.final_output

    def _create_agents_with_router(self) -> Dict[str, Agent]:
        """Create the full agent swarm including RouterAgent."""
        agents = {}
        
        # 1. Specialists
        specialists = {}
        for server_config in self.mcp_config.enabled_servers:
            name = f"{server_config.name.title()}Specialist"
            desc = get_domain_description(server_config.name)
            
            agent = new_specialist_agent(
                name=name,
                domain_description=desc,
                model=self.model,
                mcp_server_name=server_config.name,
            )
            specialists[name] = agent
            agents[name] = agent

        # 2. Router Agent
        available_specialist_names = list(specialists.keys())
        router = new_router_agent(self.model, available_specialist_names)
        agents["RouterAgent"] = router

        # 3. Leaders
        single_leader = new_single_alert_leader_agent(self.model)
        multi_leader = new_multi_alert_leader_agent(self.model)
        agents["SingleAlertLeader"] = single_leader
        agents["MultiAlertLeader"] = multi_leader

        # 4. Configure Handoffs
        
        # Multi -> Single
        multi_leader.handoffs = [single_leader]
        
        # Single -> Multi, Router, Specialists
        single_leader.handoffs = [multi_leader, router] + list(specialists.values())
        
        # Router -> Single (Returns advice)
        router.handoffs = [single_leader]
        
        # Specialists -> Single (Return findings)
        for sp in specialists.values():
            sp.handoffs = [single_leader]

        return agents
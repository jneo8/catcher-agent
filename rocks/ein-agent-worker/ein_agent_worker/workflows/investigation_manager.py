from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from agents import Agent, Runner, RunConfig
from agents.extensions.models.litellm_provider import LitellmProvider
from temporalio import workflow

from ein_agent_worker.mcp_providers import MCPConfig
from ein_agent_worker.workflows.agents.multi_alert_leader import new_multi_alert_leader_agent
from ein_agent_worker.workflows.agents.single_alert_leader import new_single_alert_leader_agent
from ein_agent_worker.workflows.agents.specialists import new_specialist_agent
from ein_agent_worker.workflows.investigation_utils import (
    format_alert_list,
    log_investigation_path,
)

class InvestigationManager:
    """Manages the lifecycle and orchestration of investigation agents."""

    def __init__(
        self,
        model: str,
        mcp_config: MCPConfig,
        specialist_descriptions: Optional[Dict[str, str]] = None
    ):
        self.model = model
        self.run_config = RunConfig(model_provider=LitellmProvider())
        self.specialist_descriptions = specialist_descriptions or {}
        
        # Initialize agents
        self.agents = self._initialize_agents(mcp_config)

    def _initialize_agents(self, mcp_config: MCPConfig) -> Dict[str, Agent]:
        """Initialize the agent swarm with handoff relationships."""
        enabled_servers = mcp_config.enabled_servers
        
        # 1. Create Specialist Agents
        specialists = {}
        for server_config in enabled_servers:
            specialist_name = f"{server_config.name.title()}Specialist"
            domain_desc = self.specialist_descriptions.get(
                server_config.name, 
                f"{server_config.name} infrastructure"
            )
            
            agent = new_specialist_agent(
                name=specialist_name,
                domain_description=domain_desc,
                model=self.model,
                mcp_server_name=server_config.name
            )
            specialists[specialist_name] = agent

        # 2. Create Leaders
        single_leader = new_single_alert_leader_agent(self.model)
        multi_leader = new_multi_alert_leader_agent(self.model)

        # 3. Setup Handoffs (Dendrogram pattern)
        # Specialists -> SingleAlertLeader
        for agent in specialists.values():
            agent.handoffs = [single_leader]

        # SingleAlertLeader -> MultiAlertLeader + Specialists
        single_leader.handoffs = [multi_leader] + list(specialists.values())

        # MultiAlertLeader -> SingleAlertLeader
        multi_leader.handoffs = [single_leader]

        return {
            "MultiAlertLeader": multi_leader,
            "SingleAlertLeader": single_leader,
            **specialists
        }

    async def run_investigation(self, alerts: List[Dict[str, Any]]) -> str:
        """Execute the single-round investigation flow."""
        workflow.logger.info(f"Running investigation for {len(alerts)} alerts")
        
        alert_summary = format_alert_list(alerts)
        
        result = await Runner.run(
            self.agents["MultiAlertLeader"],
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
            max_turns=50,
            run_config=self.run_config
        )
        
        log_investigation_path(result, workflow.logger)
        return result.final_output

"""Agent factory for multi-agent investigation workflows.

This module provides functions to create agents in workflow context.
Agent orchestration (initialize_agent_swarm, Runner.run) must happen in workflows
for durable execution, not in activities.

Following Temporal + OpenAI Agents SDK best practices:
- Agent creation and orchestration: IN WORKFLOW (durable)
- I/O operations (MCP calls, external APIs): IN ACTIVITIES
"""

import logging
from typing import Dict

from agents import Agent
from temporalio import workflow
from temporalio.contrib import openai_agents

from ein_agent_worker.mcp_providers import MCPConfig
from ein_agent_worker.workflows.agent_instructions import (
    MULTI_ALERT_LEADER_INSTRUCTIONS,
    SINGLE_ALERT_LEADER_INSTRUCTIONS,
    create_specialist_instructions,
)

logger = logging.getLogger(__name__)


def initialize_agent_swarm(
    model: str,
    mcp_config: MCPConfig,
    specialist_descriptions: Dict[str, str] = None
) -> Dict[str, Agent]:
    """Initialize all agents with proper handoff relationships.

    This function must be called from WORKFLOW CONTEXT, not activity context.
    Agent orchestration belongs in workflows for durable execution.

    Creates:
    - MultiAlertLeader
    - SingleAlertLeader
    - Dynamic specialist agents (one per MCP server)

    Args:
        model: Model name to use for all agents (e.g., "gemini/gemini-2.5-flash")
        mcp_config: MCP configuration (must be passed from workflow argument)
        specialist_descriptions: Optional dict mapping server name to domain description
                                 (deterministic, passed as workflow input)

    Returns:
        Dictionary mapping agent names to Agent instances
    """
    specialist_descriptions = specialist_descriptions or {}
    workflow.logger.info("Initializing agent swarm in workflow context")

    # Use passed MCP configuration
    enabled_servers = mcp_config.enabled_servers

    if not enabled_servers:
        workflow.logger.warning("No MCP servers configured, creating agents without specialists")
        specialists = {}
    else:
        workflow.logger.info(f"Creating specialists for {len(enabled_servers)} MCP servers")

        # Create specialists dynamically from MCP configuration
        specialists = {}

        for server_config in enabled_servers:
            specialist_name = f"{server_config.name.title()}Specialist"

            # Get description from workflow input or use generic description
            # This is deterministic (passed as workflow input, not read from environment)
            domain_description = specialist_descriptions.get(
                server_config.name,
                f"{server_config.name} infrastructure"
            )

            # Create MCP server provider for this specialist
            # Use Temporal's stateless MCP server pattern (workflow context)
            mcp_server_name = server_config.name

            try:
                # stateless_mcp_server() must be called from workflow context
                specialists[specialist_name] = Agent(
                    name=specialist_name,
                    instructions=create_specialist_instructions(domain_description),
                    model=model,
                    mcp_servers=[openai_agents.workflow.stateless_mcp_server(mcp_server_name)],
                    handoffs=[] # Will populate later
                )
                workflow.logger.info(f"Created specialist: {specialist_name} for {domain_description}")
            except Exception as e:
                workflow.logger.error(f"Failed to create specialist {specialist_name}: {e}")
                # Continue with other specialists

    # Create SingleAlertLeader with handoffs to all specialists
    single_alert_leader = Agent(
        name="SingleAlertLeader",
        instructions=SINGLE_ALERT_LEADER_INSTRUCTIONS,
        model=model,
        handoffs=[], # Will populate later
        mcp_servers=[]  # Uses specialists' tools via handoffs
    )

    # Create MultiAlertLeader
    multi_alert_leader = Agent(
        name="MultiAlertLeader",
        instructions=MULTI_ALERT_LEADER_INSTRUCTIONS,
        model=model,
        handoffs=[], # Will populate later
        mcp_servers=[]  # Uses SingleAlertLeader and specialists via handoffs
    )

    # Update handoffs with actual Agent objects (resolving string references)
    
    # Specialists -> SingleAlertLeader
    for specialist in specialists.values():
        specialist.handoffs = [single_alert_leader]

    # SingleAlertLeader -> MultiAlertLeader + Specialists
    single_alert_leader.handoffs = [multi_alert_leader] + list(specialists.values())

    # MultiAlertLeader -> SingleAlertLeader
    multi_alert_leader.handoffs = [single_alert_leader]

    workflow.logger.info(
        f"Agent swarm initialized: MultiAlertLeader, SingleAlertLeader, "
        f"{len(specialists)} specialists"
    )

    return {
        "MultiAlertLeader": multi_alert_leader,
        "SingleAlertLeader": single_alert_leader,
        **specialists
    }

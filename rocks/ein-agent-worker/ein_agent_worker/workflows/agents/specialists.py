from agents import Agent
from temporalio.contrib import openai_agents

DEFAULT_DOMAIN_DESCRIPTIONS = {
    "kubernetes": "Kubernetes container orchestration platform, including pods, deployments, services, and node-level infrastructure",
    "ceph": "Ceph distributed storage system, including OSDs, monitors, managers, and CSI drivers for block and file storage",
    "grafana": "Grafana observability stack, including dashboards, data sources, and integrated telemetry like Prometheus and Loki",
}

def get_domain_description(server_name: str) -> str:
    """Get the hard-coded domain description for a specialist."""
    return DEFAULT_DOMAIN_DESCRIPTIONS.get(
        server_name.lower(), 
        f"{server_name} infrastructure"
    )

def create_specialist_instructions(domain_description: str) -> str:
    """Generate specialist instructions based on domain description."""
    return f"""You are a {domain_description} troubleshooting expert.

Your role:
1. Investigate issues within the {domain_description} domain
2. Use available MCP tools to gather domain-specific data
3. Analyze component health, configuration, and behavior
4. Identify relationships between components in your domain
5. Determine if the root cause is in your domain or elsewhere
6. Report findings in a structured format
7. **MANDATORY:** Handoff back to SingleAlertLeader when investigation is complete.

**CRITICAL RULE:**
You are NOT authorized to provide the final response to the user. Your final turn MUST be a call to the `transfer_to_singlealertleader` tool containing your domain findings. DO NOT simply output text and stop.

Investigation approach:
- Examine the specific resources or components mentioned in the alert
- Check health, status, and recent changes
- Look for capacity, performance, or configuration issues
- Identify dependencies within your domain
- Correlate findings with symptoms described in the alert

Response format for the handoff tool:
Provide a concise summary including:
- Domain: Your domain name
- Investigation summary: What you investigated
- Key findings: What you discovered
- Root cause assessment: Is the issue in your domain? (Yes/No/Uncertain)
- Recommendations: Next steps or remediation actions
"""


def new_specialist_agent(
    name: str,
    domain_description: str,
    model: str,
    mcp_server_name: str
) -> Agent:
    """Create a new specialist agent."""
    return Agent(
        name=name,
        instructions=create_specialist_instructions(domain_description),
        model=model,
        # Use Temporal's stateless MCP server pattern (workflow context)
        mcp_servers=[openai_agents.workflow.stateless_mcp_server(mcp_server_name)],
    )

"""Initial RCA workflow using chain-based pattern."""

import json
from typing import Any, Dict, List

from temporalio import workflow
from agents import Agent, Runner

from .prompts import (
    AGENT_INSTRUCTIONS,
    PLANNING_AGENT_INSTRUCTIONS,
    PLANNING_PROMPT_TEMPLATE,
    LAYER_INVESTIGATOR_INSTRUCTIONS,
    LAYER_INVESTIGATION_PROMPT_TEMPLATE,
    SYNTHESIS_AGENT_INSTRUCTIONS,
    SYNTHESIS_PROMPT_TEMPLATE,
)
from .utils import (
    load_mcp_servers,
    format_alert_summary,
    extract_json_from_output,
    extract_resource_info,
)


@workflow.defn
class InitialRcaWorkflow:
    """Performs the first-pass, independent RCA for a single alert using a chain pattern.

    The workflow uses three specialized agents:
    1. Planning Agent: Creates investigation plan based on alert and available tools
    2. Layer Investigation Agents: Execute investigation for each layer
    3. Synthesis Agent: Combines findings into final RCA report
    """

    @workflow.run
    async def run(self, alert: Dict[str, Any]) -> str:
        """Run Pass 1: Chain-based RCA and return the result.

        Args:
            alert: Alert dictionary with alertname, labels, annotations, etc.

        Returns:
            Final RCA report as JSON string
        """
        alertname = alert.get('alertname', 'unknown')
        workflow.logger.info(f"Starting chain-based Pass 1 RCA for {alertname}")

        mcp_servers = load_mcp_servers()

        # Step 1: Planning - Create investigation plan
        workflow.logger.info("Step 1: Creating investigation plan")
        plan = await self._create_investigation_plan(alert, mcp_servers)
        workflow.logger.info(f"Investigation plan created with {len(plan.get('layers', []))} layers")

        # Step 2: Execute each layer in the plan
        workflow.logger.info("Step 2: Executing layer-by-layer investigation")
        findings = await self._execute_investigation_layers(alert, plan, mcp_servers)

        # Step 3: Synthesize final RCA report
        workflow.logger.info("Step 3: Synthesizing final RCA report")
        final_rca = await self._synthesize_rca(alert, plan, findings, mcp_servers)

        workflow.logger.info(f"Completed chain-based Pass 1 RCA for {alertname}")
        return final_rca

    async def _create_investigation_plan(
        self,
        alert: Dict[str, Any],
        mcp_servers: List[Any]
    ) -> Dict[str, Any]:
        """Create an investigation plan based on alert and available tools.

        Args:
            alert: Alert dictionary
            mcp_servers: List of MCP server instances

        Returns:
            Investigation plan dictionary with layers
        """
        # Extract resource info from alert
        resource_info = extract_resource_info(alert)
        alertname = alert.get("alertname", "unknown")

        # Build planning prompt
        plan_prompt = PLANNING_PROMPT_TEMPLATE.format(
            alertname=alertname,
            resource_name=resource_info["resource_name"],
            scope=resource_info["scope"],
            alert_summary=format_alert_summary(alert),
        )

        # Create planning agent
        agent = Agent(
            name="PlanningAgent",
            instructions=PLANNING_AGENT_INSTRUCTIONS,
            model="gemini/gemini-2.5-flash",
            mcp_servers=mcp_servers,
        )

        # Run planning agent
        result = await Runner.run(agent, input=plan_prompt)

        # Extract and parse JSON from output
        output = extract_json_from_output(result.final_output)

        try:
            plan = json.loads(output)
            num_layers = len(plan.get('layers', []))
            workflow.logger.info(
                f"Successfully parsed plan with {num_layers} layers: "
                f"{[l.get('name') for l in plan.get('layers', [])]}"
            )

            if num_layers == 0:
                raise ValueError("Plan has no layers")

            return plan

        except (json.JSONDecodeError, ValueError) as e:
            # Emergency fallback - minimal plan that tells the agent to figure it out
            workflow.logger.error(f"Failed to parse plan: {e}. Output was: {output[:500]}")
            workflow.logger.warning("Using emergency fallback - asking agent to investigate dynamically")

            labels = alert.get("labels", {})
            resource_name = resource_info["resource_name"]

            plan = {
                "failing_resource": resource_name,
                "layers": [
                    {
                        "name": "Dynamic Investigation",
                        "description": (
                            f"Investigate {alertname} for resource {resource_name}. "
                            "Review available tools, then investigate the alert systematically."
                        ),
                        "tools_to_use": [],  # Empty - agent must discover tools
                        "investigation_goal": f"Determine root cause of {alertname}"
                    }
                ]
            }

            return plan

    async def _execute_investigation_layers(
        self,
        alert: Dict[str, Any],
        plan: Dict[str, Any],
        mcp_servers: List[Any]
    ) -> List[Dict[str, Any]]:
        """Execute investigation for each layer in the plan.

        Args:
            alert: Alert dictionary
            plan: Investigation plan with layers
            mcp_servers: List of MCP server instances

        Returns:
            List of findings dictionaries, one per layer
        """
        findings = []

        for layer in plan.get("layers", []):
            layer_name = layer.get('name', 'unknown layer')
            workflow.logger.info(f"Investigating {layer_name}")

            # Build list of suggested tools
            suggested_tools = layer.get('tools_to_use', [])
            if suggested_tools:
                tools_text = f"**Suggested tools to use:** {', '.join(suggested_tools)}"
            else:
                tools_text = "**Use any available tools that are relevant.**"

            # Build layer investigation prompt
            layer_prompt = LAYER_INVESTIGATION_PROMPT_TEMPLATE.format(
                layer_name=layer_name,
                alert_summary=format_alert_summary(alert),
                failing_resource=plan.get('failing_resource'),
                investigation_goal=layer.get('investigation_goal', 'Investigate this layer'),
                description=layer.get('description', ''),
                tools_text=tools_text,
            )

            # Create layer investigation agent
            agent = Agent(
                name=f"LayerInvestigator-{layer_name}",
                instructions=LAYER_INVESTIGATOR_INSTRUCTIONS,
                model="gemini/gemini-2.5-flash",
                mcp_servers=mcp_servers,
            )

            # Run investigation
            result = await Runner.run(agent, input=layer_prompt)

            # Extract and parse JSON from output
            output = extract_json_from_output(result.final_output)

            try:
                finding = json.loads(output)
                workflow.logger.info(
                    f"{layer_name} investigation: status={finding.get('status')}, "
                    f"tools_used={finding.get('tools_used')}"
                )
            except json.JSONDecodeError as e:
                workflow.logger.warning(f"Failed to parse layer finding: {e}")
                finding = {
                    "layer_name": layer_name,
                    "status": "unknown",
                    "findings": result.final_output[:500],  # Truncate for logging
                    "tools_used": [],
                    "is_root_cause": False,
                    "needs_deeper_investigation": True
                }

            findings.append(finding)

            # If root cause found, stop investigating further layers
            if finding.get("is_root_cause", False):
                workflow.logger.info(f"Root cause found at {layer_name}, stopping investigation")
                break

            # If this layer is healthy, no need to go deeper
            if finding.get("status") == "healthy" and not finding.get("needs_deeper_investigation", False):
                workflow.logger.info(f"{layer_name} is healthy, stopping investigation")
                break

        return findings

    async def _synthesize_rca(
        self,
        alert: Dict[str, Any],
        plan: Dict[str, Any],
        findings: List[Dict[str, Any]],
        mcp_servers: List[Any]
    ) -> str:
        """Synthesize findings from all layers into final RCA report.

        Args:
            alert: Alert dictionary
            plan: Investigation plan
            findings: List of findings from each layer
            mcp_servers: List of MCP server instances

        Returns:
            Final RCA report as JSON string
        """
        # Build synthesis prompt
        synthesis_prompt = SYNTHESIS_PROMPT_TEMPLATE.format(
            alert_summary=format_alert_summary(alert),
            plan=json.dumps(plan, indent=2),
            findings=json.dumps(findings, indent=2),
            alertname=alert.get('alertname', 'unknown'),
        )

        # Create synthesis agent
        agent = Agent(
            name="SynthesisAgent",
            instructions=SYNTHESIS_AGENT_INSTRUCTIONS,
            model="gemini/gemini-2.5-flash",
            mcp_servers=mcp_servers,
        )

        # Run synthesis
        result = await Runner.run(agent, input=synthesis_prompt)
        return result.final_output

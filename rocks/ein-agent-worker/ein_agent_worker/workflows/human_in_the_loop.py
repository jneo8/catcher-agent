"""Human-in-the-Loop Investigation Workflow.

A simple conversational workflow where:
- User converses with an investigation agent
- Agent has tools to fetch alerts from Alertmanager
- Agent can investigate alerts using MCP tools (Kubernetes, Grafana, etc.)
- Agent asks for clarification naturally when needed via ask_user tool
- Agent can hand off to domain specialists for deep technical analysis
"""

from datetime import timedelta
from typing import Any

from pydantic import BaseModel, Field
from agents import Agent, Runner, RunConfig, function_tool
from agents.extensions.models.litellm_provider import LitellmProvider
from temporalio import workflow

from ein_agent_worker.mcp_providers import MCPConfig, load_mcp_config
from ein_agent_worker.models import (
    SharedContext,
    WorkflowStatus,
    ChatMessage,
    WorkflowState,
    HITLConfig,
    AgentSelectionRequest,
)
from ein_agent_worker.workflows.agents.specialists import (
    DomainType,
    new_specialist_agent,
)
from ein_agent_worker.workflows.agents.single_alert_investigator import (
    new_single_alert_investigator_agent,
)
from ein_agent_worker.workflows.agents.shared_context_tools import (
    create_shared_context_tools,
)
from agents.handoffs import handoff


class InvestigateAlertInput(BaseModel):
    """Input for starting investigation on a specific alert."""
    fingerprint: str = Field(description="The fingerprint of the alert to investigate")
    reason: str = Field(description="The reason for investigating this alert")


# =============================================================================
# Investigation Agent Prompt
# =============================================================================
INVESTIGATION_AGENT_PROMPT = """You are the Investigation Assistant (The Orchestrator).

## Your Capabilities
- **Fetch Alerts**: Use `fetch_alerts` to get current firing alerts.
- **Delegate Alert Investigation**: When a specific alert needs deep investigation, use the `investigate_alert` tool to hand off to a specialized investigator for that alert.
- **Consult Domain Specialists**: Use `select_specialist` to consult a domain specialist:
  - **ComputeSpecialist**: For Kubernetes, pods, nodes, and containers.
  - **StorageSpecialist**: For Ceph, OSDs, PVCs, and storage volumes.
  - **NetworkSpecialist**: For networking, DNS, load balancers, and ingress.
- **Ask User**: Ask for clarification using `ask_user`.
- **Print Findings Report**: Use `print_findings_report` to generate a formatted summary of all investigation findings. Use this when you want to present a comprehensive report to the user.

## Your Workflow
1. **Analyze User Request**: Determine if the user wants to investigate a specific alert or has a general infrastructure question.
2. **Consult Specialists**: When you need domain expertise, call `select_specialist`:
   - Provide your suggested specialist and the reason.
   - The user will see all available options and can choose a different specialist.
   - The tool will directly consult the specialist and return their findings.
   - Example: `select_specialist(suggested="StorageSpecialist", reason="Alert involves Ceph storage")`
3. **Synthesize**: Use the specialist's findings to provide a clear summary to the user.
4. **Report**: When the investigation is complete, use `print_findings_report` to generate a well-structured summary of all findings.

## CRITICAL RULES
- Use `select_specialist` to consult domain specialists. It returns the specialist's findings directly.
- You do NOT have direct access to MCP tools. You must delegate to specialists who do.
- Use `print_findings_report` to generate final reports for the user when wrapping up an investigation.
"""


@workflow.defn
class HumanInTheLoopWorkflow:
    """Simple conversational investigation workflow."""

    # List of available specialist agents for user selection
    AVAILABLE_SPECIALISTS = ["ComputeSpecialist", "StorageSpecialist", "NetworkSpecialist"]

    def __init__(self):
        self._state = WorkflowState()
        self._shared_context = SharedContext()
        self._config = HITLConfig()
        self._mcp_config: MCPConfig | None = None
        self._run_config: RunConfig | None = None
        self._pending_user_response: str | None = None
        self._has_pending_input = False
        self._should_end = False
        self._pending_confirmation = False
        self._confirmation_response: bool | None = None
        # Agent selection state
        self._pending_agent_selection = False
        self._selected_agent: str | None = None

    # =========================================================================
    # Signals (user sends messages)
    # =========================================================================

    @workflow.signal
    async def send_message(self, message: str) -> None:
        """User sends a message to the agent."""
        workflow.logger.info(f"Received user message: {message[:100]}...")
        self._state.messages.append(
            ChatMessage(role="user", content=message, timestamp=workflow.now())
        )
        self._pending_user_response = message
        self._has_pending_input = True

    @workflow.signal
    async def end_workflow(self) -> None:
        """User wants to end the conversation."""
        workflow.logger.info("End workflow signal received")
        self._should_end = True
        self._has_pending_input = True  # Unblock if waiting

    @workflow.signal
    async def provide_confirmation(self, confirmed: bool) -> None:
        """User provides confirmation for a pending action."""
        workflow.logger.info(f"Received confirmation: {confirmed}")
        self._confirmation_response = confirmed
        self._pending_confirmation = False

    @workflow.signal
    async def provide_agent_selection(self, selected_agent: str) -> None:
        """User selects an agent from the available options.

        Args:
            selected_agent: Name of the selected agent, or empty string to cancel.
        """
        workflow.logger.info(f"Received agent selection: {selected_agent}")
        self._selected_agent = selected_agent if selected_agent else None
        self._pending_agent_selection = False

    # =========================================================================
    # Queries (read state)
    # =========================================================================

    @workflow.query
    def get_state(self) -> dict:
        """Get current workflow state."""
        return self._state.model_dump(mode="json")

    @workflow.query
    def get_messages(self) -> list[dict]:
        """Get conversation history."""
        return [m.model_dump(mode="json") for m in self._state.messages]

    @workflow.query
    def get_status(self) -> str:
        """Get current workflow status."""
        return self._state.status.value

    # =========================================================================
    # Main workflow
    # =========================================================================

    @workflow.run
    async def run(
        self,
        initial_message: str | None = None,
        config: HITLConfig | None = None,
    ) -> str:
        """Main conversation loop.

        Args:
            initial_message: Optional first message to start the conversation
            config: Optional configuration for the workflow

        Returns:
            Final report or termination message
        """
        if config:
            self._config = config

        self._state.status = WorkflowStatus.RUNNING
        workflow.logger.info("Human-in-the-loop workflow started")

        # Load MCP configuration
        self._mcp_config = await workflow.execute_activity(
            load_mcp_config,
            start_to_close_timeout=timedelta(seconds=10),
        )

        # Setup run config
        self._run_config = RunConfig(model_provider=LitellmProvider())

        # Create the investigation agent
        agent = self._create_investigation_agent()

        # Handle initial message or produce greeting
        if initial_message:
            self._state.messages.append(
                ChatMessage(
                    role="user", content=initial_message, timestamp=workflow.now()
                )
            )
            self._has_pending_input = True
        else:
            # No initial message - produce a greeting
            greeting = (
                "Hello! I'm your infrastructure investigation assistant. "
                "I can help you investigate alerts and infrastructure issues.\n\n"
                "You can:\n"
                "- Ask me to fetch and investigate current alerts\n"
                "- Describe an issue you're experiencing\n"
                "- Ask questions about your infrastructure\n\n"
                "How can I help you today?"
            )
            self._state.messages.append(
                ChatMessage(
                    role="assistant", content=greeting, timestamp=workflow.now()
                )
            )
            workflow.logger.info("Sent initial greeting")

        # Conversation loop
        turn_count = 0
        while not self._should_end and turn_count < self._config.max_turns:
            # Wait for user input if no pending messages
            if not self._has_pending_input:
                workflow.logger.info("Waiting for user input...")
                await workflow.wait_condition(lambda: self._has_pending_input)

            if self._should_end:
                break

            self._has_pending_input = False
            turn_count += 1

            # Build conversation history for the agent
            conversation = self._build_conversation_input()

            workflow.logger.info(f"Running agent turn {turn_count}")

            try:
                # Run the agent
                result = await Runner.run(
                    agent,
                    input=conversation,
                    max_turns=30,  # Increased max turns per user message to allow deeper investigation
                    run_config=self._run_config,
                )

                response = result.final_output or "I encountered an issue processing your request."

                # Add agent response to history
                self._state.messages.append(
                    ChatMessage(
                        role="assistant", content=response, timestamp=workflow.now()
                    )
                )

                workflow.logger.info(f"Agent response: {response[:200]}...")

                # Check if this looks like a final report
                if self._is_final_report(response):
                    self._state.status = WorkflowStatus.COMPLETED
                    workflow.logger.info("Investigation completed with final report")
                    return response

            except Exception as e:
                workflow.logger.error(f"Agent error: {e}")
                error_msg = f"I encountered an error: {str(e)}. Please try again or rephrase your request."
                self._state.messages.append(
                    ChatMessage(
                        role="assistant", content=error_msg, timestamp=workflow.now()
                    )
                )

        # Workflow ended
        if self._should_end:
            self._state.status = WorkflowStatus.ENDED
            return "Investigation ended by user."
        else:
            self._state.status = WorkflowStatus.COMPLETED
            return "Investigation completed (max turns reached)."

    # =========================================================================
    # Agent Creation
    # =========================================================================

    def _create_investigation_agent(self) -> Agent:
        """Create the investigation agent with specialists."""
        available_mcp_servers = self._get_available_mcp_servers()
        workflow_ref = self

        # Create shared context tools
        update_tool, get_tool, print_report_tool = create_shared_context_tools(
            self._shared_context, agent_name="InvestigationAgent"
        )

        # Create the domain specialists
        compute_spec = new_specialist_agent(
            domain=DomainType.COMPUTE,
            model=self._config.model,
            available_mcp_servers=available_mcp_servers,
            tools=[update_tool, get_tool, print_report_tool],
        )
        storage_spec = new_specialist_agent(
            domain=DomainType.STORAGE,
            model=self._config.model,
            available_mcp_servers=available_mcp_servers,
            tools=[update_tool, get_tool, print_report_tool],
        )
        network_spec = new_specialist_agent(
            domain=DomainType.NETWORK,
            model=self._config.model,
            available_mcp_servers=available_mcp_servers,
            tools=[update_tool, get_tool, print_report_tool],
        )

        # Map agent names to agent objects for dynamic selection
        specialist_map = {
            "ComputeSpecialist": compute_spec,
            "StorageSpecialist": storage_spec,
            "NetworkSpecialist": network_spec,
        }

        # Create tools
        ask_user_tool = self._create_ask_user_tool()
        fetch_alerts_tool = self._create_fetch_alerts_tool()
        # Pass specialist_map so select_specialist can directly run specialists
        select_specialist_tool = self._create_select_specialist_tool(specialist_map)

        # Create the SingleAlertInvestigator factory
        async def on_handoff_to_investigator(ctx: Any, input: InvestigateAlertInput):
            # 1. Find alert details from state
            alert = next(
                (a for a in workflow_ref._state.last_fetched_alerts if a.get("fingerprint") == input.fingerprint),
                None
            )

            alert_context = f"Fingerprint: {input.fingerprint}\n"
            if alert:
                alert_context += f"Name: {alert.get('labels', {}).get('alertname', 'Unknown')}\n"
                alert_context += f"Summary: {alert.get('annotations', {}).get('summary', 'N/A')}\n"
                alert_context += f"Labels: {alert.get('labels', {})}\n"
            else:
                alert_context += "Alert details not found in cache. Please use MCP tools to find info if possible."

            # 2. Create the investigator agent with select_specialist tool
            # select_specialist now directly runs specialists and returns findings
            agent_name = f"Investigator_{input.fingerprint[:8]}"
            investigator = new_single_alert_investigator_agent(
                model=workflow_ref._config.model,
                tools=[update_tool, get_tool, ask_user_tool, select_specialist_tool],
                agent_name=agent_name,
                alert_context=alert_context,
            )

            return investigator

        # Create main investigation agent
        # Handoffs are only used for investigate_alert (creating per-alert investigators)
        # Specialist consultation is handled directly by select_specialist tool
        agent = Agent(
            name="InvestigationAgent",
            model=self._config.model,
            instructions=INVESTIGATION_AGENT_PROMPT,
            tools=[
                ask_user_tool,
                fetch_alerts_tool,
                select_specialist_tool,
                print_report_tool,
            ],
            handoffs=[
                handoff(
                    compute_spec,  # Placeholder, on_handoff returns the real investigator
                    on_handoff=on_handoff_to_investigator,
                    input_type=InvestigateAlertInput,
                    tool_name_override="investigate_alert",
                    tool_description_override="Hand off a specific alert to a specialized investigator for deep analysis."
                ),
            ],
        )

        return agent

    def _get_available_mcp_servers(self) -> list[str]:
        """Get list of available MCP server names."""
        if not self._mcp_config:
            return []
        return [server.name for server in self._mcp_config.enabled_servers]

    # =========================================================================
    # Tool Creation
    # =========================================================================

    def _create_ask_user_tool(self):
        """Create the ask_user tool that pauses for user input."""
        workflow_ref = self

        @function_tool
        async def ask_user(question: str) -> str:
            """Ask the user for clarification or additional information.

            Use this when you need more context to proceed with the investigation.
            The user will see your question and can provide an answer.

            Args:
                question: The question to ask the user. Be specific about what
                         information you need and why.

            Returns:
                The user's response to your question.
            """
            workflow.logger.info(f"ask_user called: {question}")

            # Set pending question in state
            workflow_ref._state.pending_question = question

            # The question becomes the agent's response, then we wait for user
            # This is handled by the conversation loop - we return a placeholder
            # that indicates we're waiting for user input

            # Wait for user response
            workflow_ref._has_pending_input = False
            await workflow.wait_condition(
                lambda: workflow_ref._has_pending_input or workflow_ref._should_end
            )

            workflow_ref._state.pending_question = None

            if workflow_ref._should_end:
                return "User ended the conversation."

            response = workflow_ref._pending_user_response or ""
            workflow.logger.info(f"User responded to ask_user: {response[:100]}...")
            return response

        return ask_user

    def _create_fetch_alerts_tool(self):
        """Create the fetch_alerts tool."""

        @function_tool
        async def fetch_alerts(
            status: str = "firing",
            alertname: str | None = None,
        ) -> str:
            """Fetch alerts from Alertmanager.

            Use this tool to get a list of current alerts. If the user does not specify a specific alert name,
            you should call this tool without the 'alertname' parameter to get all alerts with the given status.

            Args:
                status (str): The status of alerts to fetch. Can be 'firing', 'resolved', or 'all'. Defaults to 'firing'.
                alertname (Optional[str]): The specific name of an alert to filter by. Omit this to get all alerts.

            Example:
                User: "show me all firing alerts"
                Tool Call: `fetch_alerts(status='firing')`

            Returns:
                A formatted summary of matching alerts (including names, fingerprints, and summaries) or a message if none are found.
            """
            workflow.logger.info(f"fetch_alerts called: status={status}, alertname={alertname}")

            if not self._config.alertmanager_url:
                return "Error: Alertmanager URL is not configured."

            params = {
                "alertmanager_url": self._config.alertmanager_url,
                "status": status,
                "alertname": alertname,
            }

            try:
                alerts = await workflow.execute_activity(
                    "fetch_alerts_activity",
                    params,
                    start_to_close_timeout=timedelta(seconds=60),
                )
                # Store alerts in state for use by other tools/handoffs
                self._state.last_fetched_alerts = alerts
            except Exception as e:
                workflow.logger.error(f"Failed to fetch alerts: {e}")
                return f"Error: Failed to fetch alerts from Alertmanager: {e}"

            if not alerts:
                return f"No {status} alerts found" + (f" for '{alertname}'." if alertname else ".")

            # Format the output for the agent
            lines = [f"Found {len(alerts)} {status} alerts:"]
            for alert in alerts:
                labels = alert.get("labels", {})
                name = labels.get("alertname", "N/A")
                fingerprint = alert.get("fingerprint", "N/A")
                summary = alert.get("annotations", {}).get("summary", "No summary.")
                lines.append(f"- **{name}** (Fingerprint: `{fingerprint}`): {summary}")
                # Add a few key labels for context
                for key, value in labels.items():
                    if key not in ["alertname", "severity"]:
                        lines.append(f"  - {key}: {value}")

            return "\n".join(lines)

        return fetch_alerts

    def _create_select_specialist_tool(self, specialist_map: dict[str, Agent]):
        """Create the select_specialist tool that lets users choose and directly consults specialists.

        Args:
            specialist_map: Dictionary mapping specialist names to Agent objects.
        """
        workflow_ref = self

        @function_tool
        async def select_specialist(suggested: str, reason: str) -> str:
            """Consult a domain specialist for expert analysis.

            This tool lets the user choose which specialist to consult, then directly
            runs the specialist and returns their findings.

            Args:
                suggested: Your suggested specialist based on the context.
                          Must be one of: "ComputeSpecialist", "StorageSpecialist", "NetworkSpecialist"
                reason: Why you suggest this specialist and what they should investigate
                       (e.g., "Alert involves Ceph storage - investigate OSD status")

            Returns:
                The specialist's findings and analysis.

            Example:
                findings = select_specialist(
                    suggested="StorageSpecialist",
                    reason="Alert is for ceph-failure-test pod - investigate Ceph cluster health"
                )
                # Returns the specialist's detailed analysis
            """
            workflow.logger.info(f"select_specialist called: suggested={suggested}, reason={reason}")

            # Set up agent selection request for the CLI
            workflow_ref._state.pending_agent_selection = AgentSelectionRequest(
                from_agent="InvestigationAgent",
                suggested_agent=suggested,
                reason=reason,
                available_agents=HumanInTheLoopWorkflow.AVAILABLE_SPECIALISTS,
            )
            workflow_ref._pending_agent_selection = True
            workflow_ref._selected_agent = None

            # Wait for user selection
            await workflow.wait_condition(lambda: not workflow_ref._pending_agent_selection)

            # Clear the pending state
            workflow_ref._state.pending_agent_selection = None
            selected = workflow_ref._selected_agent

            if not selected:
                return "Selection cancelled by user. Please ask the user what they would like to do."

            workflow.logger.info(f"User selected specialist: {selected}")

            # Get the selected specialist agent
            specialist = specialist_map.get(selected)
            if not specialist:
                return f"Error: Unknown specialist '{selected}'. Available: {list(specialist_map.keys())}"

            # Run the specialist agent directly
            workflow.logger.info(f"Running specialist {selected} with reason: {reason}")
            try:
                result = await Runner.run(
                    specialist,
                    input=f"Investigate: {reason}",
                    max_turns=20,
                    run_config=workflow_ref._run_config,
                )
                findings = result.final_output or "Specialist completed but returned no findings."
                workflow.logger.info(f"Specialist {selected} completed: {findings[:200]}...")
                return f"**{selected} Findings:**\n\n{findings}"
            except Exception as e:
                workflow.logger.error(f"Specialist {selected} failed: {e}")
                return f"Error: Specialist {selected} encountered an error: {str(e)}"

        return select_specialist

    # =========================================================================
    # Helpers
    # =========================================================================

    def _build_conversation_input(self) -> str:
        """Build the conversation history as input for the agent."""
        if not self._state.messages:
            return "Hello, I'm ready to help investigate infrastructure issues."

        # Build a conversation summary
        lines = ["## Conversation History\n"]
        for msg in self._state.messages[-10:]:  # Last 10 messages
            role = "User" if msg.role == "user" else "Assistant"
            lines.append(f"**{role}:** {msg.content}\n")

        # Add shared context if there are findings
        if self._shared_context.findings:
            lines.append("\n## Current Investigation Findings\n")
            lines.append(self._shared_context.format_summary())

        return "\n".join(lines)

    def _is_final_report(self, response: str) -> bool:
        """Check if the response looks like a final investigation report."""
        # Look for indicators of a final report
        indicators = [
            "root cause analysis",
            "root cause:",
            "recommended actions:",
            "remediation steps:",
            "investigation complete",
            "summary of findings",
        ]
        response_lower = response.lower()
        return any(indicator in response_lower for indicator in indicators)

"""Human-in-the-Loop Investigation Workflow.

A simple conversational workflow where:
- User converses with an investigation agent
- Agent has tools to fetch alerts from Alertmanager
- Agent can investigate infrastructure using UTCP tools (Kubernetes, Grafana, Ceph)
- Agent asks for clarification naturally when needed via ask_user tool
- Agent can hand off to domain specialists for deep technical analysis
"""

from datetime import timedelta

from agents import Agent, Runner, RunConfig, function_tool
from temporalio import workflow

from ein_agent_worker.models import (
    SharedContext,
    WorkflowStatus,
    ChatMessage,
    WorkflowState,
    HITLConfig,
    WorkflowEvent,
    WorkflowEventType,
)

with workflow.unsafe.imports_passed_through():
    from ein_agent_worker.models.gemini_litellm_provider import GeminiCompatibleLitellmProvider
    from ein_agent_worker.activities.worker_config import load_worker_model
    from ein_agent_worker.workflows.agents.specialists import (
        DomainType,
        new_specialist_agent,
        DOMAIN_UTCP_SERVICES,
    )
    from ein_agent_worker.workflows.agents.shared_context_tools import (
        create_shared_context_tools,
    )
    from ein_agent_worker.utcp import registry as utcp_registry
    from ein_agent_worker.utcp.temporal_utcp import create_utcp_workflow_tools

# =============================================================================
# Investigation Agent Prompt
# =============================================================================
# ... (Prompt string kept as is)
INVESTIGATION_AGENT_PROMPT = """You are the Investigation Assistant (The Orchestrator).

## Your Capabilities
- **Fetch Alerts**: Use `fetch_alerts` to get current firing alerts.
- **Direct Infrastructure Access**: You have UTCP tools to query infrastructure directly:
  - **Kubernetes**: Use `search_kubernetes_operations`, `get_kubernetes_operation_details`, `call_kubernetes_operation`
  - **Grafana**: Use `search_grafana_operations`, `get_grafana_operation_details`, `call_grafana_operation`
  - **Ceph** (if enabled): Use `search_ceph_operations`, `get_ceph_operation_details`, `call_ceph_operation`
- **Consult Domain Specialists**: For deep technical investigations, hand off to specialists:
  - **ComputeSpecialist**: For complex Kubernetes/Grafana investigations requiring domain expertise.
  - **StorageSpecialist**: For complex Ceph/storage investigations requiring domain expertise.
  - **NetworkSpecialist**: For complex networking investigations requiring domain expertise.
- **Shared Context**: Use `get_shared_context`, `update_shared_context`, and `group_findings` to manage investigation findings.
- **Ask User**: Ask for clarification or provide updates using `ask_user`.
- **Print Findings Report**: Use `print_findings_report` to generate a formatted summary of all investigation findings.

## Your Workflow
1. **Analyze User Request**: Determine if the user wants to investigate a specific alert or has a general infrastructure question.
2. **Answer Simple Queries Directly**: For straightforward requests, use UTCP tools directly:
   - "list grafana dashboards" → Use `search_grafana_operations` + `call_grafana_operation`
   - "show kubernetes pods" → Use `search_kubernetes_operations` + `call_kubernetes_operation`
   - "check ceph health" → Use `search_ceph_operations` + `call_ceph_operation`
3. **Delegate Complex Investigations**: For multi-step investigations requiring domain expertise, hand off to specialists:
   - Example: "investigate why storage is slow" → Delegate to StorageSpecialist
4. **Synthesize & Group**: As findings accumulate, use `group_findings` to consolidate related findings.
5. **Report**: Use `print_findings_report` to show the current status.
6. **Ongoing Support**: You are an always-on assistant. Do not close the session unless the user explicitly asks to stop.

## CRITICAL RULES
- **USE UTCP TOOLS DIRECTLY**: For simple queries (list, show, get), use your UTCP tools directly. No need to delegate.
- **DELEGATE FOR DEEP ANALYSIS**: Only hand off to specialists for complex investigations requiring domain expertise.
- **HANDOFFS**: Use the standard transfer tools to delegate (e.g., `transfer_to_computespecialist`).
- **OUTPUTTING REPORTS**: Always output the content of `print_findings_report` to the user.
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
        self._run_config: RunConfig | None = None
        self._event_queue: list[WorkflowEvent] = []
        self._should_end = False
        self._utcp_tools: dict[str, list] = {}  # service_name -> tools

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
        self._event_queue.append(
            WorkflowEvent(
                type=WorkflowEventType.MESSAGE,
                payload=message,
                timestamp=workflow.now()
            )
        )

    @workflow.signal
    async def end_workflow(self) -> None:
        """User wants to end the conversation."""
        workflow.logger.info("End workflow signal received")
        self._should_end = True
        self._event_queue.append(
            WorkflowEvent(
                type=WorkflowEventType.STOP,
                timestamp=workflow.now()
            )
        )

    @workflow.signal
    async def provide_confirmation(self, confirmed: bool) -> None:
        """User provides confirmation for a pending action."""
        workflow.logger.info(f"Received confirmation: {confirmed}")
        self._event_queue.append(
            WorkflowEvent(
                type=WorkflowEventType.CONFIRMATION,
                payload=confirmed,
                timestamp=workflow.now()
            )
        )

    @workflow.signal
    async def provide_agent_selection(self, selected_agent: str) -> None:
        """User selects an agent from the available options.

        Args:
            selected_agent: Name of the selected agent, or empty string to cancel.
        """
        workflow.logger.info(f"Received agent selection: {selected_agent}")
        self._event_queue.append(
            WorkflowEvent(
                type=WorkflowEventType.SELECTION,
                payload=selected_agent if selected_agent else None,
                timestamp=workflow.now()
            )
        )

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
    # Event Handling
    # =========================================================================

    async def _next_event(self) -> WorkflowEvent:
        """Wait for and return the next event from the queue."""
        await workflow.wait_condition(lambda: len(self._event_queue) > 0)
        return self._event_queue.pop(0)

    async def _wait_for_event_type(self, event_type: WorkflowEventType) -> WorkflowEvent:
        """Wait for a specific event type, skipping others."""
        while True:
            event = await self._next_event()
            if event.type == event_type or event.type == WorkflowEventType.STOP:
                return event
            workflow.logger.info(f"Ignoring event type {event.type} while waiting for {event_type}")

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

        # Load worker model configuration from environment
        self._config.model = await workflow.execute_activity(
            load_worker_model,
            start_to_close_timeout=timedelta(seconds=10),
        )
        workflow.logger.info(f"Using model: {self._config.model}")

        # Setup run config
        self._run_config = RunConfig(
            model_provider=GeminiCompatibleLitellmProvider(),
            tracing_disabled=True,
        )

        # Initialize UTCP tools
        self._initialize_utcp_tools()

        # Create the investigation agent
        agent = self._create_investigation_agent()

        # Handle initial message or produce greeting
        if initial_message:
            # Add to messages and push a dummy event to trigger the first turn
            self._state.messages.append(
                ChatMessage(
                    role="user", content=initial_message, timestamp=workflow.now()
                )
            )
            self._event_queue.append(
                WorkflowEvent(
                    type=WorkflowEventType.MESSAGE,
                    payload=initial_message,
                    timestamp=workflow.now()
                )
            )
        else:
            # No initial message - produce a greeting
            greeting = (
                "Hello! I'm your infrastructure investigation assistant. "
                "I can help you investigate alerts and infrastructure issues.\n\n"
                "You can:\n"
                "- Ask me to fetch and investigate current alerts\n"
                "- Describe an issue you're experiencing\n"
                "- Ask questions about your infrastructure\n\n"
                "How can I help today?"
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
            # Wait for user input (MESSAGE or STOP)
            workflow.logger.info("Waiting for user message...")
            event = await self._wait_for_event_type(WorkflowEventType.MESSAGE)

            if self._should_end or event.type == WorkflowEventType.STOP:
                break

            turn_count += 1
            # Build conversation history for the agent
            conversation = self._build_conversation_input()

            workflow.logger.info(f"Running agent turn {turn_count}")

            try:
                # Run the agent
                result = await Runner.run(
                    agent,
                    input=conversation,
                    max_turns=30,
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

    def _initialize_utcp_tools(self) -> None:
        """Initialize UTCP tools from pre-registered clients.

        UTCP clients are initialized at worker startup (where network I/O is allowed)
        and stored in the registry. This method creates the 3 meta-tools
        (search, get_details, call) for each registered service.

        These tools execute UTCP operations as Temporal activities, allowing
        network I/O to happen outside the workflow sandbox.
        """
        services = utcp_registry.list_services()

        if not services:
            workflow.logger.info("No UTCP services registered")
            return

        workflow.logger.info(f"Creating tools for {len(services)} UTCP service(s)")

        for service_name in services:
            # Create workflow tools that execute as activities
            tools = create_utcp_workflow_tools(service_name)
            self._utcp_tools[service_name] = tools
            workflow.logger.info(
                f"Created {len(tools)} tools for {service_name}: "
                f"{[getattr(t, 'name', str(t)) for t in tools]}"
            )

    def _get_domain_utcp_tools(self, domain: DomainType) -> list:
        """Get UTCP tools for a specific domain.

        Args:
            domain: The domain type

        Returns:
            List of UTCP tools for the domain's services
        """
        tools = []
        services = DOMAIN_UTCP_SERVICES.get(domain, set())
        for service in services:
            if service in self._utcp_tools:
                tools.extend(self._utcp_tools[service])
        return tools

    def _create_investigation_agent(self) -> Agent:
        """Create the investigation agent with specialists."""
        # Create shared context tools for the Orchestrator
        update_tool, get_tool, print_report_tool, group_tool = create_shared_context_tools(
            self._shared_context, agent_name="InvestigationAgent"
        )

        # Collect ALL UTCP tools for the main agent (for simple queries)
        all_utcp_tools = []
        for service_name in self._utcp_tools:
            all_utcp_tools.extend(self._utcp_tools[service_name])
        workflow.logger.info(f"Investigation Agent has {len(all_utcp_tools)} UTCP tools")

        # Create tools for ComputeSpecialist (shared context + UTCP tools)
        comp_update, comp_get, comp_print, comp_group = create_shared_context_tools(
            self._shared_context, agent_name="ComputeSpecialist"
        )
        compute_utcp_tools = self._get_domain_utcp_tools(DomainType.COMPUTE)
        compute_spec = new_specialist_agent(
            domain=DomainType.COMPUTE,
            model=self._config.model,
            tools=[comp_update, comp_get, comp_print, comp_group] + compute_utcp_tools,
        )

        # Create tools for StorageSpecialist (shared context + UTCP tools)
        stor_update, stor_get, stor_print, stor_group = create_shared_context_tools(
            self._shared_context, agent_name="StorageSpecialist"
        )
        storage_utcp_tools = self._get_domain_utcp_tools(DomainType.STORAGE)
        storage_spec = new_specialist_agent(
            domain=DomainType.STORAGE,
            model=self._config.model,
            tools=[stor_update, stor_get, stor_print, stor_group] + storage_utcp_tools,
        )

        # Create tools for NetworkSpecialist (shared context + UTCP tools)
        net_update, net_get, net_print, net_group = create_shared_context_tools(
            self._shared_context, agent_name="NetworkSpecialist"
        )
        network_utcp_tools = self._get_domain_utcp_tools(DomainType.NETWORK)
        network_spec = new_specialist_agent(
            domain=DomainType.NETWORK,
            model=self._config.model,
            tools=[net_update, net_get, net_print, net_group] + network_utcp_tools,
        )

        # Create tools
        ask_user_tool = self._create_ask_user_tool()
        fetch_alerts_tool = self._create_fetch_alerts_tool()

        # Create main investigation agent with ALL UTCP tools for direct queries
        agent = Agent(
            name="InvestigationAgent",
            model=self._config.model,
            instructions=INVESTIGATION_AGENT_PROMPT,
            tools=[
                ask_user_tool,
                fetch_alerts_tool,
                print_report_tool,
                get_tool,
                update_tool,
                group_tool,
            ] + all_utcp_tools,  # Add all UTCP tools for direct access
            handoffs=[compute_spec, storage_spec, network_spec],
        )

        # Wire back-handoffs
        compute_spec.handoffs = [agent]
        storage_spec.handoffs = [agent]
        network_spec.handoffs = [agent]

        return agent

    # =========================================================================
    # Tool Creation
    # =========================================================================

    def _create_ask_user_tool(self):
        """Create the ask_user tool that pauses for user input."""
        workflow_ref = self

        @function_tool
        async def ask_user(question: str) -> str:
            """Ask the user for clarification or additional information.

            Args:
                question: The question to ask the user.
            """
            workflow.logger.info(f"ask_user called: {question}")

            # Set pending question in state for UI
            workflow_ref._state.pending_question = question

            # Wait for user response
            event = await workflow_ref._wait_for_event_type(WorkflowEventType.MESSAGE)

            # Clear pending question
            workflow_ref._state.pending_question = None

            if event.type == WorkflowEventType.STOP:
                return "User ended the conversation."

            response = event.payload or ""
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
            """Fetch alerts from Alertmanager."""
            workflow.logger.info(f"fetch_alerts called: status={status}, alertname={alertname}")

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
                self._state.last_fetched_alerts = alerts
            except Exception as e:
                workflow.logger.error(f"Failed to fetch alerts: {e}")
                return f"Error: Failed to fetch alerts from Alertmanager: {e}"

            if not alerts:
                return f"No {status} alerts found" + (f" for '{alertname}'." if alertname else ".")

            lines = [ f"Found {len(alerts)} {status} alerts:" ]
            for alert in alerts:
                labels = alert.get("labels", {})
                name = labels.get("alertname", "N/A")
                fingerprint = alert.get("fingerprint", "N/A")
                summary = alert.get("annotations", {}).get("summary", "No summary.")
                lines.append(f"- **{name}** (Fingerprint: `{fingerprint}`): {summary}")
                for key, value in labels.items():
                    if key not in ["alertname", "severity"]:
                        lines.append(f"  - {key}: {value}")

            return "\n".join(lines)

        return fetch_alerts


    # =========================================================================
    # Helpers
    # =========================================================================

    def _build_conversation_input(self) -> str:
        """Build the conversation history as input for the agent."""
        if not self._state.messages:
            return "Hello, I'm ready to help investigate infrastructure issues."

        lines = ["## Conversation History\n"]
        for msg in self._state.messages[-10:]:
            role = "User" if msg.role == "user" else "Assistant"
            lines.append(f"**{role}:** {msg.content}\n")

        if self._shared_context.findings:
            lines.append("\n## Current Investigation Findings\n")
            lines.append(self._shared_context.format_summary())

        return "\n".join(lines)



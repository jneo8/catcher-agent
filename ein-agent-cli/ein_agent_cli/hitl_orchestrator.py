"""Orchestrator for Human-in-the-Loop investigation workflow."""

import asyncio
from datetime import datetime
from typing import Any

from temporalio.client import Client as TemporalClient, WorkflowHandle
import temporalio.common

from ein_agent_cli import console
from ein_agent_cli.models import HITLWorkflowConfig


class HITLOrchestrator:
    """Orchestrator for human-in-the-loop investigation workflow."""

    def __init__(
        self,
        handle: WorkflowHandle,
        config: HITLWorkflowConfig,
    ):
        self.handle = handle
        self.config = config
        self._last_message_count = 0

    @classmethod
    async def create(
        cls,
        config: HITLWorkflowConfig,
        initial_message: str | None = None,
    ) -> "HITLOrchestrator":
        """Create a new HITL orchestrator and start the workflow.

        Args:
            config: Workflow configuration
            initial_message: Optional initial message to start conversation

        Returns:
            HITLOrchestrator instance
        """
        # Connect to Temporal
        client = await TemporalClient.connect(
            config.temporal.host,
            namespace=config.temporal.namespace,
        )

        # Generate workflow ID
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        workflow_id = config.workflow_id or f"hitl-investigation-{timestamp}"

        console.print_info(f"Starting workflow: {workflow_id}")

        # Prepare workflow config
        workflow_config = {
            "model": config.model,
            "alertmanager_url": config.alertmanager_url,
            "max_turns": config.max_turns,
        }

        # Start workflow
        handle = await client.start_workflow(
            "HumanInTheLoopWorkflow",
            args=[initial_message, workflow_config],
            id=workflow_id,
            task_queue=config.temporal.queue,
            id_reuse_policy=temporalio.common.WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        )

        console.print_success(f"Workflow started: {workflow_id}")

        return cls(handle, config)

    @classmethod
    async def connect(
        cls,
        config: HITLWorkflowConfig,
        workflow_id: str,
    ) -> "HITLOrchestrator":
        """Connect to an existing workflow.

        Args:
            config: Workflow configuration
            workflow_id: Existing workflow ID

        Returns:
            HITLOrchestrator instance
        """
        client = await TemporalClient.connect(
            config.temporal.host,
            namespace=config.temporal.namespace,
        )

        handle = client.get_workflow_handle(workflow_id)
        console.print_info(f"Connected to workflow: {workflow_id}")

        return cls(handle, config)

    async def send_message(self, message: str) -> None:
        """Send a message to the agent.

        Args:
            message: User message
        """
        await self.handle.signal("send_message", message)

    async def end_workflow(self) -> None:
        """End the workflow."""
        await self.handle.signal("end_workflow")

    async def provide_confirmation(self, confirmed: bool) -> None:
        """Send confirmation for a pending tool call.

        Args:
            confirmed: Whether the user confirmed the action
        """
        await self.handle.signal("provide_confirmation", confirmed)

    async def provide_agent_selection(self, selected_agent: str) -> None:
        """Send the selected agent for a pending handoff.

        Args:
            selected_agent: Name of the selected agent, or empty string to cancel.
        """
        await self.handle.signal("provide_agent_selection", selected_agent)

    async def get_state(self) -> dict[str, Any]:
        """Get current workflow state.

        Returns:
            Workflow state dictionary
        """
        return await self.handle.query("get_state")

    async def get_messages(self) -> list[dict[str, Any]]:
        """Get conversation history.

        Returns:
            List of message dictionaries
        """
        return await self.handle.query("get_messages")

    async def get_status(self) -> str:
        """Get workflow status.

        Returns:
            Status string
        """
        return await self.handle.query("get_status")

    async def _handle_agent_selection(self, selection: dict[str, Any]) -> str:
        """Handle agent selection UI.

        Displays a numbered list of available agents with the suggested one as default.
        User can press Enter to accept default or type a number to choose different agent.

        Args:
            selection: Agent selection request with from_agent, suggested_agent,
                      reason, and available_agents fields.

        Returns:
            Name of the selected agent, or empty string if cancelled.
        """
        from_agent = selection.get("from_agent", "Agent")
        suggested = selection.get("suggested_agent", "")
        reason = selection.get("reason", "")
        available = selection.get("available_agents", [])

        # Build the selection message
        lines = [
            f"Agent '{from_agent}' wants to hand off to a specialist.",
            f"Reason: {reason}",
            "",
            "Available agents:",
        ]

        # Find the suggested agent's index to mark it as default
        suggested_idx = -1
        for i, agent_name in enumerate(available, start=1):
            marker = ""
            if agent_name == suggested:
                marker = " (suggested)"
                suggested_idx = i
            lines.append(f"  [{i}] {agent_name}{marker}")

        lines.append("  [0] Cancel")
        lines.append("")

        # Display the panel
        console.print_panel(
            "\n".join(lines),
            title="[yellow]Agent Selection[/yellow]",
            border_style="yellow",
        )

        # Get user input
        default_display = f"{suggested_idx}" if suggested_idx > 0 else "1"
        prompt = f"Select agent [{default_display}]: "

        while True:
            user_input = input(prompt).strip()

            # Handle Enter key (accept default)
            if not user_input:
                if suggested_idx > 0:
                    console.print_info(f"Selected: {suggested}")
                    return suggested
                elif available:
                    console.print_info(f"Selected: {available[0]}")
                    return available[0]
                else:
                    return ""

            # Handle numeric input
            try:
                choice = int(user_input)
                if choice == 0:
                    console.print_warning("Selection cancelled.")
                    return ""
                if 1 <= choice <= len(available):
                    selected = available[choice - 1]
                    console.print_info(f"Selected: {selected}")
                    return selected
                else:
                    console.print_error(f"Invalid choice. Please enter 0-{len(available)}.")
            except ValueError:
                console.print_error("Please enter a number.")

    async def wait_for_response(
        self,
        poll_interval: float = 0.5,
        timeout: float = 300.0,
    ) -> str | None:
        """Wait for agent to respond.

        Args:
            poll_interval: Polling interval in seconds
            timeout: Maximum wait time in seconds

        Returns:
            Agent response or None if timeout/ended
        """
        start_time = asyncio.get_event_loop().time()

        while True:
            # Get full state to check messages, status, and pending questions
            state = await self.get_state()
            messages = state.get("messages", [])
            status = state.get("status", "unknown")
            pending_question = state.get("pending_question")
            pending_tool_call = state.get("pending_tool_call")

            current_count = len(messages)

            # Check for new messages
            if current_count > self._last_message_count:
                # Find new assistant messages
                new_messages = messages[self._last_message_count:]
                self._last_message_count = current_count

                for msg in new_messages:
                    if msg.get("role") == "assistant":
                        return msg.get("content", "")

            # Check for pending question from agent (ask_user tool)
            if pending_question:
                # Agent is waiting for user input
                return pending_question

            if pending_tool_call:
                return "[TOOL_CALL]"

            if state.get("pending_agent_selection"):
                return "[AGENT_SELECTION]"

            if state.get("pending_handoff"):
                return "[HANDOFF]"

            # Check status
            if status in ["completed", "ended"]:
                return None

            # Check timeout
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed >= timeout:
                console.print_warning("Timeout waiting for response")
                return None

            await asyncio.sleep(poll_interval)

    async def run_interactive(self) -> None:
        """Run interactive conversation loop."""
        console.print_header("\nInvestigation Assistant")
        console.print_dim("Type your message and press Enter. Type /quit to exit.\n")

        # Wait for initial response if workflow just started
        console.print_dim("Waiting for agent...")
        initial_response = await self.wait_for_response()
        if initial_response:
            console.print_message(f"\n[bold cyan]Agent:[/bold cyan] {initial_response}\n")

        while True:
            try:
                # Get user input
                user_input = input("You: ").strip()

                if not user_input:
                    continue

                # Handle commands
                if user_input.lower() in ["/quit", "/exit", "/q"]:
                    console.print_info("Ending conversation...")
                    await self.end_workflow()
                    break

                if user_input.lower() == "/status":
                    state = await self.get_state()
                    console.print_info(f"Status: {state.get('status', 'unknown')}")
                    console.print_dim(f"Messages: {len(state.get('messages', []))}")
                    continue

                if user_input.lower() == "/history":
                    messages = await self.get_messages()
                    console.print_info(f"\n--- Conversation History ({len(messages)} messages) ---")
                    for msg in messages:
                        role = msg.get("role", "unknown")
                        content = msg.get("content", "")[:200]
                        if len(msg.get("content", "")) > 200:
                            content += "..."
                        console.print_message(f"[bold]{role}:[/bold] {content}")
                    console.print_info("--- End History ---\n")
                    continue

                # Send message to agent
                await self.send_message(user_input)

                while True:
                    # Wait for response
                    console.print_dim("Thinking...")
                    response = await self.wait_for_response()

                    if response == "[TOOL_CALL]":
                        state = await self.get_state()
                        tool_call = state.get("pending_tool_call")
                        if tool_call:
                            console.print_panel(
                                f"Tool: {tool_call['name']}\nArguments: {tool_call['arguments']}",
                                title="[yellow]Confirmation Required[/yellow]",
                                border_style="yellow",
                            )
                            confirm = input("Run this tool? (y/n): ").lower()
                            await self.provide_confirmation(confirm == "y")
                            continue

                    if response == "[AGENT_SELECTION]":
                        state = await self.get_state()
                        selection = state.get("pending_agent_selection")
                        if selection:
                            selected = await self._handle_agent_selection(selection)
                            await self.provide_agent_selection(selected)
                            continue

                    if response == "[HANDOFF]":
                        state = await self.get_state()
                        handoff = state.get("pending_handoff")
                        if handoff:
                            msg = f"Agent '{handoff['from']}' wants to hand off to '{handoff['to']}'."
                            if handoff.get("reason"):
                                msg += f"\nReason: {handoff['reason']}"
                            console.print_panel(
                                msg,
                                title="[yellow]Handoff Confirmation Required[/yellow]",
                                border_style="yellow",
                            )
                            confirm = input("Approve this handoff? (y/n): ").lower()
                            await self.provide_confirmation(confirm == "y")
                            continue


                    if response:
                        console.print_message(f"\n[bold cyan]Agent:[/bold cyan] {response}\n")
                        break
                    else:
                        # Check if workflow ended
                        status = await self.get_status()
                        if status == "completed":
                            console.print_success("\nInvestigation completed!")
                            break
                        elif status == "ended":
                            console.print_info("\nConversation ended.")
                            break
                if (await self.get_status()) in ["completed", "ended"]:
                    break

            except KeyboardInterrupt:
                console.print_warning("\nInterrupted. Ending conversation...")
                await self.end_workflow()
                break
            except EOFError:
                console.print_info("\nEnding conversation...")
                await self.end_workflow()
                break

        console.print_info("Goodbye!")



async def run_hitl_workflow(config: HITLWorkflowConfig) -> None:
    """Run the human-in-the-loop investigation workflow.

    Args:
        config: Workflow configuration
    """
    try:
        console.print_header("Ein Agent - Interactive Investigation\n")

        # Create orchestrator and start workflow
        orchestrator = await HITLOrchestrator.create(
            config=config,
            initial_message=None,  # Wait for user's first message
        )

        # Run interactive loop
        await orchestrator.run_interactive()

    except Exception as e:
        console.print_error(f"Error: {e}")
        raise

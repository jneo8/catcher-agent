import asyncio
import functools
from datetime import datetime
from typing import Any

from temporalio.client import Client as TemporalClient, WorkflowHandle
import temporalio.common
from temporalio.service import RPCError

from ein_agent_cli import console
from ein_agent_cli.models import HITLWorkflowConfig


def handle_rpc_error(return_on_error: Any = None, print_error: bool = True):
    """Decorator to handle RPC errors (specifically workflow completion)."""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except RPCError as e:
                if "workflow execution already completed" in str(e).lower():
                    if print_error:
                        console.print_error("Cannot perform action: Workflow is already completed.")
                    return return_on_error
                raise
        return wrapper
    return decorator


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

        # Prepare workflow config (model is configured on worker via EIN_AGENT_MODEL env var)
        workflow_config = {
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

    @handle_rpc_error()
    async def send_message(self, message: str) -> None:
        """Send a message to the agent.

        Args:
            message: User message
        """
        await self.handle.signal("send_message", message)

    @handle_rpc_error(print_error=False)
    async def end_workflow(self) -> None:
        """End the workflow."""
        await self.handle.signal("end_workflow")

    @handle_rpc_error()
    async def provide_confirmation(self, confirmed: bool) -> None:
        """Send confirmation for a pending tool call.

        Args:
            confirmed: Whether the user confirmed the action
        """
        await self.handle.signal("provide_confirmation", confirmed)

    @handle_rpc_error()
    async def provide_agent_selection(self, selected_agent: str) -> None:
        """Send the selected agent for a pending handoff.

        Args:
            selected_agent: Name of the selected agent, or empty string to cancel.
        """
        await self.handle.signal("provide_agent_selection", selected_agent)

    @handle_rpc_error()
    async def provide_approval_decisions(self, decisions: list[dict]) -> None:
        """Send approval decisions for pending tool calls.

        Args:
            decisions: List of approval decision dicts (interruption_id, approved, always, reason)
        """
        await self.handle.signal("provide_approval_decisions", decisions)

    @handle_rpc_error(return_on_error={"status": "completed"}, print_error=False)
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

    async def _handle_approval_interruptions(self, interruptions: list[dict[str, Any]]) -> list[dict]:
        """Handle approval interruptions UI.

        Displays each tool call and prompts user to approve/reject with sticky option.

        Args:
            interruptions: List of WorkflowInterruption dicts

        Returns:
            List of ApprovalDecision dicts
        """
        console.print_panel(
            f"Agent needs approval for {len(interruptions)} operation(s)",
            title="[yellow]Tool Approval Required[/yellow]",
            border_style="yellow",
        )

        decisions = []

        for idx, interruption in enumerate(interruptions, 1):
            interruption_id = interruption["id"]
            tool_name = interruption.get("tool_name", "unknown")
            arguments = interruption.get("arguments", {})
            agent_name = interruption.get("agent_name", "Agent")

            # Extract real operation from UTCP wrapper if present
            real_tool_name = tool_name
            real_arguments = arguments

            if tool_name.startswith("call_") and tool_name.endswith("_operation"):
                # This is a UTCP wrapper, extract the real operation
                real_tool_name = arguments.get("tool_name", tool_name)
                args_str = arguments.get("arguments", "{}")

                # Parse the arguments string
                if isinstance(args_str, str):
                    import json
                    try:
                        real_arguments = json.loads(args_str) if args_str else {}
                    except json.JSONDecodeError:
                        real_arguments = {"raw": args_str}
                else:
                    real_arguments = args_str if isinstance(args_str, dict) else {}

            # Display compact approval request
            console.print_dim(f"\n({idx}/{len(interruptions)}) {agent_name}")
            console.print_message(f"  → [cyan]{real_tool_name}[/cyan]")

            # Show arguments only if non-empty
            if real_arguments:
                console.print_dim("  Arguments:")
                for key, value in real_arguments.items():
                    value_str = str(value)
                    if len(value_str) > 80:
                        value_str = value_str[:77] + "..."
                    console.print_dim(f"    {key}: {value_str}")

            # Prompt for decision with clearer options
            print()
            console.print_message("  [dim]y[/dim] - Approve once      [dim]a[/dim] - Approve always")
            console.print_message("  [dim]n[/dim] - Reject once       [dim]r[/dim] - Reject always")
            print()

            while True:
                choice = input("  Your choice: ").strip().lower()

                # Flexible input parsing
                if choice in ("y", "yes", "approve"):
                    decisions.append({
                        "interruption_id": interruption_id,
                        "approved": True,
                        "always": False,
                    })
                    console.print_success("  ✓ Approved")
                    break
                elif choice in ("a", "always", "approve always"):
                    decisions.append({
                        "interruption_id": interruption_id,
                        "approved": True,
                        "always": True,
                    })
                    console.print_success(f"  ✓ Approved always → [dim]{real_tool_name}[/dim]")
                    break
                elif choice in ("n", "no", "reject"):
                    decisions.append({
                        "interruption_id": interruption_id,
                        "approved": False,
                        "always": False,
                    })
                    console.print_warning("  ✗ Rejected")
                    break
                elif choice in ("r", "reject always", "always reject"):
                    decisions.append({
                        "interruption_id": interruption_id,
                        "approved": False,
                        "always": True,
                    })
                    console.print_warning(f"  ✗ Rejected always → [dim]{real_tool_name}[/dim]")
                    break
                else:
                    console.print_error("  Invalid. Enter: y, a, n, or r")

            print()  # Add spacing between interruptions

        return decisions

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
                # Iterate through new messages
                for i in range(self._last_message_count, current_count):
                    msg = messages[i]
                    if msg.get("role") == "assistant":
                        # Update counter to next message and return
                        self._last_message_count = i + 1
                        return msg.get("content", "")

                # No assistant messages found in new batch
                self._last_message_count = current_count

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

            # Check for interruptions (tool approvals, etc.)
            interruptions = state.get("interruptions", [])
            if interruptions:
                return "[INTERRUPTIONS]"

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
        # If we just connected and there are existing messages, wait_for_response will return them
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

                    if response == "[INTERRUPTIONS]":
                        state = await self.get_state()
                        interruptions = state.get("interruptions", [])
                        if interruptions:
                            # Handle all interruptions and collect decisions
                            decisions = await self._handle_approval_interruptions(interruptions)
                            # Send decisions to workflow
                            await self.provide_approval_decisions(decisions)
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


async def connect_hitl_workflow(config: HITLWorkflowConfig) -> None:
    """Connect to an existing human-in-the-loop investigation workflow.

    Args:
        config: Workflow configuration (must have workflow_id)
    """
    if not config.workflow_id:
        raise ValueError("Workflow ID is required to connect")

    try:
        console.print_header("Ein Agent - Interactive Investigation (Reconnecting)\n")

        # Connect to orchestrator
        orchestrator = await HITLOrchestrator.connect(
            config=config,
            workflow_id=config.workflow_id,
        )

        # Check status
        status = await orchestrator.get_status()
        if status in ["completed", "ended"]:
            console.print_warning(f"Workflow {config.workflow_id} is already {status}.")

        # Run interactive loop
        await orchestrator.run_interactive()

    except Exception as e:
        console.print_error(f"Error connecting to workflow: {e}")
        raise

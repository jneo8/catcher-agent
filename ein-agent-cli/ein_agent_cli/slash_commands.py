"""Implementation of interactive slash commands."""

import json
from abc import ABC, abstractmethod
from typing import Dict, Optional, Any

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from rich.prompt import Prompt, IntPrompt
from rich.table import Table
from temporalio.client import Client as TemporalClient

from ein_agent_cli import console
from ein_agent_cli.models import (
    AlertmanagerQueryParams,
    Context,
    ContextItem,
    ContextItemType,
    HumanInLoopConfig,
    LocalContext,
    SessionState,
    WorkflowAlert,
)
from ein_agent_cli.temporal import get_workflow_status, list_workflows
from ein_agent_cli.alertmanager import query_alertmanager
from ein_agent_cli.session_storage import generate_context_id



PASS_1_RCA_PROMPT = """You are an RCA analyst. Your task is to perform a root cause analysis for the given alert.

Here is the alert details:
{alert_details}
"""

class WorkflowCompleter(Completer):
    """Completer that provides auto-completion for workflow selection."""

    def __init__(self, workflows: list, current_workflow_id: Optional[str] = None):
        """Initialize the completer with workflow list.

        Args:
            workflows: List of workflow dictionaries.
            current_workflow_id: The currently active workflow ID.
        """
        self.workflows = workflows
        self.current_workflow_id = current_workflow_id

    def get_completions(self, document: Document, complete_event):
        """Generate completions for workflow selection.

        Args:
            document: The current document being edited.
            complete_event: The completion event.

        Yields:
            Completion objects for matching workflows.
        """
        text = document.text_before_cursor.lower()

        for wf in self.workflows:
            wf_id = wf.get("workflow_id", "")
            # Support both formats: Temporal workflows and local context workflows
            wf_type = wf.get("workflow_type") or wf.get("type", "")
            wf_status = wf.get("status", "")
            start_time = wf.get("start_time", "")

            # Create display text with metadata
            is_current = wf_id == self.current_workflow_id
            current_marker = " [CURRENT]" if is_current else ""

            # Different metadata for different workflow sources
            if start_time:
                display_meta = f"{wf_type} - Started: {start_time}{current_marker}"
            else:
                display_meta = f"{wf_type} - Status: {wf_status}{current_marker}"

            # Match on workflow ID
            if text in wf_id.lower():
                yield Completion(
                    text=wf_id,
                    start_position=-len(document.text_before_cursor),
                    display=wf_id,
                    display_meta=display_meta,
                )


class AlertCompleter(Completer):
    """Completer that provides auto-completion for alert selection."""

    def __init__(self, alerts: list):
        """Initialize the completer with alert list.

        Args:
            alerts: List of ContextItem objects containing alerts.
        """
        self.alerts = alerts

    def get_completions(self, document: Document, complete_event):
        """Generate completions for alert selection.

        Args:
            document: The current document being edited.
            complete_event: The completion event.

        Yields:
            Completion objects for matching alerts.
        """
        text = document.text_before_cursor.lower()

        for alert_item in self.alerts:
            alert_data = alert_item.data
            alert_name = alert_data.get("alertname", "unknown")
            fingerprint = alert_item.item_id
            status = alert_data.get("status", "unknown")

            # Create display text with metadata
            display_meta = f"{alert_name} - Status: {status}"

            # Match on fingerprint or alert name
            if text in fingerprint.lower() or text in alert_name.lower():
                yield Completion(
                    text=fingerprint,
                    start_position=-len(document.text_before_cursor),
                    display=fingerprint[:16] + "..." if len(fingerprint) > 16 else fingerprint,
                    display_meta=display_meta,
                )


class ContextCompleter(Completer):
    """Completer that provides auto-completion for context selection."""

    def __init__(self, contexts: list, current_context_id: Optional[str] = None):
        """Initialize the completer with context list.

        Args:
            contexts: List of Context objects.
            current_context_id: The currently active context ID.
        """
        self.contexts = contexts
        self.current_context_id = current_context_id

    def get_completions(self, document: Document, complete_event):
        """Generate completions for context selection.

        Args:
            document: The current document being edited.
            complete_event: The completion event.

        Yields:
            Completion objects for matching contexts.
        """
        text = document.text_before_cursor.lower()

        for ctx in self.contexts:
            context_id = ctx.context_id
            context_name = ctx.context_name or ""
            alert_count = len(ctx.local_context.items)
            workflow_count = len(ctx.local_context.get_all_workflows())

            # Create display text with metadata
            is_current = context_id == self.current_context_id
            current_marker = " [CURRENT]" if is_current else ""
            display_meta = f"{context_name} - {alert_count} alerts, {workflow_count} workflows{current_marker}"

            # Match on context ID or context name
            if text in context_id.lower() or (context_name and text in context_name.lower()):
                yield Completion(
                    text=context_id,
                    start_position=-len(document.text_before_cursor),
                    display=context_id,
                    display_meta=display_meta,
                )


class CommandResult:
    """Result of a command execution, signaling how the main loop should proceed."""
    def __init__(
        self,
        should_continue: bool = True,
        should_exit: bool = False,
        workflow_id: Optional[str] = None,
        should_switch: bool = False,
        should_create_new: bool = False,
        new_workflow_prompt: Optional[str] = None,
        should_complete: bool = False,
        should_reset: bool = False,
        workflow_type: Optional[str] = None,  # Type of workflow: RCA, EnrichmentRCA, CompactRCA, etc.
        alert_fingerprint: Optional[str] = None,  # Alert fingerprint for RCA/EnrichmentRCA workflows
        enrichment_context: Optional[Dict[str, Any]] = None,  # Context for enrichment workflows
        source_workflow_ids: Optional[list] = None,  # Source workflows for compact workflows
    ):
        self.should_continue = should_continue
        self.should_exit = should_exit
        self.workflow_id = workflow_id  # For backward compatibility and switching
        self.should_switch = should_switch  # Signal to switch to workflow_id
        self.should_create_new = should_create_new  # Signal to create new workflow
        self.new_workflow_prompt = new_workflow_prompt  # Task for new workflow
        self.should_complete = should_complete # Signal to complete the workflow
        self.workflow_type = workflow_type  # Type of workflow being created
        self.alert_fingerprint = alert_fingerprint  # Alert for RCA workflows
        self.enrichment_context = enrichment_context  # Context for enrichment
        self.source_workflow_ids = source_workflow_ids  # Sources for compact workflows


class SlashCommand(ABC):
    """Abstract base class for an interactive slash command."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """The name of the command (e.g., 'help')."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """A short description of the command."""
        pass
    
    @abstractmethod
    async def execute(self, args: str, config: HumanInLoopConfig, client: TemporalClient, session: SessionState) -> CommandResult:
        """
        Executes the command.

        Args:
            args: The arguments string passed to the command.
            config: The active human-in-the-loop configuration.
            client: The connected Temporal client.
            session: The current session state with workflow and context information.

        Returns:
            A CommandResult indicating the desired next state of the interactive loop.
        """
        pass


class HelpCommand(SlashCommand):
    """Displays available commands."""
    def __init__(self, registry: 'CommandRegistry'):
        self._registry = registry

    @property
    def name(self) -> str:
        return "help"
    
    @property
    def description(self) -> str:
        return "Show this help message"

    async def execute(self, args: str, config: HumanInLoopConfig, client: TemporalClient, session: SessionState) -> CommandResult:
        console.print_info("Available commands:")
        commands = sorted(self._registry.get_all(), key=lambda cmd: cmd.name)
        for cmd in commands:
            console.print_message(f"  /{cmd.name.ljust(25)}- {cmd.description}")
        return CommandResult()


class WorkflowsCommand(SlashCommand):
    """Manage workflows in local context with interactive filtering."""
    @property
    def name(self) -> str:
        return "workflows"

    @property
    def description(self) -> str:
        return "Manage workflows in local context"

    async def execute(self, args: str, config: HumanInLoopConfig, client: TemporalClient, session: SessionState) -> CommandResult:
        context = session.get_current_context()
        if not context:
            console.print_error("No active context.")
            return CommandResult()

        workflows = context.local_context.get_all_workflows()

        if not workflows:
            console.print_info("No workflows in local context.")
            console.print_info("Use /alerts to start RCA workflows for your alerts.")
            return CommandResult()

        # Interactive workflow management loop
        filters = {}
        while True:
            # Apply filters
            filtered_workflows = self._apply_filters(workflows, filters)

            # Display workflows
            console.print_newline()
            if filters:
                filter_str = ", ".join([f"{k}={v}" for k, v in filters.items()])
                console.print_header(f"Workflows in Local Context ({len(filtered_workflows)} matching filters: {filter_str})")
            else:
                console.print_header(f"Workflows in Local Context ({len(filtered_workflows)} total)")
            console.print_newline()

            if not filtered_workflows:
                console.print_info("No workflows match the current filters.")
                console.print_newline()
                console.print_info("Actions: (c)lear filter, (q)uit")
                action = Prompt.ask("Action", choices=["c", "q"], default="q")
                if action == "c":
                    filters = {}
                    continue
                else:
                    return CommandResult()

            # Display table
            self._display_workflows_table(filtered_workflows, context)

            # Show actions
            console.print_newline()
            console.print_info("Actions: (s)elect, (f)ilter, (c)lear filter, (q)uit")
            action = Prompt.ask("Action", choices=["s", "f", "c", "q"], default="q")

            if action == "s":
                # Select workflow
                result = await self._select_and_show_workflow(filtered_workflows, context, config, client, session)
                if result:
                    return result
                continue

            elif action == "f":
                # Add filter
                console.print_newline()
                console.print_info("Enter filters (e.g., type=RCA status=completed):")
                filter_input = Prompt.ask("Filters")
                filters = self._parse_filters(filter_input)
                continue

            elif action == "c":
                # Clear filters
                filters = {}
                continue

            elif action == "q":
                return CommandResult()

    def _apply_filters(self, workflows: list, filters: dict) -> list:
        """Apply filters to workflow list."""
        if not filters:
            return workflows

        filtered = workflows
        for key, value in filters.items():
            if key == "type":
                filtered = [w for w in filtered if w.get("type", "").lower() == value.lower()]
            elif key == "status":
                filtered = [w for w in filtered if w.get("status", "").lower() == value.lower()]
            elif key == "alert":
                # Filter by alert fingerprint or name
                filtered = [w for w in filtered if w.get("alert_fingerprint") and value.lower() in w.get("alert_fingerprint", "").lower()]

        return filtered

    def _parse_filters(self, filter_input: str) -> dict:
        """Parse filter input string into dict."""
        filters = {}
        if not filter_input or not filter_input.strip():
            return filters

        parts = filter_input.strip().split()
        for part in parts:
            if "=" in part:
                key, value = part.split("=", 1)
                filters[key.strip()] = value.strip()

        return filters

    def _display_workflows_table(self, workflows: list, context: Context):
        """Display workflows in a table."""
        table = Table("#", "Workflow ID", "Type", "Alert", "Status", show_header=True, header_style="bold magenta")

        for idx, wf in enumerate(workflows, 1):
            workflow_id = wf.get("workflow_id", "")
            workflow_type = wf.get("type", "")
            status = wf.get("status", "")

            # Get alert name if applicable
            alert_fingerprint = wf.get("alert_fingerprint")
            alert_name = "-"
            if alert_fingerprint:
                alert_item = context.local_context.get_item(alert_fingerprint)
                if alert_item:
                    alert_name = alert_item.data.get("alertname", alert_fingerprint[:12] + "...")
                else:
                    alert_name = alert_fingerprint[:12] + "..."

            # Truncate workflow ID for display
            display_id = workflow_id if len(workflow_id) <= 30 else workflow_id[:27] + "..."

            table.add_row(
                str(idx),
                display_id,
                workflow_type,
                alert_name,
                status
            )

        console.print_table(table)

    async def _select_and_show_workflow(self, workflows: list, context: Context, config: HumanInLoopConfig, client: TemporalClient, session: SessionState):
        """Prompt user to select a workflow and show details."""
        console.print_newline()
        try:
            # Create completer with workflow list
            completer = WorkflowCompleter(workflows, session.current_workflow_id)
            prompt_session = PromptSession(completer=completer)

            console.print_info("Select workflow by number or ID (with auto-completion):")
            user_input = await prompt_session.prompt_async("Workflow: ")

            if not user_input or not user_input.strip():
                console.print_info("Cancelled.")
                return None

            search_term = user_input.strip()
            selected_workflow = None

            # Try to parse as a number first
            try:
                choice = int(search_term)
                if 1 <= choice <= len(workflows):
                    selected_workflow = workflows[choice - 1]
            except ValueError:
                # Not a number, try to match by workflow ID
                for wf in workflows:
                    if wf.get("workflow_id") == search_term or search_term in wf.get("workflow_id", ""):
                        selected_workflow = wf
                        break

            if not selected_workflow:
                console.print_error(f"Workflow '{search_term}' not found.")
                return None

            # Show workflow details and action menu
            return await self._show_workflow_details(selected_workflow, context, config, client, session)

        except (KeyboardInterrupt, EOFError):
            return None

    async def _show_workflow_details(self, workflow: dict, context: Context, config: HumanInLoopConfig, client: TemporalClient, session: SessionState):
        """Display workflow details and action menu."""
        while True:
            console.print_newline()
            console.print_header("Workflow Details")
            console.print_newline()

            console.print_message(f"Workflow ID:       {workflow.get('workflow_id', '')}")
            console.print_message(f"Type:              {workflow.get('type', '')}")

            # Show alert info if applicable
            alert_fingerprint = workflow.get("alert_fingerprint")
            if alert_fingerprint:
                alert_item = context.local_context.get_item(alert_fingerprint)
                if alert_item:
                    alert_name = alert_item.data.get("alertname", "unknown")
                    console.print_message(f"Alert:             {alert_name} ({alert_fingerprint})")
                else:
                    console.print_message(f"Alert:             {alert_fingerprint}")

            console.print_message(f"Status:            {workflow.get('status', '')}")

            # Show result if available
            result = workflow.get("result")
            if result:
                console.print_newline()
                console.print_info("Result:")
                result_json = json.dumps(result, indent=2)
                # Show first 10 lines
                result_lines = result_json.split("\n")
                for line in result_lines[:10]:
                    console.print_message(line)
                if len(result_lines) > 10:
                    console.print_dim(f"... ({len(result_lines) - 10} more lines)")

            console.print_newline()
            console.print_info("Workflow Actions:")

            # Build action list with proper numbering
            action_handlers = []
            action_num = 1

            # Always: View full result
            console.print_message(f"  [{action_num}] View full result")
            action_handlers.append(("view_result", action_num))
            action_num += 1

            # Conditionally: Start enrichment RCA (only for completed RCA workflows)
            if workflow.get("type") == "RCA" and workflow.get("status") == "completed":
                console.print_message(f"  [{action_num}] Start enrichment RCA workflow (requires compact RCA)")
                action_handlers.append(("start_enrichment", action_num))
                action_num += 1

            # Always: Switch to workflow (if not already current)
            current_workflow = session.current_workflow_id
            if workflow.get("workflow_id") != current_workflow:
                console.print_message(f"  [{action_num}] Switch to this workflow")
                action_handlers.append(("switch", action_num))
                action_num += 1

            # Always: Remove workflow
            console.print_message(f"  [{action_num}] Remove workflow from context")
            action_handlers.append(("remove", action_num))
            action_num += 1

            # Always: Back to list
            console.print_message(f"  [{action_num}] Back to workflow list")
            action_handlers.append(("back", action_num))
            max_action = action_num

            console.print_newline()

            try:
                action_choice = IntPrompt.ask("Select action", default=max_action)

                # Find and execute the selected action
                for action_type, action_num in action_handlers:
                    if action_choice == action_num:
                        if action_type == "view_result":
                            # View full result
                            if result:
                                console.print_newline()
                                result_json = json.dumps(result, indent=2)
                                console.print_message(result_json)
                                console.print_newline()
                                Prompt.ask("Press Enter to continue")
                            else:
                                console.print_info("No result available.")
                            break

                        elif action_type == "start_enrichment":
                            # Start enrichment RCA
                            return await self._start_enrichment_rca(workflow, context, config, client, session)

                        elif action_type == "switch":
                            # Switch to this workflow
                            return CommandResult(should_switch=True, workflow_id=workflow.get("workflow_id"))

                        elif action_type == "remove":
                            # Remove workflow
                            confirm = Prompt.ask(f"Remove workflow '{workflow.get('workflow_id', '')}'?", choices=["y", "n"], default="n")
                            if confirm.lower() == "y":
                                context.local_context.remove_workflow(workflow.get("workflow_id", ""))
                                console.print_success("Workflow removed from context.")
                                return None
                            break

                        elif action_type == "back":
                            # Back to list
                            return None

                # If no action matched, continue the loop
                continue

            except (KeyboardInterrupt, EOFError):
                return None

    async def _start_enrichment_rca(self, rca_workflow: dict, context: Context, config: HumanInLoopConfig, client: TemporalClient, session: SessionState):
        """Start enrichment RCA workflow for the selected RCA."""
        console.print_newline()
        console.print_info("Checking requirements...")

        # Check if compact RCA exists
        if not context.local_context.compact_rca:
            console.print_error("Compact RCA not found in context")
            console.print_newline()
            console.print_info("You need to:")
            console.print_message("  1. Run /compact-rca to create compact RCA from all RCA workflows")
            console.print_message("  2. Wait for compact workflow to complete")
            console.print_message("  3. Then retry starting enrichment RCA")
            console.print_newline()
            Prompt.ask("Press Enter to continue")
            return None

        if context.local_context.compact_rca.status != "completed":
            console.print_error(f"Compact RCA is not completed (status: {context.local_context.compact_rca.status})")
            console.print_info("Wait for compact RCA to complete before starting enrichment RCA.")
            console.print_newline()
            Prompt.ask("Press Enter to continue")
            return None

        console.print_success(f"Found compact RCA: {context.local_context.compact_rca.workflow_id} (completed)")
        console.print_newline()

        # Get alert details
        alert_fingerprint = rca_workflow.get("alert_fingerprint")
        alert_item = context.local_context.get_item(alert_fingerprint)
        if not alert_item:
            console.print_error(f"Alert not found: {alert_fingerprint}")
            return None

        alert_name = alert_item.data.get("alertname", "unknown")
        console.print_info(f"Starting enrichment RCA for alert: {alert_name} ({alert_fingerprint})")
        console.print_newline()

        # Prepare enrichment context
        enrichment_context = {
            "compact_rca_id": context.local_context.compact_rca.workflow_id,
            "compact_summary": context.local_context.compact_rca.result,
            "source_workflows": context.local_context.compact_rca.source_workflow_ids,
        }

        # Build prompt
        alert_details = json.dumps(alert_item.data, indent=2)
        enrichment_context_str = json.dumps(enrichment_context, indent=2)

        prompt = f"""Perform enrichment RCA for this alert using compact RCA context.

Alert details:
{alert_details}

Enrichment context (from compact RCA):
{enrichment_context_str}
"""

        console.print_dim("Task: Perform enrichment RCA for this alert using compact RCA context")
        console.print_newline()

        # Return command result to create new workflow
        return CommandResult(
            should_create_new=True,
            new_workflow_prompt=prompt,
            workflow_type="EnrichmentRCA",
            alert_fingerprint=alert_fingerprint,
            enrichment_context=enrichment_context
        )


class RefreshCommand(SlashCommand):
    """Gets the latest status of the current workflow."""
    @property
    def name(self) -> str:
        return "refresh"
    
    @property
    def description(self) -> str:
        return "Get the latest workflow status"

    async def execute(self, args: str, config: HumanInLoopConfig, client: TemporalClient, session: SessionState) -> CommandResult:
        if not session.current_workflow_id:
            console.print_warning("No active workflow to refresh.")
            return CommandResult()

        console.print_info("Refreshing workflow status...")
        try:
            status = await get_workflow_status(client, session.current_workflow_id)
            console.print_success(f"State: {status.state}")
            if status.current_question:
                console.print_newline()
                console.print_message(status.current_question)
            if status.suggested_mcp_tools:
                console.print_dim(f"Suggested tools: {', '.join(status.suggested_mcp_tools)}")
        except Exception as e:
            console.print_error(f"Failed to refresh status: {e}")
        return CommandResult()


class CompleteCommand(SlashCommand):
    """Completes the current workflow."""
    @property
    def name(self) -> str:
        return "complete"

    @property
    def description(self) -> str:
        return "Complete the current workflow without exiting the CLI"

    async def execute(self, args: str, config: HumanInLoopConfig, client: TemporalClient, session: SessionState) -> CommandResult:
        if not session.current_workflow_id:
            console.print_warning("No active workflow to complete.")
            return CommandResult()

        return CommandResult(should_complete=True)


class EndCommand(SlashCommand):
    """Ends the current conversation and exits the CLI."""
    @property
    def name(self) -> str:
        return "end"

    @property
    def description(self) -> str:
        return "End the conversation and close the workflow"

    async def execute(self, args: str, config: HumanInLoopConfig, client: TemporalClient, session: SessionState) -> CommandResult:
        console.print_warning("Exiting.")
        return CommandResult(should_exit=True)


class SwitchCommand(SlashCommand):
    """Switch between connected workflows."""
    @property
    def name(self) -> str:
        return "switch"

    @property
    def description(self) -> str:
        return "Switch between workflows (shows running workflows with dropdown)"

    async def execute(self, args: str, config: HumanInLoopConfig, client: TemporalClient, session: SessionState) -> CommandResult:
        # Get list of all workflows
        workflows = await list_workflows(config.temporal)

        if not workflows:
            console.print_info("No workflows found.")
            return CommandResult()

        # Display workflow table
        console.print_info("Available workflows:")
        console.print_newline()
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Workflow ID", style="cyan")
        table.add_column("Type", style="green")
        table.add_column("Started", style="yellow")
        table.add_column("Status", style="blue")

        for wf in workflows:
            wf_id = wf.get("workflow_id", "N/A")
            wf_type = wf.get("workflow_type", "N/A")
            start_time = wf.get("start_time", "N/A")
            status_marker = "[CURRENT]" if wf_id == session.current_workflow_id else ""

            table.add_row(wf_id, wf_type, start_time, f"{wf.get('status', 'N/A')} {status_marker}")

        console.print_table(table)
        console.print_newline()

        # Create completer with workflow IDs
        completer = WorkflowCompleter(workflows, session.current_workflow_id)
        prompt_session = PromptSession(completer=completer)

        # Determine default workflow ID
        default_wf_id = session.current_workflow_id if session.current_workflow_id else workflows[0].get("workflow_id", "")

        console.print_info("Type or use Tab to select a workflow ID:")

        while True:
            try:
                selected_workflow_id = await prompt_session.prompt_async(
                    "Select workflow: ",
                    default=default_wf_id
                )

                # Strip whitespace
                selected_workflow_id = selected_workflow_id.strip()

                if not selected_workflow_id:
                    console.print_error("Workflow ID cannot be empty.")
                    continue

                # Check if workflow exists in list
                workflow_exists = any(wf.get("workflow_id") == selected_workflow_id for wf in workflows)
                if not workflow_exists:
                    console.print_error(f"Workflow '{selected_workflow_id}' not found in running workflows.")
                    console.print_dim("Hint: Use Tab to see available workflows")
                    continue

                if selected_workflow_id == session.current_workflow_id:
                    console.print_info("Already on this workflow.")
                    return CommandResult()

                # Verify the workflow is accessible
                try:
                    status = await get_workflow_status(client, selected_workflow_id)
                    console.print_success(f"✓ Switched to workflow: {selected_workflow_id}")
                    console.print_dim(f"Current state: {status.state}")
                    return CommandResult(should_switch=True, workflow_id=selected_workflow_id)
                except Exception as e:
                    console.print_error(f"Failed to switch to workflow: {e}")
                    return CommandResult()

            except KeyboardInterrupt:
                console.print_warning("Selection cancelled.")
                return CommandResult()
            except EOFError:
                console.print_warning("Selection cancelled.")
                return CommandResult()


class NewCommand(SlashCommand):
    """Create a new investigation context."""
    @property
    def name(self) -> str:
        return "new"

    @property
    def description(self) -> str:
        return "Create a new investigation context"

    async def execute(self, args: str, config: HumanInLoopConfig, client: TemporalClient, session: SessionState) -> CommandResult:
        # Parse optional context name from args
        context_name = args.strip() if args.strip() else None

        # Prompt for context name if not provided
        if not context_name:
            context_name = Prompt.ask("Context name (optional, press Enter to skip)", default="")
            if not context_name:
                context_name = None

        # Generate new context
        new_context = Context(
            context_id=generate_context_id(),
            context_name=context_name,
            local_context=LocalContext(),
        )

        # Add to session and switch to it
        session.add_context(new_context)

        console.print_newline()
        console.print_success(f"Created new context: {new_context.context_id}")
        if context_name:
            console.print_info(f"Name: {context_name}")
        console.print_info(f"Total contexts: {len(session.contexts)}")
        console.print_newline()

        return CommandResult()


class SwitchContextCommand(SlashCommand):
    """Switch to a different investigation context."""
    @property
    def name(self) -> str:
        return "switch-context"

    @property
    def description(self) -> str:
        return "Switch to a different investigation context"

    async def execute(self, args: str, config: HumanInLoopConfig, client: TemporalClient, session: SessionState) -> CommandResult:
        if len(session.contexts) == 0:
            console.print_error("No contexts available.")
            return CommandResult()

        if len(session.contexts) == 1:
            console.print_info("Only one context exists. Use /new to create more.")
            return CommandResult()

        console.print_newline()
        console.print_header("Available Contexts")
        console.print_newline()

        # Display contexts in a table
        table = Table("", "Context ID", "Name", "Alerts", "Workflows", show_header=True, header_style="bold magenta")

        contexts_list = list(session.contexts.values())
        for ctx in contexts_list:
            is_current = ctx.context_id == session.current_context_id
            marker = "*" if is_current else ""

            alert_count = len(ctx.local_context.items)
            workflow_count = len(ctx.local_context.get_all_workflows())

            display_name = ctx.context_name or "-"

            table.add_row(
                marker,
                ctx.context_id,
                display_name,
                str(alert_count),
                str(workflow_count)
            )

        console.print_table(table)
        console.print_dim("* = current context")
        console.print_newline()

        # Create prompt session with auto-completion
        completer = ContextCompleter(contexts_list, session.current_context_id)
        prompt_session = PromptSession(completer=completer)

        # Prompt for selection with auto-completion
        try:
            console.print_info("Select context by ID or name (with auto-completion):")
            user_input = await prompt_session.prompt_async("Context: ")

            if not user_input or not user_input.strip():
                console.print_info("Cancelled.")
                return CommandResult()

            # Try to find context by ID or name
            selected_context = None
            search_term = user_input.strip()

            # First try exact match on context_id
            if search_term in session.contexts:
                selected_context = session.contexts[search_term]
            else:
                # Try to match by name (case-insensitive)
                for ctx in contexts_list:
                    if ctx.context_name and ctx.context_name.lower() == search_term.lower():
                        selected_context = ctx
                        break

                # If still not found, try partial match on context_id
                if not selected_context:
                    for ctx in contexts_list:
                        if search_term.lower() in ctx.context_id.lower():
                            selected_context = ctx
                            break

            if not selected_context:
                console.print_error(f"Context '{search_term}' not found.")
                return CommandResult()

            if selected_context.context_id == session.current_context_id:
                console.print_info("Already in this context.")
                return CommandResult()

            # Switch context
            session.switch_context(selected_context.context_id)

            console.print_success(f"Switched to context: {selected_context.context_id}")
            if selected_context.context_name:
                console.print_info(f"Name: {selected_context.context_name}")
            console.print_newline()

            return CommandResult()

        except (KeyboardInterrupt, EOFError):
            console.print_warning("Cancelled.")
            return CommandResult()


class ImportAlertsCommand(SlashCommand):
    """Import alerts from AlertManager to local context."""

    @property
    def name(self) -> str:
        return "import-alerts"

    @property
    def description(self) -> str:
        return "Query AlertManager and import alerts to local context"

    async def execute(self, args: str, config: HumanInLoopConfig, client: TemporalClient, session: SessionState) -> CommandResult:
        # Parse command arguments for initial filters
        import_args = self._parse_args(args)

        # Determine AlertManager URL
        alertmanager_url = import_args.get("url") or config.alertmanager_url or "http://localhost:9093"

        console.print_info(f"Querying AlertManager at {alertmanager_url}...")

        try:
            # Query AlertManager
            query_params = AlertmanagerQueryParams(url=alertmanager_url)
            all_alerts = await query_alertmanager(query_params)

            if not all_alerts:
                console.print_info("No alerts found.")
                return CommandResult()

            # Start interactive import loop
            await self._interactive_import_loop(all_alerts, import_args, alertmanager_url, session)

            return CommandResult()

        except Exception as e:
            console.print_error(f"Failed to import alerts: {e}")
            return CommandResult()

    async def _interactive_import_loop(self, all_alerts, import_args, alertmanager_url, session):
        """Interactive loop for filtering and importing alerts."""
        selected_indices = set()
        
        while True:
            # Get fingerprints of alerts already in context
            context_alerts = session.local_context.get_items_by_type(ContextItemType.ALERT)
            
            # Display context alerts
            if context_alerts:
                self._display_context_alerts_table(context_alerts)

            # Filter out alerts that are already in the context
            context_fingerprints = {item.item_id for item in context_alerts}
            new_alerts = [alert for alert in all_alerts if alert.fingerprint not in context_fingerprints]
            
            # Apply filters
            filtered_alerts = self._filter_alerts(new_alerts, import_args)

            if not filtered_alerts:
                console.print_info("No new alerts matched the filters.")
                # Prompt to clear filters if any are active
                if any(v is not None for k, v in import_args.items() if k != 'status'):
                    if await self._prompt_for_clear_filters():
                        import_args = self._parse_args("") # Reset to defaults
                        continue
                return


            self._display_alerts_table(filtered_alerts, selected_indices)

            # Prompt for action
            action = await self._prompt_for_action()

            if not action:
                continue

            action_cmd = action.lower().split()[0]
            action_args = action.split()[1:] if len(action.split()) > 1 else []

            if action_cmd == 'i':
                if not selected_indices:
                    console.print_warning("No alerts selected. Use 's' to select alerts first.")
                    continue
                
                alerts_to_import = [filtered_alerts[i] for i in sorted(list(selected_indices))]
                self._import_alerts(alerts_to_import, alertmanager_url, session)
                
                # Remove imported alerts from the list
                imported_fingerprints = {alert.fingerprint for alert in alerts_to_import}
                all_alerts = [alert for alert in all_alerts if alert.fingerprint not in imported_fingerprints]
                selected_indices.clear()
            
            elif action_cmd == 'a':
                self._import_alerts(filtered_alerts, alertmanager_url, session)
                
                # Remove all currently filtered alerts from the list
                imported_fingerprints = {alert.fingerprint for alert in filtered_alerts}
                all_alerts = [alert for alert in all_alerts if alert.fingerprint not in imported_fingerprints]
                selected_indices.clear()

            elif action_cmd == 's':
                if action_args:
                    self._handle_selection(action_args[0], filtered_alerts, selected_indices)
                else:
                    console.print_warning("Usage: s <numbers/ranges> (e.g., s 1,2,5-7)")

            elif action_cmd == 'f':
                new_filters = await self._prompt_for_filters()
                import_args.update(new_filters)
                selected_indices.clear()

            elif action_cmd == 'c':
                import_args = self._parse_args("")
                selected_indices.clear()
                console.print_info("Filters cleared.")

            elif action_cmd == 'q':
                break

    def _filter_alerts(self, alerts, filters):
        """Filter alerts based on a dictionary of filters."""
        filtered_alerts = []
        
        for alert in alerts:
            # Status filter
            status_filter = filters.get("status")
            if status_filter and status_filter != "all" and alert.status.state != status_filter:
                continue

            # Whitelist filter (alert name)
            whitelist = filters.get("include")
            if whitelist and not any(w.lower() in alert.labels.get("alertname", "").lower() for w in whitelist):
                continue
            
            # Severity filter
            severity_filter = filters.get("severity")
            if severity_filter and severity_filter.lower() not in alert.labels.get("severity", "").lower():
                continue

            # Fingerprint filter
            fingerprint_filter = filters.get("fingerprint")
            if fingerprint_filter and fingerprint_filter.lower() not in alert.fingerprint.lower():
                continue

            filtered_alerts.append(alert)
            
        return filtered_alerts

    def _display_context_alerts_table(self, alerts):
        """Display alerts already in the local context."""
        table = Table(title="Alerts in Local Context", show_header=True, header_style="bold blue")
        table.add_column("Alert Name", style="cyan")
        table.add_column("Status", style="yellow")
        table.add_column("Severity", style="red")
        table.add_column("Fingerprint", style="green")

        for alert_item in alerts:
            alert_data = alert_item.data
            alert_name = alert_data.get("alertname", "unknown")
            status = alert_data.get("status", "unknown")
            severity = alert_data.get("labels", {}).get("severity", "-")
            fingerprint = alert_item.item_id[:12] + "..." if len(alert_item.item_id) > 12 else alert_item.item_id
            table.add_row(alert_name, status, severity, fingerprint)
        
        console.print_table(table)
        console.print_newline()

    def _display_alerts_table(self, alerts, selected_indices):
        """Display alerts in a table with selection and context markers."""
        table = Table(title="New Alerts from AlertManager", show_header=True, header_style="bold magenta")
        table.add_column(" ", style="dim")
        table.add_column("#", style="dim")
        table.add_column("Alert Name", style="cyan")
        table.add_column("Status", style="yellow")
        table.add_column("Severity", style="red")
        table.add_column("Fingerprint", style="green")

        for idx, alert in enumerate(alerts, 1):
            selected = "x" if idx - 1 in selected_indices else " "
            alert_name = alert.labels.get("alertname", "unknown")
            status = alert.status.state
            severity = alert.labels.get("severity", "-")
            fingerprint = alert.fingerprint[:12] + "..." if len(alert.fingerprint) > 12 else alert.fingerprint

            table.add_row(f"({selected})", str(idx), alert_name, status, severity, fingerprint)

        console.print_table(table)

    async def _prompt_for_action(self):
        """Prompt user for action."""
        console.print_info("Actions: (s)elect, (i)mport, (a)ll, (f)ilter, (c)lear filter, (q)uit")
        session = PromptSession()
        return await session.prompt_async("Action: ")

    async def _prompt_for_filters(self):
        """Prompt user for key-value filters."""
        session = PromptSession()
        console.print_info("Enter filters (e.g., name=KubePod status=active severity=warning):")
        filter_str = await session.prompt_async("Filters: ")
        filters = {}
        for part in filter_str.split():
            if "=" in part:
                key, value = part.split("=", 1)
                key = key.lower()
                if key in ["name", "include"]:
                    filters["include"] = filters.get("include", []) + [value]
                else:
                    filters[key] = value
        return filters

    async def _prompt_for_clear_filters(self) -> bool:
        """Ask user if they want to clear active filters."""
        session = PromptSession()
        response = await session.prompt_async("No results. Clear all filters and try again? (y/n): ")
        return response.lower() == 'y'

    def _handle_selection(self, selection_str, alerts, selected_indices):
        """Handle user selection of alerts."""
        try:
            for part in selection_str.split(','):
                part = part.strip()
                if '-' in part:
                    start, end = map(int, part.split('-'))
                    for i in range(start - 1, end):
                        if 0 <= i < len(alerts):
                            if i in selected_indices:
                                selected_indices.remove(i)
                            else:
                                selected_indices.add(i)
                else:
                    i = int(part) - 1
                    if 0 <= i < len(alerts):
                        if i in selected_indices:
                            selected_indices.remove(i)
                        else:
                            selected_indices.add(i)
        except ValueError:
            console.print_error("Invalid selection. Use numbers and ranges (e.g., 1,2,5-7).")

    def _import_alerts(self, alerts_to_import, alertmanager_url, session):
        """Import selected alerts into the local context."""
        imported_count = 0
        for alert in alerts_to_import:
            workflow_alert = WorkflowAlert.from_alertmanager_alert(alert)
            item = ContextItem(
                item_id=alert.fingerprint or f"alert-{imported_count}",
                item_type=ContextItemType.ALERT,
                data=workflow_alert.model_dump(),
                source=alertmanager_url,
            )
            session.local_context.add_item(item)
            imported_count += 1

        console.print_success(f"Imported {imported_count} alert(s) to local context")
        console.print_dim(f"Total alerts in local context: {session.local_context.count()}")

    def _parse_args(self, args: str) -> Dict[str, Any]:
        """Parse command arguments.

        Supported format:
            -a URL --alertmanager-url URL
            -i ALERT --include ALERT (can be repeated)
            --status STATUS

        Returns:
            Dict with parsed arguments
        """
        result = {
            "url": None,
            "include": None,
            "status": "active",  # default
        }

        if not args.strip():
            return result

        # Simple argument parsing
        parts = args.split()
        i = 0
        include_list = []

        while i < len(parts):
            part = parts[i]

            if part in ["-a", "--alertmanager-url"]:
                if i + 1 < len(parts):
                    result["url"] = parts[i + 1]
                    i += 2
                else:
                    i += 1

            elif part in ["-i", "--include"]:
                if i + 1 < len(parts):
                    include_list.append(parts[i + 1])
                    i += 2
                else:
                    i += 1

            elif part == "--status":
                if i + 1 < len(parts):
                    result["status"] = parts[i + 1].lower()
                    i += 2
                else:
                    i += 1

            else:
                i += 1

        # Set lists if provided
        if include_list:
            result["include"] = include_list

        return result


class AlertsCommand(SlashCommand):
    """List and manage locally stored alerts."""

    @property
    def name(self) -> str:
        return "alerts"

    @property
    def description(self) -> str:
        return "List and manage locally stored alerts"

    async def execute(self, args: str, config: HumanInLoopConfig, client: TemporalClient, session: SessionState) -> CommandResult:
        # Get alerts from local context
        all_alerts = session.local_context.get_items_by_type(ContextItemType.ALERT)

        if not all_alerts:
            console.print_info("No alerts in local context. Use /import-alerts to import alerts.")
            return CommandResult()

        # Interactive alert management loop with filtering
        filters = {}
        while True:
            # Apply filters
            filtered_alerts = self._apply_alert_filters(all_alerts, filters)

            # Display alerts table
            console.print_newline()
            if filters:
                filter_str = ", ".join([f"{k}={v}" for k, v in filters.items()])
                console.print_header(f"Alerts in Local Context ({len(filtered_alerts)} matching filters: {filter_str})")
            else:
                console.print_header(f"Alerts in Local Context ({len(filtered_alerts)} total)")
            console.print_newline()

            if not filtered_alerts:
                console.print_info("No alerts match the current filters.")
                console.print_newline()
                console.print_info("Actions: (c)lear filter, (q)uit")
                action = Prompt.ask("Action", choices=["c", "q"], default="q")
                if action == "c":
                    filters = {}
                    continue
                else:
                    return CommandResult()

            # Display table
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("#", style="dim")
            table.add_column("Alert Name", style="cyan")
            table.add_column("Status", style="yellow")
            table.add_column("Severity", style="red")
            table.add_column("Workflows", style="green")
            table.add_column("Fingerprint", style="dim")

            for idx, item in enumerate(filtered_alerts, 1):
                alert_data = item.data
                alert_name = alert_data.get("alertname", "unknown")
                status = alert_data.get("status", "unknown")
                severity = alert_data.get("labels", {}).get("severity", "-")
                fingerprint = item.item_id[:12] + "..." if len(item.item_id) > 12 else item.item_id

                # Get related workflows
                workflows_info = self._get_workflows_for_alert(item.item_id, session)

                table.add_row(str(idx), alert_name, status, severity, workflows_info, fingerprint)

            console.print_table(table)
            console.print_newline()

            # Show actions
            console.print_info("Actions: (s)elect, (f)ilter, (c)lear filter, (q)uit")
            action = Prompt.ask("Action", choices=["s", "f", "c", "q"], default="q")

            if action == "s":
                # Select alert
                result = await self._select_and_show_alert(filtered_alerts, session)
                if result:
                    return result
                # Refresh alert list after selection
                all_alerts = session.local_context.get_items_by_type(ContextItemType.ALERT)
                if not all_alerts:
                    console.print_info("No more alerts in local context.")
                    return CommandResult()
                continue

            elif action == "f":
                # Add filter
                console.print_newline()
                console.print_info("Enter filters (e.g., name=KubePod status=firing severity=critical):")
                filter_input = Prompt.ask("Filters")
                filters = self._parse_alert_filters(filter_input)
                continue

            elif action == "c":
                # Clear filters
                filters = {}
                continue

            elif action == "q":
                return CommandResult()

    def _apply_alert_filters(self, alerts: list, filters: dict) -> list:
        """Apply filters to alert list."""
        if not filters:
            return alerts

        filtered = alerts
        for key, value in filters.items():
            if key == "name":
                filtered = [a for a in filtered if value.lower() in a.data.get("alertname", "").lower()]
            elif key == "status":
                filtered = [a for a in filtered if a.data.get("status", "").lower() == value.lower()]
            elif key == "severity":
                filtered = [a for a in filtered if a.data.get("labels", {}).get("severity", "").lower() == value.lower()]

        return filtered

    def _parse_alert_filters(self, filter_input: str) -> dict:
        """Parse filter input string into dict."""
        filters = {}
        if not filter_input or not filter_input.strip():
            return filters

        parts = filter_input.strip().split()
        for part in parts:
            if "=" in part:
                key, value = part.split("=", 1)
                filters[key.strip()] = value.strip()

        return filters

    def _get_workflows_for_alert(self, alert_fingerprint: str, session: SessionState) -> str:
        """Get workflow status for a specific alert.

        Returns:
            String describing workflows (e.g., "RCA: completed" or "RCA: running, EnrichRCA: completed")
        """
        context = session.get_current_context()
        if not context:
            return "-"

        local_ctx = context.local_context
        workflow_parts = []

        # Check for RCA workflow
        rca = local_ctx.get_rca_for_alert(alert_fingerprint)
        if rca:
            workflow_parts.append(f"RCA: {rca.status}")

        # Check for Enrichment RCA workflow
        enrichment = local_ctx.get_enrichment_rca_for_alert(alert_fingerprint)
        if enrichment:
            workflow_parts.append(f"EnrichRCA: {enrichment.status}")

        return ", ".join(workflow_parts) if workflow_parts else "-"

    async def _select_and_show_alert(self, alerts: list, session: SessionState):
        """Prompt user to select an alert and show details."""
        console.print_newline()
        try:
            # Create completer with alert items
            completer = AlertCompleter(alerts)
            prompt_session = PromptSession(completer=completer)

            console.print_info("Select alert by number or fingerprint (with auto-completion):")
            user_input = await prompt_session.prompt_async("Alert: ")

            if not user_input or not user_input.strip():
                console.print_info("Cancelled.")
                return None

            search_term = user_input.strip()
            selected_item = None

            # Try to parse as a number first
            try:
                idx = int(search_term)
                if 1 <= idx <= len(alerts):
                    selected_item = alerts[idx - 1]
            except ValueError:
                # Try to find by fingerprint
                for item in alerts:
                    if item.item_id == search_term or search_term in item.item_id:
                        selected_item = item
                        break

            if not selected_item:
                console.print_error(f"Alert '{search_term}' not found.")
                return None

            # Show action menu
            action_result = await self._show_action_menu(selected_item, session)

            if isinstance(action_result, CommandResult):
                # This means a new workflow should be started
                return action_result

            # action_result is "back" or "quit"
            return None

        except (KeyboardInterrupt, EOFError):
            return None

    async def _show_action_menu(self, alert_item: ContextItem, session: SessionState) -> Any:
        """Show action menu for selected alert.

        Args:
            alert_item: The selected alert context item
            session: The session state

        Returns:
            Action result: "back", "quit", or a CommandResult object
        """
        while True:
            console.print_newline()
            console.print_info("Alert Actions:")
            console.print_message("  [1] View Details")
            console.print_message("  [2] Remove from context")
            console.print_message("  [3] Start RCA workflow")
            console.print_message("  [4] Back to alert list")
            console.print_newline()

            try:
                choice = IntPrompt.ask("Select action", default=1)

                if choice == 1:
                    # View details
                    self._view_alert_details(alert_item)
                    # Show menu again
                    continue

                elif choice == 2:
                    # Remove alert
                    alert_data = alert_item.data
                    alert_name = alert_data.get("labels", {}).get("alertname", "unknown")

                    confirm = Prompt.ask(f"Remove alert '{alert_name}'?", choices=["y", "n"], default="n")
                    if confirm.lower() == "y":
                        session.local_context.remove_item(alert_item.item_id)
                        console.print_success(f"Removed alert '{alert_name}' from context")
                        return "back"
                    else:
                        console.print_info("Cancelled")
                        continue
                
                elif choice == 3:
                    # Start RCA workflow
                    alert_details = json.dumps(alert_item.data, indent=2)
                    prompt = PASS_1_RCA_PROMPT.format(
                        alert_details=alert_details
                    )
                    return CommandResult(
                        should_create_new=True,
                        new_workflow_prompt=prompt,
                        workflow_type="RCA",
                        alert_fingerprint=alert_item.item_id
                    )

                elif choice == 4:
                    # Back to list
                    return "back"

                else:
                    console.print_error("Invalid choice. Please select 1, 2, 3 or 4.")
                    continue

            except (KeyboardInterrupt, EOFError):
                return "quit"

    def _view_alert_details(self, alert_item: ContextItem) -> None:
        """Display full alert details.

        Args:
            alert_item: The alert context item
        """
        console.print_newline()
        console.print_info("Alert Details:")
        console.print_newline()

        # Display as formatted JSON
        alert_json = json.dumps(alert_item.data, indent=2)
        console.print_message(alert_json)

        console.print_newline()
        if alert_item.source:
            console.print_dim(f"Source: {alert_item.source}")
        console.print_newline()


class CompactRCACommand(SlashCommand):
    """Compact all completed RCA workflows into summary."""

    @property
    def name(self) -> str:
        return "compact-rca"

    @property
    def description(self) -> str:
        return "Compact all completed RCA workflows into summary"

    async def execute(self, args: str, config: HumanInLoopConfig, client: TemporalClient, session: SessionState) -> CommandResult:
        context = session.get_current_context()
        if not context:
            console.print_error("No active context.")
            return CommandResult()

        console.print_newline()
        console.print_info("Checking RCA workflows...")

        # Get all completed RCA workflows
        completed_rcas = context.local_context.get_completed_rca_workflows()

        if not completed_rcas:
            console.print_error("No completed RCA workflows found in context.")
            console.print_info("Use /alerts to start RCA workflows for your alerts first.")
            return CommandResult()

        console.print_success(f"Found {len(completed_rcas)} completed RCA workflow(s):")

        # Display list of RCA workflows
        for rca in completed_rcas:
            alert_fingerprint = rca.alert_fingerprint
            alert_name = "unknown"
            if alert_fingerprint:
                alert_item = context.local_context.get_item(alert_fingerprint)
                if alert_item:
                    alert_name = alert_item.data.get("alertname", alert_fingerprint)

            console.print_message(f"- {rca.workflow_id} ({alert_name})")

        console.print_newline()

        # Ask for confirmation
        confirm = Prompt.ask(f"Create compact RCA from {len(completed_rcas)} workflows?", choices=["y", "n"], default="y")

        if confirm.lower() != "y":
            console.print_info("Cancelled.")
            return CommandResult()

        console.print_newline()
        console.print_info("Starting compact RCA workflow...")

        # Prepare compact context
        rca_results = []
        source_workflow_ids = []

        for rca in completed_rcas:
            source_workflow_ids.append(rca.workflow_id)
            if rca.result:
                rca_results.append({
                    "workflow_id": rca.workflow_id,
                    "alert_fingerprint": rca.alert_fingerprint,
                    "result": rca.result
                })

        # Build prompt for compact RCA workflow
        rca_results_json = json.dumps(rca_results, indent=2)

        prompt = f"""You are a summarization analyst. Your task is to analyze multiple RCA (Root Cause Analysis) outputs and create a compact summary.

You will be analyzing {len(completed_rcas)} RCA workflows.

RCA Results:
{rca_results_json}

Your task:
1. Analyze all RCA outputs
2. Identify common patterns and themes
3. Group related issues
4. Create a compact summary that captures:
   - Key findings across all RCAs
   - Common root causes
   - Patterns in failures
   - Recommended remediation strategies

The compact summary should be concise but comprehensive, suitable for use as context in enrichment RCA workflows.
"""

        console.print_dim("This workflow will:")
        console.print_message(f"- Analyze all {len(completed_rcas)} RCA outputs")
        console.print_message("- Identify common patterns")
        console.print_message("- Create compact summary")
        console.print_message("- Store result in local context")
        console.print_newline()
        console.print_info("Use /workflows to monitor progress.")
        console.print_info("Once completed, you can run /start-enrichment-rca-workflows")
        console.print_newline()

        # Return command result to create the compact RCA workflow
        return CommandResult(
            should_create_new=True,
            new_workflow_prompt=prompt,
            workflow_type="CompactRCA",
            source_workflow_ids=source_workflow_ids
        )


class ContextCommand(SlashCommand):
    """Show local context summary."""

    @property
    def name(self) -> str:
        return "context"

    @property
    def description(self) -> str:
        return "Show context summary"

    async def execute(self, args: str, config: HumanInLoopConfig, client: TemporalClient, session: SessionState) -> CommandResult:
        """Display summary of local context."""
        console.print_newline()
        console.print_header("Local Context Summary")
        console.print_newline()

        context = session.local_context

        # Count alerts
        alert_count = len(context.items)
        firing_count = sum(1 for item in context.items.values() if item.data.get("status") == "firing")
        resolved_count = sum(1 for item in context.items.values() if item.data.get("status") == "resolved")

        # Count workflows by type and status
        rca_total = len(context.rca_workflows)
        rca_completed = sum(1 for w in context.rca_workflows.values() if w.status == "completed")
        rca_running = sum(1 for w in context.rca_workflows.values() if w.status == "running")

        enrichment_total = len(context.enrichment_rca_workflows)
        enrichment_completed = sum(1 for w in context.enrichment_rca_workflows.values() if w.status == "completed")
        enrichment_running = sum(1 for w in context.enrichment_rca_workflows.values() if w.status == "running")

        # Total workflows
        total_workflows = rca_total + enrichment_total
        if context.compact_rca:
            total_workflows += 1
        if context.compact_enrichment_rca:
            total_workflows += 1
        if context.incident_summary:
            total_workflows += 1

        # Display summary
        console.print_message(f"Alerts:               {alert_count} ({firing_count} firing, {resolved_count} resolved)")
        console.print_message(f"Workflows:            {total_workflows} total")
        console.print_message(f"  - RCA:              {rca_total} ({rca_completed} completed, {rca_running} running)")
        console.print_message(f"  - EnrichmentRCA:    {enrichment_total} ({enrichment_completed} completed, {enrichment_running} running)")

        # Compact outputs
        compact_count = 0
        if context.compact_rca:
            compact_count += 1
        if context.compact_enrichment_rca:
            compact_count += 1
        if compact_count > 0:
            compact_types = []
            if context.compact_rca:
                compact_types.append("CompactRCA")
            if context.compact_enrichment_rca:
                compact_types.append("CompactEnrichmentRCA")
            console.print_message(f"Compact Outputs:      {compact_count} ({', '.join(compact_types)})")

        console.print_newline()

        return CommandResult()


class CommandRegistry:
    """A registry for slash commands."""
    def __init__(self):
        self._commands: Dict[str, SlashCommand] = {}
        # The help command needs a reference to the registry itself
        self.register(HelpCommand(self))

    def register(self, command: SlashCommand):
        """Registers a command."""
        self._commands[command.name] = command

    def find(self, name: str) -> Optional[SlashCommand]:
        """Finds a command by its name."""
        return self._commands.get(name)
    
    def get_all(self) -> list[SlashCommand]:
        """Returns a list of all registered commands."""
        return list(self._commands.values())


async def handle_command(
    user_input: str,
    registry: CommandRegistry,
    config: HumanInLoopConfig,
    client: TemporalClient,
    session: SessionState
) -> CommandResult:
    """
    Parses and executes a slash command from user input.

    Args:
        user_input: The raw string from the user.
        registry: The command registry.
        config: The active human-in-the-loop configuration.
        client: The connected Temporal client.
        session: The current session state with workflow and context information.

    Returns:
        The result of the command execution.
    """
    if not user_input.startswith('/'):
        return CommandResult(should_continue=False) # Not a command, probably a text response

    parts = user_input.strip()[1:].split(' ', 1)
    command_name = parts[0]
    args = parts[1] if len(parts) > 1 else ""

    command = registry.find(command_name)
    if not command:
        console.print_error(f"Unknown command: /{command_name}")
        return CommandResult()

    return await command.execute(args, config, client, session)

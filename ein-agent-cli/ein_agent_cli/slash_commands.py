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
    ContextItem,
    ContextItemType,
    HumanInLoopConfig,
    SessionState,
    WorkflowAlert,
)
from ein_agent_cli.temporal import get_workflow_status, list_workflows
from ein_agent_cli.alertmanager import query_alertmanager



PASS_1_RCA_PROMPT = """You are an RCA analyst. Your task is to perform a root cause analysis for the given alert.

Here is the alert details:
{alert_details}
"""

class WorkflowCompleter(Completer):
    """Completer that provides auto-completion for workflow selection."""

    def __init__(self, workflows: list, current_workflow_id: Optional[str] = None):
        """Initialize the completer with workflow list.

        Args:
            workflows: List of workflow dictionaries from list_workflows().
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
            wf_type = wf.get("workflow_type", "")
            start_time = wf.get("start_time", "")

            # Create display text with metadata
            is_current = wf_id == self.current_workflow_id
            current_marker = " [CURRENT]" if is_current else ""
            display_meta = f"{wf_type} - Started: {start_time}{current_marker}"

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
    ):
        self.should_continue = should_continue
        self.should_exit = should_exit
        self.workflow_id = workflow_id  # For backward compatibility and switching
        self.should_switch = should_switch  # Signal to switch to workflow_id
        self.should_create_new = should_create_new  # Signal to create new workflow
        self.new_workflow_prompt = new_workflow_prompt  # Task for new workflow
        self.should_complete = should_complete # Signal to complete the workflow


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
    """Lists workflows, with an option to filter by status."""
    @property
    def name(self) -> str:
        return "workflows"

    @property
    def description(self) -> str:
        return "List workflows, with an option to filter by status"

    async def execute(self, args: str, config: HumanInLoopConfig, client: TemporalClient, session: SessionState) -> CommandResult:

        status_filter = args.strip().capitalize()
        valid_statuses = ["Running", "Active", "Completed", "Failed", "Canceled", "Terminated", "TimedOut", "All"]

        if status_filter not in valid_statuses:
            console.print_info("Select a workflow status to filter by:")
            for i, status in enumerate(valid_statuses):
                console.print_message(f"  [{i+1}] {status}")

            while True:
                try:
                    choice = IntPrompt.ask("Enter selection", default=1)
                    if 1 <= choice <= len(valid_statuses):
                        status_filter = valid_statuses[choice - 1]
                        break
                    else:
                        console.print_error(f"Please enter a number between 1 and {len(valid_statuses)}.")
                except (ValueError, TypeError):
                     console.print_error("Invalid input. Please enter a number.")

        title = f"{status_filter} Temporal Workflows" if status_filter.lower() != 'all' else "All Temporal Workflows"

        workflows = await list_workflows(config.temporal, status_filter)
        if not workflows:
            console.print_info(f"No {status_filter.lower()} workflows found.")
            return CommandResult()

        table = Table(
            "Workflow ID", "Workflow Type", "Start Time", "Status", "Task Queue",
            title=title, show_header=True, header_style="bold magenta"
        )
        for wf in workflows:
            table.add_row(
                wf.get("workflow_id", "N/A"), wf.get("workflow_type", "N/A"),
                wf.get("start_time", "N/A"), wf.get("status", "N/A"),
                wf.get("task_queue", "N/A")
            )
        console.print_table(table)
        return CommandResult()


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
    """Create a new workflow."""
    @property
    def name(self) -> str:
        return "new"

    @property
    def description(self) -> str:
        return "Create a new workflow and start a conversation"

    async def execute(self, args: str, config: HumanInLoopConfig, client: TemporalClient, session: SessionState) -> CommandResult:
        # Check if args contains the task prompt
        task_prompt = args.strip()

        if not task_prompt:
            # Prompt user for task description
            console.print_info("What would you like the agent to help you with?")
            task_prompt = Prompt.ask("Task")

            if not task_prompt or not task_prompt.strip():
                console.print_error("Task description cannot be empty.")
                return CommandResult()

        console.print_info(f"Creating new workflow with task: {task_prompt}")
        return CommandResult(should_create_new=True, new_workflow_prompt=task_prompt)


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
        alert_items = session.local_context.get_items_by_type(ContextItemType.ALERT)

        if not alert_items:
            console.print_info("No alerts in local context. Use /import-alerts to import alerts.")
            return CommandResult()

        # Main loop for alert management
        while True:
            # Display alerts table
            console.print_newline()
            console.print_info(f"Local Context Alerts ({len(alert_items)} total)")
            console.print_newline()

            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("#", style="dim")
            table.add_column("Alert Name", style="cyan")
            table.add_column("Status", style="yellow")
            table.add_column("Severity", style="red")
            table.add_column("Imported At", style="green")
            table.add_column("Fingerprint", style="dim")

            for idx, item in enumerate(alert_items, 1):
                alert_data = item.data
                alert_name = alert_data.get("alertname", "unknown")
                status = alert_data.get("status", "unknown")
                severity = alert_data.get("labels", {}).get("severity", "-")
                imported_at = item.imported_at[:19] if len(item.imported_at) > 19 else item.imported_at
                fingerprint = item.item_id[:12] + "..." if len(item.item_id) > 12 else item.item_id

                table.add_row(str(idx), alert_name, status, severity, imported_at, fingerprint)

            console.print_table(table)
            console.print_newline()

            # Prompt for selection
            console.print_info("Select an alert by number or fingerprint (or 'q' to quit):")

            try:
                # Create completer with alert items
                completer = AlertCompleter(alert_items)
                prompt_session = PromptSession(completer=completer)

                selection = await prompt_session.prompt_async("Select alert: ")
                selection = selection.strip()

                if selection.lower() in ["q", "quit", "exit", ""]:
                    return CommandResult()

                # Find selected alert (by number or fingerprint)
                selected_item = None

                # Try to parse as number
                try:
                    idx = int(selection)
                    if 1 <= idx <= len(alert_items):
                        selected_item = alert_items[idx - 1]
                except ValueError:
                    # Try to find by fingerprint
                    for item in alert_items:
                        if item.item_id.startswith(selection) or selection in item.item_id:
                            selected_item = item
                            break

                if not selected_item:
                    console.print_error(f"Invalid selection: {selection}")
                    continue

                # Show action menu
                action_result = await self._show_action_menu(selected_item, session)

                if isinstance(action_result, CommandResult):
                    # This means a new workflow should be started
                    return action_result

                if action_result == "back":
                    # Refresh alert list
                    alert_items = session.local_context.get_items_by_type(ContextItemType.ALERT)
                    if not alert_items:
                        console.print_info("No more alerts in local context.")
                        return CommandResult()
                    continue
                elif action_result == "quit":
                    return CommandResult()

            except (KeyboardInterrupt, EOFError):
                console.print_warning("Cancelled.")
                return CommandResult()

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
                    return CommandResult(should_create_new=True, new_workflow_prompt=prompt)

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
        console.print_dim(f"Source: {alert_item.source}")
        console.print_dim(f"Imported at: {alert_item.imported_at}")
        console.print_newline()


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

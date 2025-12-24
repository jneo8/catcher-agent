"""Auto-completion support for InteractiveList component."""

from typing import Iterable, Optional

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document

from ein_agent_cli.models import AlertmanagerAlert


class ImportAlertsCompleter(Completer):
    """Completer for selecting alerts to import."""

    def __init__(self, alerts: list[AlertmanagerAlert]):
        self.alerts = alerts

    def get_completions(self, document: Document, complete_event) -> Iterable[Completion]:
        text = document.text_before_cursor.lower()

        # Also complete by number
        for i, alert in enumerate(self.alerts, 1):
            if text in str(i):
                 yield Completion(
                    text=str(i),
                    start_position=-len(document.text_before_cursor),
                    display=f"[{i}] {alert.labels.get('alertname', 'N/A')}",
                    display_meta=alert.annotations.get('summary', '')
                )

        for alert in self.alerts:
            alert_name = alert.labels.get("alertname", "")
            fingerprint = alert.fingerprint

            if text in fingerprint.lower() or (alert_name and text in alert_name.lower()):
                yield Completion(
                    text=fingerprint,
                    start_position=-len(document.text_before_cursor),
                    display=fingerprint[:16] + "...",
                    display_meta=alert_name,
                )


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

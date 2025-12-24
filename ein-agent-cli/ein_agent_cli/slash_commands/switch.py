"""Implementation of the /switch slash command."""
from typing import Dict, List, Optional

from temporalio.client import Client as TemporalClient

from ein_agent_cli import console
from ein_agent_cli.completer import WorkflowCompleter
from ein_agent_cli.models import HumanInLoopConfig, SessionState
from ein_agent_cli.slash_commands.base import (
    CommandResult,
    SlashCommand,
)
from ein_agent_cli.ui import InteractiveList


class SwitchCommand(SlashCommand):
    """Switch to a workflow in the current context."""

    @property
    def name(self) -> str:
        return "switch"

    @property
    def description(self) -> str:
        return "Switch to a workflow in the current context"

    async def execute(
        self, args: str, config: HumanInLoopConfig, client: TemporalClient, session: SessionState
    ) -> CommandResult:
        context = session.get_current_context()
        if not context:
            console.print_error("No active context.")
            return CommandResult()

        workflows = context.local_context.get_all_workflows()
        if not workflows:
            console.print_info("No workflows in local context to switch to.")
            return CommandResult()
        
        # If an argument is provided, try to switch directly
        if args:
            item = self._workflow_finder(args, workflows)
            if item:
                return await self._switch_to_workflow(item, {"session": session})
            else:
                console.print_error(f"Workflow '{args}' not found in local context.")
                return CommandResult()

        interactive_list = InteractiveList(
            items=workflows,
            item_name="workflow",
            table_title="Switch to a Workflow",
            column_definitions=[
                {"header": "#", "style": "dim"},
                {"header": "Workflow ID", "style": "cyan"},
                {"header": "Type", "style": "green"},
                {"header": "Alert", "style": "yellow"},
                {"header": "Status", "style": "blue"},
            ],
            row_renderer=self._render_row,
            completer_class=lambda items: WorkflowCompleter(
                items, session.current_workflow_id
            ),
            default_action=self._switch_to_workflow,
            finder=self._workflow_finder,
            session_state={
                "session": session,
                "context": context,
            },
        )
        result = await interactive_list.run()
        return result or CommandResult()

    def _workflow_finder(self, search_term: str, items: List[Dict]) -> Optional[Dict]:
        try:
            choice = int(search_term)
            if 1 <= choice <= len(items):
                return items[choice - 1]
        except ValueError:
            pass
        
        for item in items:
            if search_term in item.get("workflow_id", ""):
                return item
        return None

    def _render_row(self, idx: int, wf: Dict, session_state: Dict) -> List[str]:
        context = session_state["context"]
        workflow_id = wf.get("workflow_id", "")
        workflow_type = wf.get("type", "")
        status = wf.get("status", "")
        alert_fingerprint = wf.get("alert_fingerprint")

        alert_name = "-"
        if alert_fingerprint:
            alert_item = context.local_context.get_item(alert_fingerprint)
            alert_name = (
                alert_item.data.get("alertname", alert_fingerprint[:12] + "...")
                if alert_item
                else alert_fingerprint[:12] + "..."
            )

        display_id = (
            workflow_id if len(workflow_id) <= 30 else workflow_id[:27] + "..."
        )
        return [str(idx), display_id, workflow_type, alert_name, status]

    async def _switch_to_workflow(
        self, wf: Dict, session_state: Dict
    ) -> Optional[CommandResult]:
        session = session_state["session"]
        workflow_id = wf.get("workflow_id")

        if not workflow_id:
            return CommandResult()

        if workflow_id == session.current_workflow_id:
            console.print_info(f"Re-entering workflow {workflow_id}...")
        else:
            console.print_success(f"✓ Switched to workflow: {workflow_id}")
        
        return CommandResult(should_switch=True, workflow_id=workflow_id)

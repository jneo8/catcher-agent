"""Implementation of the /alerts slash command."""
import json
from typing import Dict, List, Optional

from rich.prompt import Prompt
from temporalio.client import Client as TemporalClient

from ein_agent_cli import console
from ein_agent_cli.completer import AlertCompleter
from ein_agent_cli.models import (
    ContextItem,
    ContextItemType,
    HumanInLoopConfig,
    SessionState,
)
from ein_agent_cli.slash_commands.base import CommandResult, SlashCommand
from ein_agent_cli.ui import InteractiveList

PASS_1_RCA_PROMPT = """You are an RCA analyst. Your task is to perform a root cause analysis for the given alert.

Here is the alert details:
{alert_details}
"""


class AlertsCommand(SlashCommand):
    """List and manage locally stored alerts."""

    @property
    def name(self) -> str:
        return "alerts"

    @property
    def description(self) -> str:
        return "List and manage locally stored alerts"

    async def execute(
        self, args: str, config: HumanInLoopConfig, client: TemporalClient, session: SessionState
    ) -> CommandResult:
        all_alerts = session.local_context.get_items_by_type(ContextItemType.ALERT)
        if not all_alerts:
            console.print_info(
                "No alerts in local context. Use /import-alerts to import alerts."
            )
            return CommandResult()

        def _alert_finder(search_term: str, items: List[ContextItem]) -> Optional[ContextItem]:
            try:
                choice = int(search_term)
                if 1 <= choice <= len(items):
                    return items[choice - 1]
            except ValueError:
                pass
            
            for item in items:
                if search_term in item.item_id:
                    return item
            return None

        filter_keys = ["name", "status", "severity", "fingerprint"]

        interactive_list = InteractiveList(
            items=all_alerts,
            item_name="alert",
            table_title="Alerts in Local Context",
            column_definitions=[
                {"header": "#", "style": "dim"},
                {"header": "Alert Name", "style": "cyan"},
                {"header": "Status", "style": "yellow"},
                {"header": "Severity", "style": "red"},
                {"header": "Workflows", "style": "green"},
                {"header": "Fingerprint", "style": "dim"},
            ],
            row_renderer=self._render_row,
            completer_class=AlertCompleter,
            finder=_alert_finder,
            item_actions=[
                {"name": "View Details", "handler": self._view_alert_details},
                {"name": "Remove from context", "handler": self._remove_alert},
                {"name": "Start RCA workflow", "handler": self._start_rca_workflow},
            ],
            session_state={"session": session},
            filter_keys=filter_keys,
            filter_logic=self._filter_alerts,
        )
        interactive_list.session_state["interactive_list"] = interactive_list
        result = await interactive_list.run()
        return result or CommandResult()

    def _filter_alerts(self, items: List[ContextItem], filters: Dict[str, str]) -> List[ContextItem]:
        filtered_items = []
        
        key_map = {
            "status": "status",
            "name": "alertname",
            "severity": "severity",
            "fingerprint": "item_id",
        }

        for item in items:
            matches_all = True
            for key, value in filters.items():
                value_lower = value.lower()
                
                if key not in key_map:
                    continue

                # Special handling for fingerprint as it's on the item itself
                if key == "fingerprint":
                    if value_lower not in item.item_id.lower():
                        matches_all = False
                        break
                    continue
                
                # For other keys, look inside the 'data' or 'data.labels' dict
                item_value = None
                if key == "severity":
                    item_value = item.data.get("labels", {}).get(key_map[key], "")
                else:
                    item_value = item.data.get(key_map[key], "")
                
                if value_lower not in str(item_value).lower():
                    matches_all = False
                    break
            
            if matches_all:
                filtered_items.append(item)
        return filtered_items


    def _render_row(
        self, idx: int, item: ContextItem, session_state: Dict
    ) -> List[str]:
        session = session_state["session"]
        alert_data = item.data
        alert_name = alert_data.get("alertname", "unknown")
        status = alert_data.get("status", "unknown")
        severity = alert_data.get("labels", {}).get("severity", "-")
        fingerprint = item.item_id[:12] + "..."
        workflows_info = self._get_workflows_for_alert(item.item_id, session)
        return [str(idx), alert_name, status, severity, workflows_info, fingerprint]

    def _get_workflows_for_alert(
        self, alert_fingerprint: str, session: SessionState
    ) -> str:
        context = session.get_current_context()
        if not context:
            return "-"
        local_ctx = context.local_context
        parts = []
        if rca := local_ctx.get_rca_for_alert(alert_fingerprint):
            parts.append(f"RCA: {rca.status}")
        if enrichment := local_ctx.get_enrichment_rca_for_alert(alert_fingerprint):
            parts.append(f"EnrichRCA: {enrichment.status}")
        return ", ".join(parts) if parts else "-"

    async def _view_alert_details(
        self, item: ContextItem, session_state: Dict
    ) -> Optional[CommandResult]:
        console.print_newline()
        console.print_info("Alert Details:")
        console.print_message(json.dumps(item.data, indent=2))
        if item.source:
            console.print_dim(f"Source: {item.source}")
        console.print_newline()
        return None

    async def _remove_alert(
        self, item: ContextItem, session_state: Dict
    ) -> Optional[CommandResult]:
        session = session_state["session"]
        interactive_list = session_state["interactive_list"]
        alert_name = item.data.get("labels", {}).get("alertname", "unknown")
        if Prompt.ask(
            f"Remove alert '{alert_name}'?", choices=["y", "n"], default="n"
        ).lower() == "y":
            session.local_context.remove_item(item.item_id)
            interactive_list.all_items.remove(item)
            console.print_success(f"Removed alert '{alert_name}' from context")
        else:
            console.print_info("Cancelled")
        return None

    async def _start_rca_workflow(
        self, item: ContextItem, session_state: Dict
    ) -> Optional[CommandResult]:
        prompt = PASS_1_RCA_PROMPT.format(alert_details=json.dumps(item.data, indent=2))
        return CommandResult(
            should_create_new=True,
            new_workflow_prompt=prompt,
            workflow_type="RCA",
            alert_fingerprint=item.item_id,
        )

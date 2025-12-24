"""Implementation of the /import-alerts slash command."""
from typing import Dict, List, Optional

from temporalio.client import Client as TemporalClient

from ein_agent_cli import console
from ein_agent_cli.alertmanager import query_alertmanager
from ein_agent_cli.completer import ImportAlertsCompleter
from ein_agent_cli.models import (
    AlertmanagerQueryParams,
    ContextItem,
    ContextItemType,
    HumanInLoopConfig,
    SessionState,
    WorkflowAlert,
    AlertmanagerAlert,
)
from ein_agent_cli.slash_commands.base import CommandResult, SlashCommand
from ein_agent_cli.ui import InteractiveList


class ImportAlertsCommand(SlashCommand):
    """Import alerts from AlertManager to local context."""

    @property
    def name(self) -> str:
        return "import-alerts"

    @property
    def description(self) -> str:
        return "Query AlertManager and import alerts to local context"

    async def execute(
        self, args: str, config: HumanInLoopConfig, client: TemporalClient, session: SessionState
    ) -> CommandResult:
        context = session.get_current_context()
        if not context:
            console.print_error("No active context.")
            return CommandResult()

        alertmanager_url = args or config.alertmanager_url or "http://localhost:9093"

        console.print_info(f"Querying AlertManager at {alertmanager_url}...")
        try:
            all_alerts = await query_alertmanager(
                AlertmanagerQueryParams(url=alertmanager_url)
            )
        except Exception as e:
            console.print_error(f"Failed to query AlertManager: {e}")
            return CommandResult()

        if not all_alerts:
            console.print_info("No alerts found from AlertManager.")
            return CommandResult()

        context_fingerprints = set(context.local_context.items.keys())
        new_alerts = [
            a for a in all_alerts if a.fingerprint not in context_fingerprints
        ]

        if not new_alerts:
            console.print_info("No new alerts to import. All alerts are already in the local context.")
            return CommandResult()

        filter_keys = ["name", "summary", "state"]

        interactive_list = InteractiveList(
            items=new_alerts,
            item_name="alert",
            table_title="New Alerts from AlertManager",
            column_definitions=[
                {"header": "#", "style": "dim"},
                {"header": "Alert Name", "style": "cyan"},
                {"header": "Summary", "style": "white"},
                {"header": "State", "style": "yellow"},
                {"header": "Starts At", "style": "blue"},
            ],
            row_renderer=self._render_alert_row,
            finder=self._alert_finder,
            completer_class=ImportAlertsCompleter,
            item_actions=[
                {"name": "Import this alert", "handler": self._import_alert},
            ],
            session_state={
                "session": session,
                "alertmanager_url": alertmanager_url,
            },
            filter_keys=filter_keys,
            filter_logic=self._filter_alerts,
        )
        interactive_list.session_state["interactive_list"] = interactive_list
        await interactive_list.run()
        return CommandResult()

    def _filter_alerts(self, items: List[AlertmanagerAlert], filters: Dict[str, str]) -> List[AlertmanagerAlert]:
        filtered_items = []
        
        for item in items:
            matches_all = True
            for key, value in filters.items():
                value_lower = value.lower()
                
                if key == "name":
                    if value_lower not in item.labels.get("alertname", "").lower():
                        matches_all = False
                        break
                elif key == "summary":
                    if value_lower not in item.annotations.get("summary", "").lower():
                        matches_all = False
                        break
                elif key == "state":
                    if value_lower not in item.status.state.lower():
                        matches_all = False
                        break
            
            if matches_all:
                filtered_items.append(item)
        return filtered_items


    def _alert_finder(self, search_term: str, items: List[AlertmanagerAlert]) -> Optional[AlertmanagerAlert]:
        try:
            choice = int(search_term)
            if 1 <= choice <= len(items):
                return items[choice - 1]
        except ValueError:
            pass
        
        for item in items:
            if search_term in item.fingerprint:
                return item
            if search_term in item.labels.get("alertname", ""):
                return item
        return None

    def _render_alert_row(self, idx: int, alert: AlertmanagerAlert, session_state: Dict) -> List[str]:
        alert_name = alert.labels.get("alertname", "N/A")
        summary = alert.annotations.get("summary", "N/A")
        if len(summary) > 60:
            summary = summary[:57] + "..."
        state = alert.status.state
        starts_at = alert.startsAt
        return [str(idx), alert_name, summary, state, starts_at]

    async def _import_alert(self, alert: AlertmanagerAlert, session_state: Dict) -> Optional[CommandResult]:
        session = session_state["session"]
        alertmanager_url = session_state["alertmanager_url"]
        interactive_list = session_state["interactive_list"]
        
        context = session.get_current_context()
        if not context:
            return CommandResult()

        item = ContextItem(
            item_id=alert.fingerprint,
            item_type=ContextItemType.ALERT,
            data=WorkflowAlert.from_alertmanager_alert(alert).model_dump(),
            source=alertmanager_url,
        )
        context.local_context.add_item(item)
        console.print_success(f"Imported alert '{alert.labels.get('alertname', alert.fingerprint)}'.")
        
        # Remove the alert from the list in the interactive list component
        interactive_list.all_items.remove(alert)
        
        return None

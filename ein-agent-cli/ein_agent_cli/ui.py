"""Reusable UI components for the CLI."""

from typing import Any, Callable, Dict, List, Optional

from prompt_toolkit import PromptSession
from rich.prompt import Prompt, IntPrompt
from rich.table import Table

from ein_agent_cli import console
from ein_agent_cli.slash_commands.base import CommandResult


class InteractiveList:
    """A reusable component for displaying, filtering, and selecting from a list of items."""

    def __init__(
        self,
        items: List[Any],
        item_name: str,
        table_title: str,
        column_definitions: List[Dict[str, Any]],
        row_renderer: Callable[[Any, Dict], None],
        completer_class: Optional[Callable] = None,
        item_actions: Optional[List[Dict[str, Any]]] = None,
        default_action: Optional[Callable] = None,
        session_state: Optional[Dict] = None,
        finder: Optional[Callable] = None,
        filter_keys: Optional[List[str]] = None,
        filter_logic: Optional[Callable] = None,
    ):
        self.all_items = items
        self.item_name = item_name
        self.table_title = table_title
        self.column_definitions = column_definitions
        self.row_renderer = row_renderer
        self.completer_class = completer_class
        self.item_actions = item_actions or []
        self.default_action = default_action
        self.session_state = session_state or {}
        self.finder = finder or self._default_find_item
        self.filters: Dict[str, str] = {}
        self.filter_keys = filter_keys or []
        self.filter_logic = filter_logic or self._default_filter_logic

    async def run(self) -> Optional[CommandResult]:
        """Main loop for the interactive list."""
        while True:
            filtered_items = self._apply_filters()

            if not filtered_items:
                console.print_info(f"No {self.item_name}s match the current filters.")
                if self.filters:
                    action = Prompt.ask("Actions: (c)lear filter, (q)uit", choices=["c", "q"], default="q")
                    if action == "c":
                        self.filters = {}
                        continue
                return None

            self._display_table(filtered_items)

            action = Prompt.ask("Actions: (s)elect, (f)ilter, (c)lear filter, (q)uit", choices=["s", "f", "c", "q"], default="q")

            if action == "s":
                result = await self._select_and_act(filtered_items)
                if result:
                    return result
                continue
            elif action == "f":
                self._prompt_for_filters()
                continue
            elif action == "c":
                self.filters = {}
                continue
            elif action == "q":
                return None

    def _apply_filters(self) -> List[Any]:
        """Apply current filters to the list of items."""
        if not self.filters:
            return self.all_items
        return self.filter_logic(self.all_items, self.filters)

    def _display_table(self, items: List[Any]):
        """Display the items in a table."""
        if self.filters:
            filter_str = ", ".join([f"{k}={v}" for k, v in self.filters.items()])
            title = f"{self.table_title} ({len(items)} matching filters: {filter_str})"
        else:
            title = f"{self.table_title} ({len(items)} total)"

        table = Table(title=title, show_header=True, header_style="bold magenta")
        for col_def in self.column_definitions:
            table.add_column(col_def["header"], style=col_def.get("style"))

        for idx, item in enumerate(items, 1):
            row_data = self.row_renderer(idx, item, self.session_state)
            table.add_row(*row_data)

        console.print_table(table)

    async def _select_and_act(self, items: List[Any]) -> Optional[CommandResult]:
        """Prompt for selection and execute the chosen action."""
        console.print_newline()
        try:
            completer = self.completer_class(items) if self.completer_class else None
            prompt_session = PromptSession(completer=completer)

            console.print_info(f"Select {self.item_name} by number or ID (with auto-completion):")
            user_input = await prompt_session.prompt_async(f"{self.item_name.capitalize()}: ")

            if not user_input or not user_input.strip():
                console.print_info("Cancelled.")
                return None

            selected_item = self.finder(user_input, items)

            if not selected_item:
                console.print_error(f"{self.item_name.capitalize()} '{user_input}' not found.")
                return None

            if self.default_action:
                return await self.default_action(selected_item, self.session_state)

            return await self._show_action_menu(selected_item)

        except (KeyboardInterrupt, EOFError):
            return None

    def _default_find_item(self, search_term: str, items: List[Any]) -> Optional[Any]:
        """Find an item by index or a unique property."""
        try:
            choice = int(search_term)
            if 1 <= choice <= len(items):
                return items[choice - 1]
        except ValueError:
            pass  # Fallback to searching by a property
        
        # This is a generic implementation. The instantiator should provide a proper finder function.
        # For now, we'll assume a simple dict with an 'id' key.
        for item in items:
            if isinstance(item, dict) and (item.get("id") == search_term or search_term in item.get("id", "")):
                return item
        return None

    async def _show_action_menu(self, item: Any) -> Optional[CommandResult]:
        """Display a menu of actions for the selected item."""
        while True:
            console.print_newline()
            console.print_info(f"{self.item_name.capitalize()} Actions:")

            for idx, action in enumerate(self.item_actions, 1):
                console.print_message(f"  [{idx}] {action['name']}")
            
            back_idx = len(self.item_actions) + 1
            console.print_message(f"  [{back_idx}] Back to list")
            console.print_newline()

            try:
                choice = IntPrompt.ask("Select action", default=back_idx)

                if choice == back_idx:
                    return None
                
                if 1 <= choice <= len(self.item_actions):
                    action_handler = self.item_actions[choice - 1]["handler"]
                    result = await action_handler(item, self.session_state)
                    if result is not None:
                        return result
                    # if the handler returns None, the action is considered complete for this item.
                    # Break the action menu loop and go back to the main item list.
                    break
                else:
                    console.print_error("Invalid choice.")

            except (KeyboardInterrupt, EOFError):
                return None

    def _default_filter_logic(self, items: List[Any], filters: Dict[str, str]) -> List[Any]:
        """A default, simple, case-insensitive filter logic."""
        filtered_items = []
        for item in items:
            matches_all = True
            for key, value in filters.items():
                item_value = item.get(key)
                if item_value is None:
                    # If the item doesn't have the key, it's not a match.
                    # This could be adapted based on desired behavior.
                    matches_all = False
                    break
                
                # Case-insensitive containment check
                if value.lower() not in str(item_value).lower():
                    matches_all = False
                    break
            
            if matches_all:
                filtered_items.append(item)
        return filtered_items
    
    def _prompt_for_filters(self):
        """Prompt user for key-value filters."""
        console.print_newline()
        if self.filter_keys:
            keys = ", ".join(self.filter_keys)
            console.print_info(f"Enter filters as key=value pairs (e.g., status=running type=RCA).")
            console.print_info(f"Available keys: {keys}")
        else:
            console.print_info("Enter filters (e.g., key=value key2=value2):")
        filter_input = Prompt.ask("Filters")
        self.filters = self._parse_filters(filter_input)

    @staticmethod
    def _parse_filters(filter_input: str) -> dict:
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

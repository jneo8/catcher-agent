"""Implementation of the /switch-context slash command."""
from prompt_toolkit import PromptSession
from rich.table import Table
from temporalio.client import Client as TemporalClient

from ein_agent_cli import console
from ein_agent_cli.completer import ContextCompleter
from ein_agent_cli.models import HumanInLoopConfig, SessionState
from ein_agent_cli.slash_commands.base import (
    CommandResult,
    SlashCommand,
)


class SwitchContextCommand(SlashCommand):
    """Switch to a different investigation context."""

    @property
    def name(self) -> str:
        return "switch-context"

    @property
    def description(self) -> str:
        return "Switch to a different investigation context"

    async def execute(
        self, args: str, config: HumanInLoopConfig, client: TemporalClient, session: SessionState
    ) -> CommandResult:
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
        table = Table(
            "",
            "Context ID",
            "Name",
            "Alerts",
            "Workflows",
            show_header=True,
            header_style="bold magenta",
        )

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
                str(workflow_count),
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
                    if (
                        ctx.context_name
                        and ctx.context_name.lower() == search_term.lower()
                    ):
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

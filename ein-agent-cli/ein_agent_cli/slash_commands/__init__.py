"""A registry for slash commands."""
from typing import Dict, Optional, Iterable

from temporalio.client import Client as TemporalClient

from ein_agent_cli import console
from ein_agent_cli.models import HumanInLoopConfig, SessionState
from ein_agent_cli.slash_commands.alerts import AlertsCommand
from ein_agent_cli.slash_commands.base import CommandResult, SlashCommand
from ein_agent_cli.slash_commands.compact_rca import CompactRCACommand
from ein_agent_cli.slash_commands.complete import CompleteCommand
from ein_agent_cli.slash_commands.context import ContextCommand
from ein_agent_cli.slash_commands.exit import ExitCommand
from ein_agent_cli.slash_commands.help import HelpCommand
from ein_agent_cli.slash_commands.import_alerts import ImportAlertsCommand
from ein_agent_cli.slash_commands.new import NewCommand
from ein_agent_cli.slash_commands.refresh import RefreshCommand
from ein_agent_cli.slash_commands.switch import SwitchCommand
from ein_agent_cli.slash_commands.switch_context import SwitchContextCommand
from ein_agent_cli.slash_commands.workflows import WorkflowsCommand
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document


class CommandRegistry:
    """A registry for slash commands."""

    def __init__(self):
        self._commands: Dict[str, SlashCommand] = {}
        # The help command needs a reference to the registry itself
        self.register(HelpCommand(self))
        self.register(AlertsCommand())
        self.register(CompactRCACommand())
        self.register(CompleteCommand())
        self.register(ContextCommand())
        self.register(ExitCommand())
        self.register(ImportAlertsCommand())
        self.register(NewCommand())
        self.register(RefreshCommand())
        self.register(SwitchCommand())
        self.register(SwitchContextCommand())
        self.register(WorkflowsCommand())

    def register(self, command: SlashCommand):
        """Registers a command."""
        self._commands[command.name] = command

    def find(self, name: str) -> Optional[SlashCommand]:
        """Finds a command by its name."""
        return self._commands.get(name)

    def get_all(self) -> list[SlashCommand]:
        """Returns a list of all registered commands."""
        return list(self._commands.values())


class SlashCommandCompleter(Completer):
    """Completer that provides auto-completion for slash commands."""

    def __init__(self, registry: CommandRegistry):
        """Initialize the completer with a command registry.

        Args:
            registry: The CommandRegistry containing available commands.
        """
        self.registry = registry

    def get_completions(self, document: Document, complete_event) -> Iterable[Completion]:
        """Generate completions for the current input.

        Args:
            document: The current document being edited.
            complete_event: The completion event.

        Yields:
            Completion objects for matching commands.
        """
        text = document.text_before_cursor

        # Only provide completions if the user has typed a slash
        if not text.startswith('/'):
            return

        # Get the partial command (everything after the slash)
        partial_command = text[1:]

        # Get all commands from the registry
        commands = self.registry.get_all()

        # Filter commands that match the partial input
        for cmd in commands:
            command_text = f"/{cmd.name}"

            # Check if the command matches the current input
            if cmd.name.startswith(partial_command):
                # Calculate how many characters back to start the completion
                # This ensures we replace from the '/' onwards
                start_position = -len(text)

                yield Completion(
                    text=command_text,
                    start_position=start_position,
                    display=command_text,
                    display_meta=cmd.description,
                )



async def handle_command(
    user_input: str,
    registry: CommandRegistry,
    config: HumanInLoopConfig,
    client: TemporalClient,
    session: SessionState,
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
    if not user_input.startswith("/"):
        return CommandResult(
            should_continue=False
        )  # Not a command, probably a text response

    parts = user_input.strip()[1:].split(" ", 1)
    command_name = parts[0]
    args = parts[1] if len(parts) > 1 else ""

    command = registry.find(command_name)
    if not command:
        console.print_error(f"Unknown command: /{command_name}")
        return CommandResult()

    return await command.execute(args, config, client, session)

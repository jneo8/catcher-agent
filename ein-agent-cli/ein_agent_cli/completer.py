"""Auto-completion support for slash commands."""

from typing import Iterable

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document

from ein_agent_cli.slash_commands import CommandRegistry


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

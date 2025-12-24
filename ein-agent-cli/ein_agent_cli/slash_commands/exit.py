"""Implementation of the /exit slash command."""
from temporalio.client import Client as TemporalClient

from ein_agent_cli import console
from ein_agent_cli.models import HumanInLoopConfig, SessionState
from ein_agent_cli.slash_commands.base import CommandResult, SlashCommand


class ExitCommand(SlashCommand):
    """Exits the CLI."""

    @property
    def name(self) -> str:
        return "exit"

    @property
    def description(self) -> str:
        return "Exit the CLI"

    async def execute(
        self, args: str, config: HumanInLoopConfig, client: TemporalClient, session: SessionState
    ) -> CommandResult:
        console.print_warning("Exiting.")
        return CommandResult(should_exit=True)

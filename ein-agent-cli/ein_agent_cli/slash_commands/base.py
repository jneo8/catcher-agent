"""Base classes for slash commands."""

from abc import ABC, abstractmethod
from typing import Dict, Optional, Any

from temporalio.client import Client as TemporalClient

from ein_agent_cli.models import HumanInLoopConfig, SessionState


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
        workflow_type: Optional[str] = None,  # Type of workflow: RCA, EnrichmentRCA, CompactRCA, etc.
        alert_fingerprint: Optional[str] = None,  # Alert fingerprint for RCA/EnrichmentRCA workflows
        enrichment_context: Optional[Dict[str, Any]] = None,  # Context for enrichment workflows
        source_workflow_ids: Optional[list] = None,  # Source workflows for compact workflows
    ):
        self.should_continue = should_continue
        self.should_exit = should_exit
        self.workflow_id = workflow_id  # For backward compatibility and switching
        self.should_switch = should_switch  # Signal to switch to workflow_id
        self.should_create_new = should_create_new  # Signal to create new workflow
        self.new_workflow_prompt = new_workflow_prompt  # Task for new workflow
        self.should_complete = should_complete # Signal to complete the workflow
        self.workflow_type = workflow_type  # Type of workflow being created
        self.alert_fingerprint = alert_fingerprint  # Alert for RCA workflows
        self.enrichment_context = enrichment_context  # Context for enrichment
        self.source_workflow_ids = source_workflow_ids  # Sources for compact workflows


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

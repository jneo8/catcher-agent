"""Orchestrates human-in-the-loop workflow execution."""

import asyncio
from typing import Optional
import uuid

import typer
from prompt_toolkit import PromptSession
from rich.panel import Panel
from temporalio.client import Client as TemporalClient
from temporalio.api.enums.v1 import EventType
from temporalio.api.workflowservice.v1 import ResetWorkflowExecutionRequest
from temporalio.api.common.v1 import WorkflowExecution

from ein_agent_cli import console
from ein_agent_cli.completer import SlashCommandCompleter
from ein_agent_cli.slash_commands import (
    AlertsCommand,
    CommandRegistry,
    CompleteCommand,
    EndCommand,
    handle_command,
    ImportAlertsCommand,
    NewCommand,
    RefreshCommand,
    SwitchCommand,
    WorkflowsCommand,
)
from ein_agent_cli.temporal import (
    trigger_human_in_loop_workflow,
    start_workflow_execution,
    provide_user_action,
    get_workflow_status,
    end_workflow,
)
from ein_agent_cli.models import (
    HumanInLoopConfig,
    SessionState,
    WorkflowStatus,
    UserAction,
    ActionType,
)


async def run_human_in_loop(config: HumanInLoopConfig) -> None:
    """Orchestrate human-in-the-loop workflow execution."""
    try:
        console.print_header("Ein Agent - Human-in-the-Loop Workflow\n")
        console.print_dim(f"Temporal: {config.temporal.host}/{config.temporal.namespace}")
        console.print_newline()

        client = await TemporalClient.connect(
            config.temporal.host,
            namespace=config.temporal.namespace,
        )

        # Initialize session state for managing multiple workflows
        session = SessionState()

        # Initialize and populate the command registry
        registry = CommandRegistry()
        registry.register(WorkflowsCommand())
        registry.register(SwitchCommand())
        registry.register(NewCommand())
        registry.register(RefreshCommand())
        registry.register(EndCommand())
        registry.register(ImportAlertsCommand())
        registry.register(AlertsCommand())
        registry.register(CompleteCommand())

        # Initial prompt loop to get first workflow
        workflow_id, user_prompt = await _initial_user_prompt_loop(config, client, registry, session)

        if not workflow_id:
            # A text prompt was provided, so we start a new workflow
            workflow_id = await _create_new_workflow(config, client, user_prompt)

        # Add workflow to session
        session.add_workflow(workflow_id)

        console.print_dim(f"Workflow ID: {workflow_id}")
        console.print_dim(f"(Use '/switch' to switch between workflows, '/new' to create a new one)")
        console.print_newline()

        # Main interactive loop - handles workflow switching
        await _main_session_loop(config, client, registry, session)

    except typer.Exit:
        raise
    except Exception as e:
        console.print_error(f"✗ Error: {e}")
        raise typer.Exit(1)


async def _create_new_workflow(config: HumanInLoopConfig, client: TemporalClient, user_prompt: str) -> str:
    """Create a new workflow with the given user prompt."""
    console.print_newline()
    console.print_info(f"Task: {user_prompt}")
    console.print_newline()
    console.print_info("Starting workflow...")

    workflow_id = await trigger_human_in_loop_workflow(
        user_prompt=user_prompt,
        config=config.temporal,
        workflow_id=config.workflow_id,
    )
    await start_workflow_execution(
        client=client,
        workflow_id=workflow_id,
        user_prompt=user_prompt,
    )
    console.print_success("✓ Agent is now working on your task")
    console.print_newline()
    return workflow_id


async def _initial_user_prompt_loop(config: HumanInLoopConfig, client: TemporalClient, registry: CommandRegistry, session_state: SessionState) -> (Optional[str], Optional[str]):
    """Handles the initial user prompt before a workflow starts."""
    if config.user_prompt and config.user_prompt.strip():
        return None, config.user_prompt

    # Create prompt session with auto-completion
    completer = SlashCommandCompleter(registry)
    prompt_session = PromptSession(completer=completer)

    console.print_info("What would you like the agent to help you with? (Type /help for commands)")
    while True:
        user_input = await prompt_session.prompt_async("You: ")
        if not user_input.startswith('/'):
            # This is the main task prompt
            return None, user_input

        result = await handle_command(user_input, registry, config, client, session_state)
        if result.should_exit:
            raise typer.Exit(0)

        # Handle new workflow creation
        if result.should_create_new and result.new_workflow_prompt:
            return None, result.new_workflow_prompt

        # Handle workflow switching
        if result.should_switch and result.workflow_id:
            console.print_info("Resuming conversation...")
            console.print_newline()
            return result.workflow_id, None

        console.print_newline()


async def _main_session_loop(config: HumanInLoopConfig, client: TemporalClient, registry: CommandRegistry, session: SessionState) -> None:
    """Main session loop that handles multiple workflows and switching between them."""
    while True:
        current_workflow_id = session.current_workflow_id
        if not current_workflow_id:
            console.print_error("No active workflow in session.")
            break

        # Run the interactive loop for the current workflow
        action = await _interactive_workflow_loop(config, client, registry, session)

        # Handle the action returned by the interactive loop
        if action == "exit":
            break
        elif action == "switch":
            # The switch already happened in the loop, just continue
            console.print_info(f"Now on workflow: {session.current_workflow_id}")
            console.print_newline()
            continue
        elif action == "new_workflow":
            # A new workflow was created and added to session, continue with it
            console.print_info(f"Now on workflow: {session.current_workflow_id}")
            console.print_newline()
            continue


async def _interactive_workflow_loop(config: HumanInLoopConfig, client: TemporalClient, registry: CommandRegistry, session: SessionState) -> str:
    """The main interactive loop while a workflow is running.

    Returns:
        Action string: "exit", "switch", "new_workflow", or "completed"
    """
    workflow_id = session.current_workflow_id
    iteration = 0
    while iteration < config.max_iterations:
        iteration += 1

        status = await get_workflow_status(client, workflow_id)

        if status.state == "executing":
            _display_executing_status(status, iteration)
            await asyncio.sleep(config.poll_interval)
            continue

        elif status.state == "awaiting_input":
            _display_awaiting_input_status(status)
            result = await _get_user_action(config, client, registry, session)

            # Handle exit
            if result is None:
                console.print_warning("Ending workflow...")
                await end_workflow(client, workflow_id)
                return "exit"

            # Handle workflow switching
            if result.should_switch and result.workflow_id:
                session.switch_to(result.workflow_id)
                return "switch"

            # Handle new workflow creation
            if result.should_create_new and result.new_workflow_prompt:
                new_workflow_id = await _create_new_workflow(config, client, result.new_workflow_prompt)
                session.add_workflow(new_workflow_id)
                return "new_workflow"

            # Handle workflow completion
            if result.should_complete:
                console.print_info(f"Signaling workflow to complete: {workflow_id}")
                await end_workflow(client, workflow_id)
                console.print_success("✓ Completion signal sent.")
                # The loop will continue and detect the completed state
                continue

            # Normal user action - send to workflow
            console.print_dim("Sending action to agent...")
            await provide_user_action(client, workflow_id, result)
            console.print_success("✓ Action sent")
            console.print_newline()

        elif status.state == "completed":
            _display_completed_status(status, workflow_id, config.temporal)
            return await _completed_workflow_loop(config, client, registry, session)
        elif status.state == "failed":
            _display_failed_status(status)
            raise typer.Exit(1)

    if iteration >= config.max_iterations:
        console.print_warning(f"Maximum iterations ({config.max_iterations}) reached")
        console.print_info("Ending workflow...")
        await end_workflow(client, workflow_id)
        return "completed"


async def _completed_workflow_loop(config: HumanInLoopConfig, client: TemporalClient, registry: CommandRegistry, session: SessionState) -> str:
    """A limited interactive loop for a completed workflow."""
    console.print_info("Workflow is completed. Available commands: /reset, /switch, /new, /workflows, /alerts, /import-alerts, /end")

    # A smaller command registry for completed workflows
    completed_registry = CommandRegistry()
    completed_registry.register(SwitchCommand())
    completed_registry.register(NewCommand())
    completed_registry.register(WorkflowsCommand())
    completed_registry.register(EndCommand())
    completed_registry.register(AlertsCommand())
    completed_registry.register(ImportAlertsCommand())

    while True:
        result = await _get_user_action(config, client, completed_registry, session)

        if result is None: # Exit
            return "exit"
        if result.should_switch and result.workflow_id:
            session.switch_to(result.workflow_id)
            return "switch"
        if result.should_create_new and result.new_workflow_prompt:
            new_workflow_id = await _create_new_workflow(config, client, result.new_workflow_prompt)
            session.add_workflow(new_workflow_id)
            return "new_workflow"

        console.print_newline()




def _display_executing_status(status: WorkflowStatus, iteration: int) -> None:
    """Display executing status."""
    console.print_dim(f"[Iteration {iteration}] Agent is executing...")
    if status.findings:
        console.print_info(f"Progress: {len(status.findings)} finding(s)")


def _display_awaiting_input_status(status: WorkflowStatus) -> None:
    """Display awaiting input status."""
    console.print_newline()
    if status.current_question:
        console.print_message(status.current_question)
        console.print_newline()
    if status.suggested_mcp_tools:
        console.print_dim(f"Suggested tools: {', '.join(status.suggested_mcp_tools)}")
        console.print_newline()


async def _get_user_action(config: HumanInLoopConfig, client: TemporalClient, registry: CommandRegistry, session_state: SessionState):
    """Get user action via interactive prompt, handling slash commands.

    Returns:
        UserAction, CommandResult, or None (for exit)
    """
    # Create prompt session with auto-completion
    completer = SlashCommandCompleter(registry)
    prompt_session = PromptSession(completer=completer)

    while True:
        content = await prompt_session.prompt_async("You: ")
        if not content.startswith('/'):
            return UserAction(action_type=ActionType.TEXT, content=content, metadata={})

        result = await handle_command(content, registry, config, client, session_state)

        # Handle exit
        if result.should_exit:
            return None

        # Handle workflow switching
        if result.should_switch:
            return result

        # Handle new workflow creation
        if result.should_create_new:
            return result

        # Handle workflow completion
        if result.should_complete:
            return result

        console.print_newline()


def _display_completed_status(
    status: WorkflowStatus,
    workflow_id: str,
    temporal_config,
) -> None:
    """Display completed workflow status."""
    console.print_newline()
    console.print_bold_success("✓ Workflow Completed!")
    console.print_newline()

    if status.final_report:
        panel = Panel(
            status.final_report,
            title="Final Report",
            border_style="green",
        )
        console.print_table(panel)

    console.print_newline()
    console.print_info(f"Workflow ID: {workflow_id}")
    ui_host = temporal_config.host.split(':')[0]
    console.print_dim(
        f"View in Temporal UI: http://{ui_host}:8080/namespaces/{temporal_config.namespace}/workflows/{workflow_id}"
    )


def _display_failed_status(status: WorkflowStatus) -> None:
    """Display failed workflow status."""
    console.print_newline()
    console.print_error("✗ Workflow Failed")

    if status.error_message:
        console.print_error(f"Error: {status.error_message}")


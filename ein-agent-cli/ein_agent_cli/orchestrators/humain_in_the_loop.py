"""Orchestrates human-in-the-loop workflow execution."""

import asyncio
from typing import Optional

import typer
from prompt_toolkit import PromptSession
from rich.panel import Panel
from temporalio.client import Client as TemporalClient

from ein_agent_cli import console
from ein_agent_cli.completer import SlashCommandCompleter
from ein_agent_cli.slash_commands import (
    CommandRegistry,
    ConnectWorkflowCommand,
    EndCommand,
    handle_command,
    RefreshCommand,
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

        # Initialize and populate the command registry
        registry = CommandRegistry()
        registry.register(WorkflowsCommand())
        registry.register(ConnectWorkflowCommand())
        registry.register(RefreshCommand())
        registry.register(EndCommand())

        workflow_id, user_prompt = await _initial_user_prompt_loop(config, client, registry)

        if not workflow_id:
            # A text prompt was provided, so we start a new workflow
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
        else:
            # We connected to an existing workflow
            console.print_info("Resuming conversation...")
            console.print_newline()

        console.print_dim(f"Workflow ID: {workflow_id}")
        console.print_dim(f"(Use '/connect-workflow {workflow_id}' to resume this conversation later)")
        console.print_newline()

        await _interactive_workflow_loop(config, client, registry, workflow_id)

    except typer.Exit:
        raise
    except Exception as e:
        console.print_error(f"✗ Error: {e}")
        raise typer.Exit(1)


async def _initial_user_prompt_loop(config: HumanInLoopConfig, client: TemporalClient, registry: CommandRegistry) -> (Optional[str], Optional[str]):
    """Handles the initial user prompt before a workflow starts."""
    if config.user_prompt and config.user_prompt.strip():
        return None, config.user_prompt

    # Create prompt session with auto-completion
    completer = SlashCommandCompleter(registry)
    session = PromptSession(completer=completer)

    console.print_info("What would you like the agent to help you with? (Type /help for commands)")
    while True:
        user_input = await session.prompt_async("You: ")
        if not user_input.startswith('/'):
            # This is the main task prompt
            return None, user_input

        result = await handle_command(user_input, registry, config, client, None)
        if result.should_exit:
            raise typer.Exit(0)
        if not result.should_continue and result.workflow_id:
            # Successfully connected to a workflow
            return result.workflow_id, None

        console.print_newline()

async def _interactive_workflow_loop(config: HumanInLoopConfig, client: TemporalClient, registry: CommandRegistry, workflow_id: str):
    """The main interactive loop while a workflow is running."""
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
            action = await _get_user_action(config, client, registry, workflow_id)

            if action is None: # User requested to end the workflow
                console.print_warning("Ending workflow...")
                await end_workflow(client, workflow_id)
                break

            console.print_dim("Sending action to agent...")
            await provide_user_action(client, workflow_id, action)
            console.print_success("✓ Action sent")
            console.print_newline()

        elif status.state == "completed":
            _display_completed_status(status, workflow_id, config.temporal)
            break
        elif status.state == "failed":
            _display_failed_status(status)
            raise typer.Exit(1)
        
    if iteration >= config.max_iterations:
        console.print_warning(f"Maximum iterations ({config.max_iterations}) reached")
        console.print_info("Ending workflow...")
        await end_workflow(client, workflow_id)


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


async def _get_user_action(config: HumanInLoopConfig, client: TemporalClient, registry: CommandRegistry, workflow_id: str) -> Optional[UserAction]:
    """Get user action via interactive prompt, handling slash commands."""
    # Create prompt session with auto-completion
    completer = SlashCommandCompleter(registry)
    session = PromptSession(completer=completer)

    while True:
        content = await session.prompt_async("You: ")
        if not content.startswith('/'):
            return UserAction(action_type=ActionType.TEXT, content=content, metadata={})

        result = await handle_command(content, registry, config, client, workflow_id)
        if result.should_exit:
            return None # Signal to the main loop to end the workflow

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


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
    CommandResult,
    CompactRCACommand,
    CompleteCommand,
    ContextCommand,
    EndCommand,
    handle_command,
    ImportAlertsCommand,
    NewCommand,
    RefreshCommand,
    SwitchContextCommand,
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
    CompactMetadata,
    EnrichmentRCAMetadata,
    HumanInLoopConfig,
    SessionState,
    WorkflowMetadata,
    WorkflowStatus,
    UserAction,
    ActionType,
)
from ein_agent_cli.session_storage import load_session_state, save_session_state


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

        # Load session state from disk (or create new if doesn't exist)
        session = load_session_state()
        current_context = session.get_current_context()
        if current_context:
            alert_count = len(current_context.local_context.items)
            workflow_count = len(current_context.local_context.get_all_workflows())
            context_name = current_context.context_name or current_context.context_id
            console.print_dim(f"Loaded context '{context_name}' ({alert_count} alerts, {workflow_count} workflows)")
            console.print_dim(f"Total contexts: {len(session.contexts)}")
        else:
            console.print_error("No context available. This should not happen.")
            raise typer.Exit(1)

        # Initialize and populate the command registry
        registry = CommandRegistry()
        registry.register(WorkflowsCommand())
        registry.register(SwitchContextCommand())
        registry.register(NewCommand())
        registry.register(RefreshCommand())
        registry.register(EndCommand())
        registry.register(ImportAlertsCommand())
        registry.register(AlertsCommand())
        registry.register(ContextCommand())
        registry.register(CompactRCACommand())
        registry.register(CompleteCommand())

        # Initial prompt loop to get first workflow
        workflow_id, user_prompt, cmd_result = await _initial_user_prompt_loop(config, client, registry, session)

        if not workflow_id:
            # A text prompt was provided, so we start a new workflow
            if cmd_result:
                # Workflow created from slash command (e.g., /alerts)
                workflow_id = await _create_new_workflow(
                    config,
                    client,
                    session,
                    user_prompt,
                    workflow_type=cmd_result.workflow_type,
                    alert_fingerprint=cmd_result.alert_fingerprint,
                    enrichment_context=cmd_result.enrichment_context,
                    source_workflow_ids=cmd_result.source_workflow_ids,
                )
            else:
                # Plain text prompt from user
                workflow_id = await _create_new_workflow(config, client, session, user_prompt)

        # Add workflow to session
        session.add_workflow(workflow_id)

        console.print_dim(f"Workflow ID: {workflow_id}")
        console.print_dim(f"(Use /workflows to manage workflows, /new for a new context)")
        console.print_newline()

        # Main interactive loop - handles workflow switching
        await _main_session_loop(config, client, registry, session)

    except typer.Exit:
        raise
    except Exception as e:
        console.print_error(f"✗ Error: {e}")
        raise typer.Exit(1)


async def _create_new_workflow(
    config: HumanInLoopConfig,
    client: TemporalClient,
    session: SessionState,
    user_prompt: str,
    workflow_type: Optional[str] = None,
    alert_fingerprint: Optional[str] = None,
    enrichment_context: Optional[dict] = None,
    source_workflow_ids: Optional[list] = None,
) -> str:
    """Create a new workflow with the given user prompt and add to local context."""
    console.print_newline()
    console.print_info(f"Task: {user_prompt[:100]}..." if len(user_prompt) > 100 else f"Task: {user_prompt}")
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

    # Add workflow to local context based on type
    context = session.get_current_context()
    if context and workflow_type:
        if workflow_type == "RCA":
            metadata = WorkflowMetadata(
                workflow_id=workflow_id,
                alert_fingerprint=alert_fingerprint,
                status="running",
                result=None
            )
            context.local_context.add_rca_workflow(metadata)
            console.print_dim(f"Added RCA workflow to context (alert: {alert_fingerprint})")

        elif workflow_type == "EnrichmentRCA":
            metadata = EnrichmentRCAMetadata(
                workflow_id=workflow_id,
                alert_fingerprint=alert_fingerprint,
                status="running",
                result=None,
                enrichment_context=enrichment_context or {}
            )
            context.local_context.add_enrichment_rca_workflow(metadata)
            console.print_dim(f"Added Enrichment RCA workflow to context (alert: {alert_fingerprint})")

        elif workflow_type == "CompactRCA":
            metadata = CompactMetadata(
                workflow_id=workflow_id,
                source_workflow_ids=source_workflow_ids or [],
                status="running",
                result=None
            )
            context.local_context.compact_rca = metadata
            console.print_dim(f"Added Compact RCA workflow to context")

        elif workflow_type == "CompactEnrichmentRCA":
            metadata = CompactMetadata(
                workflow_id=workflow_id,
                source_workflow_ids=source_workflow_ids or [],
                status="running",
                result=None
            )
            context.local_context.compact_enrichment_rca = metadata
            console.print_dim(f"Added Compact Enrichment RCA workflow to context")

        elif workflow_type == "IncidentSummary":
            metadata = WorkflowMetadata(
                workflow_id=workflow_id,
                alert_fingerprint=None,
                status="running",
                result=None
            )
            context.local_context.incident_summary = metadata
            console.print_dim(f"Added Incident Summary workflow to context")

        # Save session state after adding workflow
        save_session_state(session)

    return workflow_id


async def _initial_user_prompt_loop(config: HumanInLoopConfig, client: TemporalClient, registry: CommandRegistry, session_state: SessionState):
    """Handles the initial user prompt before a workflow starts.

    Returns:
        Tuple of (workflow_id, user_prompt, command_result)
        - workflow_id: Existing workflow ID to resume, or None
        - user_prompt: New workflow prompt, or None
        - command_result: CommandResult with workflow metadata, or None
    """
    if config.user_prompt and config.user_prompt.strip():
        return None, config.user_prompt, None

    # Create prompt session with auto-completion
    completer = SlashCommandCompleter(registry)
    prompt_session = PromptSession(completer=completer)

    console.print_info("What would you like the agent to help you with? (Type /help for commands)")
    while True:
        user_input = await prompt_session.prompt_async("You: ")
        if not user_input.startswith('/'):
            # This is the main task prompt
            return None, user_input, None

        result = await handle_command(user_input, registry, config, client, session_state)

        # Save session state after command execution
        save_session_state(session_state)

        if result.should_exit:
            raise typer.Exit(0)

        # Handle new workflow creation
        if result.should_create_new and result.new_workflow_prompt:
            return None, result.new_workflow_prompt, result

        # Handle workflow switching
        if result.should_switch and result.workflow_id:
            console.print_info("Resuming conversation...")
            console.print_newline()
            return result.workflow_id, None, None

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

            # Check if result is a CommandResult (from slash commands)
            if isinstance(result, UserAction):
                # Normal user action - send to workflow
                console.print_dim("Sending action to agent...")
                await provide_user_action(client, workflow_id, result)
                console.print_success("✓ Action sent")
                console.print_newline()
            else:
                # Handle CommandResult from slash commands
                # Handle workflow switching
                if result.should_switch and result.workflow_id:
                    session.switch_to(result.workflow_id)
                    return "switch"

                # Handle new workflow creation
                if result.should_create_new and result.new_workflow_prompt:
                    new_workflow_id = await _create_new_workflow(
                        config,
                        client,
                        session,
                        result.new_workflow_prompt,
                        workflow_type=result.workflow_type,
                        alert_fingerprint=result.alert_fingerprint,
                        enrichment_context=result.enrichment_context,
                        source_workflow_ids=result.source_workflow_ids,
                    )
                    session.add_workflow(new_workflow_id)
                    return "new_workflow"

                # Handle workflow completion
                if result.should_complete:
                    console.print_info(f"Signaling workflow to complete: {workflow_id}")
                    await end_workflow(client, workflow_id)
                    console.print_success("✓ Completion signal sent.")
                    # The loop will continue and detect the completed state
                    continue

        elif status.state == "completed":
            _display_completed_status(status, workflow_id, config.temporal)
            # Update workflow result in local context
            await _update_workflow_result(client, workflow_id, session, status)
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
    console.print_info("Workflow is completed. Use /workflows to switch workflows or start new ones.")

    # A smaller command registry for completed workflows
    completed_registry = CommandRegistry()
    completed_registry.register(SwitchContextCommand())
    completed_registry.register(NewCommand())
    completed_registry.register(WorkflowsCommand())
    completed_registry.register(EndCommand())
    completed_registry.register(AlertsCommand())
    completed_registry.register(ContextCommand())
    completed_registry.register(CompactRCACommand())
    completed_registry.register(ImportAlertsCommand())

    while True:
        result = await _get_user_action(config, client, completed_registry, session)

        if result is None: # Exit
            return "exit"
        if result.should_switch and result.workflow_id:
            session.switch_to(result.workflow_id)
            return "switch"
        if result.should_create_new and result.new_workflow_prompt:
            new_workflow_id = await _create_new_workflow(
                config,
                client,
                session,
                result.new_workflow_prompt,
                workflow_type=result.workflow_type,
                alert_fingerprint=result.alert_fingerprint,
                enrichment_context=result.enrichment_context,
                source_workflow_ids=result.source_workflow_ids,
            )
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

        # Save session state after command execution
        save_session_state(session_state)

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


async def _update_workflow_result(client: TemporalClient, workflow_id: str, session: SessionState, status: WorkflowStatus) -> None:
    """Update workflow result in local context when workflow completes."""
    context = session.get_current_context()
    if not context:
        return

    # The result is in status.final_report for completed workflows
    workflow_result = {"final_report": status.final_report} if status.final_report else None

    # Find workflow in local context and update its result
    local_ctx = context.local_context

    # Check RCA workflows
    if workflow_id in local_ctx.rca_workflows:
        local_ctx.rca_workflows[workflow_id].status = "completed"
        local_ctx.rca_workflows[workflow_id].result = workflow_result
        save_session_state(session)
        console.print_dim(f"Updated RCA workflow result in context")
        return

    # Check Enrichment RCA workflows
    if workflow_id in local_ctx.enrichment_rca_workflows:
        local_ctx.enrichment_rca_workflows[workflow_id].status = "completed"
        local_ctx.enrichment_rca_workflows[workflow_id].result = workflow_result
        save_session_state(session)
        console.print_dim(f"Updated Enrichment RCA workflow result in context")
        return

    # Check Compact RCA
    if local_ctx.compact_rca and local_ctx.compact_rca.workflow_id == workflow_id:
        local_ctx.compact_rca.status = "completed"
        local_ctx.compact_rca.result = workflow_result
        save_session_state(session)
        console.print_dim(f"Updated Compact RCA workflow result in context")
        return

    # Check Compact Enrichment RCA
    if local_ctx.compact_enrichment_rca and local_ctx.compact_enrichment_rca.workflow_id == workflow_id:
        local_ctx.compact_enrichment_rca.status = "completed"
        local_ctx.compact_enrichment_rca.result = workflow_result
        save_session_state(session)
        console.print_dim(f"Updated Compact Enrichment RCA workflow result in context")
        return

    # Check Incident Summary
    if local_ctx.incident_summary and local_ctx.incident_summary.workflow_id == workflow_id:
        local_ctx.incident_summary.status = "completed"
        local_ctx.incident_summary.result = workflow_result
        save_session_state(session)
        console.print_dim(f"Updated Incident Summary workflow result in context")
        return


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


"""Orchestrates human-in-the-loop workflow execution."""

import asyncio
from typing import Any

import typer
from prompt_toolkit import PromptSession
from rich.panel import Panel
from temporalio.client import Client as TemporalClient

from ein_agent_cli import console
from ein_agent_cli.slash_commands import (
    CommandRegistry,
    handle_command,
    CommandResult,
    SlashCommandCompleter,
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
    """Orchestrate human-in-the-loop workflow execution with a menu-driven UI."""
    try:
        console.print_header("Ein Agent - Human-in-the-Loop\n")
        console.print_dim(f"Temporal: {config.temporal.host}/{config.temporal.namespace}\n")

        client = await TemporalClient.connect(
            config.temporal.host, namespace=config.temporal.namespace
        )
        session = load_session_state()
        registry = CommandRegistry()

        while True:
            _display_main_menu(session)
            user_input = await _get_command_from_prompt(registry)

            result = await handle_command(user_input, registry, config, client, session)
            save_session_state(session)


            if result is None:
                continue

            if result.should_create_new and result.new_workflow_prompt:
                new_workflow_id = await _create_new_workflow(
                    config, client, session, result
                )
                session.add_workflow(new_workflow_id)
                save_session_state(session)
                
                action = await _interactive_workflow_loop(config, client, registry, session)
                if action == "exit":
                    break
            elif result.should_switch and result.workflow_id:
                session.switch_to(result.workflow_id)
                save_session_state(session)
                action = await _interactive_workflow_loop(config, client, registry, session)
                if action == "exit":
                    break
            elif result.should_exit:
                break

    except (typer.Exit, KeyboardInterrupt):
        console.print_warning("\nExiting.")
    except Exception as e:
        console.print_error(f"✗ Error: {e}")
        raise typer.Exit(1)


def _display_main_menu(session: SessionState):
    console.print_header("Main Menu")
    ctx = session.get_current_context()
    if ctx:
        alert_count = len(ctx.local_context.items)
        wf_count = len(ctx.local_context.get_all_workflows())
        console.print_dim(f"Current Context: {ctx.context_name or ctx.context_id} ({alert_count} alerts, {wf_count} workflows)")
    
    # Display running workflows
    all_workflows = ctx.local_context.get_all_workflows() if ctx else []
    if all_workflows:
        console.print_info("Active Workflows in current context:")
        for wf in all_workflows:
            wf_id = wf.get("workflow_id")
            console.print_message(f"  - {wf_id} {'(current)' if wf_id == ctx.current_workflow_id else ''}")

    console.print_info("\nType /<command> to run an action. Press Tab for auto-completion, or /exit to quit.")
    console.print_newline()


async def _get_command_from_prompt(registry: CommandRegistry) -> str:
    completer = SlashCommandCompleter(registry)
    prompt_session = PromptSession(completer=completer)
    
    while True:
        try:
            user_input = await prompt_session.prompt_async("Ein> ")
            if user_input.strip().startswith('/'):
                return user_input.strip()
            # Allow exiting without a slash
            if user_input.strip().lower() == 'exit':
                return '/exit'
            console.print_error("Invalid input. Please start your command with a '/' (e.g., /help).")
        except (KeyboardInterrupt, EOFError):
            return "/exit"

async def _create_new_workflow(config: HumanInLoopConfig, client: TemporalClient, session: SessionState, cmd_result: CommandResult) -> str:
    console.print_info(f"Task: {cmd_result.new_workflow_prompt[:100].strip()}...")
    workflow_id = await trigger_human_in_loop_workflow(
        user_prompt=cmd_result.new_workflow_prompt,
        config=config.temporal,
    )
    await start_workflow_execution(client, workflow_id, cmd_result.new_workflow_prompt)
    console.print_success("✓ Agent is now working on your task")

    context = session.get_current_context()
    if context and cmd_result.workflow_type:
        metadata: Any = None
        if cmd_result.workflow_type == "RCA":
            metadata = WorkflowMetadata(workflow_id=workflow_id, alert_fingerprint=cmd_result.alert_fingerprint, status="running")
            context.local_context.add_rca_workflow(metadata)
        elif cmd_result.workflow_type == "EnrichmentRCA":
            metadata = EnrichmentRCAMetadata(workflow_id=workflow_id, alert_fingerprint=cmd_result.alert_fingerprint, status="running", enrichment_context=cmd_result.enrichment_context or {})
            context.local_context.add_enrichment_rca_workflow(metadata)
        elif cmd_result.workflow_type == "CompactRCA":
            metadata = CompactMetadata(workflow_id=workflow_id, source_workflow_ids=cmd_result.source_workflow_ids or [], status="running")
            context.local_context.compact_rca = metadata
        
        if metadata:
            console.print_dim(f"Added {cmd_result.workflow_type} workflow to context")
            save_session_state(session)

    return workflow_id

async def _interactive_workflow_loop(config: HumanInLoopConfig, client: TemporalClient, registry: CommandRegistry, session: SessionState) -> str:
    workflow_id = session.current_workflow_id
    if not workflow_id:
        return "completed"

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
            if result is None:
                return "exit"
            if isinstance(result, UserAction):
                await provide_user_action(client, workflow_id, result)
            else: # CommandResult
                if result.should_switch and result.workflow_id:
                    session.switch_to(result.workflow_id)
                    return "switch"
                if result.should_create_new:
                    return "new_workflow"
                if result.should_complete:
                    await end_workflow(client, workflow_id)
                if result.should_exit: # Handle exit from within conversation loop
                    return "exit"
        elif status.state in ["completed", "failed"]:
            if status.state == "completed":
                _display_completed_status(status, workflow_id, config.temporal)
                await _update_workflow_result(client, workflow_id, session, status)
            else:
                _display_failed_status(status)
            save_session_state(session)
            return "completed"
    
    console.print_warning(f"Max iterations reached for workflow {workflow_id}.")
    return "completed"


async def _get_user_action(config: HumanInLoopConfig, client: TemporalClient, registry: CommandRegistry, session: SessionState):
    """Get user action via interactive prompt, handling slash commands."""
    completer = SlashCommandCompleter(registry)
    prompt_session = PromptSession(completer=completer)

    try:
        content = await prompt_session.prompt_async("You: ")
        if not content.strip().startswith('/'):
            return UserAction(action_type=ActionType.TEXT, content=content, metadata={})

        # It's a slash command, handle it
        result = await handle_command(content, registry, config, client, session)
        save_session_state(session)
        return result

    except (KeyboardInterrupt, EOFError):
        return None

async def _update_workflow_result(client: TemporalClient, workflow_id: str, session: SessionState, status: WorkflowStatus):
    context = session.get_current_context()
    if not context: return
    
    workflow_result = {"final_report": status.final_report} if status.final_report else None
    local_ctx = context.local_context

    if workflow_id in local_ctx.rca_workflows:
        local_ctx.rca_workflows[workflow_id].status = "completed"
        local_ctx.rca_workflows[workflow_id].result = workflow_result
    elif workflow_id in local_ctx.enrichment_rca_workflows:
        local_ctx.enrichment_rca_workflows[workflow_id].status = "completed"
        local_ctx.enrichment_rca_workflows[workflow_id].result = workflow_result
    elif local_ctx.compact_rca and local_ctx.compact_rca.workflow_id == workflow_id:
        local_ctx.compact_rca.status = "completed"
        local_ctx.compact_rca.result = workflow_result
    
    save_session_state(session)
    console.print_dim("Updated workflow result in context.")


def _display_executing_status(status: WorkflowStatus, iteration: int):
    console.print_dim(f"[Iteration {iteration}] Agent is executing...")
    if status.findings:
        console.print_info(f"Progress: {len(status.findings)} finding(s)")

def _display_awaiting_input_status(status: WorkflowStatus):
    if status.current_question:
        console.print_message(f"\nAgent: {status.current_question}")
    if status.suggested_mcp_tools:
        console.print_dim(f"Suggested tools: {', '.join(status.suggested_mcp_tools)}")
    console.print_newline()

def _display_completed_status(status: WorkflowStatus, workflow_id: str, temporal_config: Any):
    console.print_bold_success("\n✓ Workflow Completed!")
    if status.final_report:
        panel = Panel(status.final_report, title="Final Report", border_style="green")
        console.print_table(panel)
    console.print_info(f"Workflow ID: {workflow_id}")
    ui_host = temporal_config.host.split(':')[0]
    console.print_dim(f"View in Temporal UI: http://{ui_host}:8080/namespaces/{temporal_config.namespace}/workflows/{workflow_id}\n")

def _display_failed_status(status: WorkflowStatus):
    console.print_error("\n✗ Workflow Failed")
    if status.error_message:
        console.print_error(f"Error: {status.error_message}")
    console.print_newline()

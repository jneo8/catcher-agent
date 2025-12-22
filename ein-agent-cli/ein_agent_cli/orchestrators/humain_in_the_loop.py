"""Orchestrates human-in-the-loop workflow execution."""

import asyncio
from typing import Optional

import typer
from rich.panel import Panel
from rich.prompt import Prompt
from temporalio.client import Client as TemporalClient

from ein_agent_cli import console
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
    """Orchestrate human-in-the-loop workflow execution.

    This function:
    1. Triggers the workflow in Temporal
    2. Sends the initial query
    3. Polls for status updates
    4. Prompts user for input when agent needs help
    5. Displays final report when execution completes

    Args:
        config: Human-in-the-loop configuration

    Raises:
        typer.Exit: On error or completion
    """
    try:
        console.print_header("Ein Agent - Human-in-the-Loop Workflow\n")

        # Display configuration
        console.print_info(f"Query: {config.query}")
        console.print_dim(f"MCP servers: {config.mcp_servers}")
        console.print_dim(f"Temporal: {config.temporal.host}/{config.temporal.namespace}")
        console.print_newline()

        # Connect to Temporal
        client = await TemporalClient.connect(
            config.temporal.host,
            namespace=config.temporal.namespace,
        )

        # Trigger workflow
        workflow_id = await trigger_human_in_loop_workflow(
            query=config.query,
            mcp_servers=config.mcp_servers,
            config=config.temporal,
            workflow_id=config.workflow_id,
            context=config.context,
        )

        # Start execution
        console.print_info("Starting workflow execution...")
        await start_workflow_execution(
            client=client,
            workflow_id=workflow_id,
            query=config.query,
            mcp_servers=config.mcp_servers,
            context=config.context,
        )

        console.print_success("✓ Workflow execution started")
        console.print_newline()

        # Interactive workflow loop
        iteration = 0
        while iteration < config.max_iterations:
            iteration += 1

            # Poll for status
            await asyncio.sleep(config.poll_interval)
            status = await get_workflow_status(client, workflow_id)

            # Handle different states
            if status.state == "executing":
                _display_executing_status(status, iteration)

            elif status.state == "awaiting_input":
                _display_awaiting_input_status(status)

                # Get user input
                action = await _get_user_action(status)

                if action is None:
                    # User wants to end workflow
                    console.print_warning("Ending workflow...")
                    await end_workflow(client, workflow_id)
                    break

                # Send action to workflow
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

    except typer.Exit:
        raise
    except Exception as e:
        console.print_error(f"✗ Error: {e}")
        raise typer.Exit(1)


def _display_executing_status(status: WorkflowStatus, iteration: int) -> None:
    """Display executing status.

    Args:
        status: Current workflow status
        iteration: Current iteration number
    """
    console.print_dim(f"[Iteration {iteration}] Agent is executing...")
    if status.findings:
        console.print_info(f"Progress: {len(status.findings)} finding(s)")


def _display_awaiting_input_status(status: WorkflowStatus) -> None:
    """Display awaiting input status.

    Args:
        status: Current workflow status
    """
    console.print_newline()
    console.print_header("Agent needs your input")

    if status.current_question:
        panel = Panel(
            status.current_question,
            title="Question",
            border_style="yellow",
        )
        console.print_table(panel)

    if status.suggested_mcp_tools:
        console.print_info(f"Suggested MCP tools: {', '.join(status.suggested_mcp_tools)}")

    if status.findings:
        console.print_info("Current progress:")
        for i, finding in enumerate(status.findings, 1):
            console.print_dim(f"  {i}. {finding}")

    console.print_newline()


async def _get_user_action(status: WorkflowStatus) -> Optional[UserAction]:
    """Get user action via interactive prompt.

    Args:
        status: Current workflow status

    Returns:
        UserAction or None if user wants to end
    """
    # Check if this is a task completion (agent waiting for next task)
    is_task_complete = (
        status.current_question and
        ("task completed" in status.current_question.lower() or
         "would you like to continue" in status.current_question.lower())
    )

    if is_task_complete:
        console.print_newline()
        console.print_info("What would you like to do next?")
        console.print_message("  1) Provide a new task or follow-up question")
        console.print_message("  2) End workflow")
        console.print_newline()

        choice = Prompt.ask("Choose an action", choices=["1", "2"], default="1")

        if choice == "2":
            return None

        console.print_info("Enter your next task or question:")
        content = Prompt.ask("Task")

        return UserAction(
            action_type=ActionType.TEXT,
            content=content,
            metadata={},
        )
    else:
        # Regular human input request from agent
        console.print_info("Action options:")
        console.print_message("  1) Provide text response")
        console.print_message("  2) Provide tool result / data")
        console.print_message("  3) Approve or deny")
        console.print_message("  4) End workflow")
        console.print_newline()

        choice = Prompt.ask("Choose an action", choices=["1", "2", "3", "4"], default="1")

        if choice == "4":
            return None

        action_type_map = {
            "1": ActionType.TEXT,
            "2": ActionType.TOOL_RESULT,
            "3": ActionType.APPROVAL,
        }

        action_type = action_type_map[choice]

        # Get content based on action type
        if action_type == ActionType.TEXT:
            console.print_info("Enter your text response:")
            content = Prompt.ask("Response")
        elif action_type == ActionType.TOOL_RESULT:
            console.print_info("Enter the tool result (paste JSON or description):")
            content = Prompt.ask("Result")
        else:  # APPROVAL
            console.print_info("Approve or deny?")
            content = Prompt.ask("Decision", choices=["yes", "no"], default="yes")

        return UserAction(
            action_type=action_type,
            content=content,
            metadata={},
        )


def _display_completed_status(
    status: WorkflowStatus,
    workflow_id: str,
    temporal_config,
) -> None:
    """Display completed workflow status.

    Args:
        status: Current workflow status
        workflow_id: Workflow ID
        temporal_config: Temporal configuration
    """
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
    """Display failed workflow status.

    Args:
        status: Current workflow status
    """
    console.print_newline()
    console.print_error("✗ Workflow Failed")

    if status.error_message:
        console.print_error(f"Error: {status.error_message}")

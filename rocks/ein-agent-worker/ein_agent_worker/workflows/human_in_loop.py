"""Human-in-the-loop workflow for interactive task execution."""

import asyncio
from datetime import timedelta
from typing import Any, Dict, List, Optional

from agents import Agent, Runner
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.contrib import openai_agents


@workflow.defn
class HumanInLoopWorkflow:
    """Workflow that enables human-in-the-loop interaction for task execution.

    This workflow allows an agent to pause and request human input during execution.
    The agent can ask questions, request tool results, or seek approvals before
    proceeding with the next steps.

    States:
    - pending: Workflow created, waiting for start_execution
    - executing: Agent is actively working on the task
    - awaiting_input: Agent needs human input to continue
    - completed: Task completed successfully
    - failed: Task failed with error
    """

    def __init__(self) -> None:
        """Initialize workflow state."""
        self.state = "pending"
        self.query: Optional[str] = None
        self.mcp_server_names: List[str] = []
        self.context: Dict[str, str] = {}

        # State for human interaction
        self.current_question: Optional[str] = None
        self.suggested_mcp_tools: List[str] = []
        self.findings: List[str] = []
        self.final_report: Optional[str] = None
        self.error_message: Optional[str] = None

        # Action handling
        self.pending_action: Optional[Dict[str, Any]] = None
        self.action_received = asyncio.Event()

        # Workflow control
        self.should_end = False
        self.execution_started = False

    # NOTE: Using @workflow.signal instead of @workflow.update as a workaround
    # The Juju Temporal operator (v1.23.1) doesn't support workflow updates.
    # See: https://github.com/canonical/temporal-k8s-operator/issues/118
    # TODO: Change to @workflow.update when operator supports Temporal 1.25.0+
    @workflow.signal
    def start_execution(self, execution_input: Dict[str, Any]) -> None:
        """Start the workflow execution.

        Args:
            execution_input: Dict containing query, mcp_servers, and context
        """
        workflow.logger.info("Received start_execution signal")

        self.query = execution_input.get("query", "")
        self.mcp_server_names = execution_input.get("mcp_servers", [])
        self.context = execution_input.get("context", {})
        self.execution_started = True

        workflow.logger.info(f"Execution started with query: {self.query}")
        workflow.logger.info(f"MCP servers: {self.mcp_server_names}")

    # NOTE: Using @workflow.signal instead of @workflow.update as a workaround
    # The Juju Temporal operator (v1.23.1) doesn't support workflow updates.
    # See: https://github.com/canonical/temporal-k8s-operator/issues/118
    # TODO: Change to @workflow.update when operator supports Temporal 1.25.0+
    @workflow.signal
    def provide_action(self, action: Dict[str, Any]) -> None:
        """Provide user action in response to agent's question.

        Args:
            action: Dict containing action_type, content, and metadata
        """
        workflow.logger.info(f"Received user action: {action.get('action_type')}")

        self.pending_action = action
        self.action_received.set()

    @workflow.query
    def get_status(self) -> Dict[str, Any]:
        """Get current workflow status.

        Returns:
            Status dict with state, question, suggestions, findings, etc.
        """
        return {
            "state": self.state,
            "current_question": self.current_question,
            "suggested_mcp_tools": self.suggested_mcp_tools,
            "findings": self.findings,
            "final_report": self.final_report,
            "error_message": self.error_message,
        }

    @workflow.signal
    def end_workflow(self) -> None:
        """Signal to end the workflow gracefully."""
        workflow.logger.info("Received end_workflow signal")
        self.should_end = True

    @workflow.run
    async def run(self) -> str:
        """Main workflow execution.

        Returns:
            Final report or result
        """
        workflow.logger.info("HumanInLoopWorkflow started")

        try:
            # Wait for execution to start
            await workflow.wait_condition(lambda: self.execution_started)

            if self.should_end:
                self.state = "completed"
                return "Workflow ended before execution"

            # Load MCP servers from memo (fallback to empty if not set)
            memo_mcp_servers = workflow.memo_value("mcp_servers", default=[])
            # Use mcp_servers from start_execution if available, otherwise from memo
            mcp_server_names = self.mcp_server_names if self.mcp_server_names else memo_mcp_servers

            # Configure MCP activities to fail fast (no retries)
            # This allows errors to surface immediately to the agent for user interaction
            mcp_activity_config = workflow.ActivityConfig(
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(maximum_attempts=1),  # Fail fast - no retries
            )

            mcp_servers = []
            for name in mcp_server_names:
                try:
                    mcp_servers.append(
                        openai_agents.workflow.stateless_mcp_server(
                            name,
                            config=mcp_activity_config,
                        )
                    )
                    workflow.logger.info(f"Loaded MCP server: {name}")
                except Exception as e:
                    workflow.logger.warning(f"Failed to load MCP server '{name}': {e}")

            # Transition to executing state
            self.state = "executing"

            # Build initial prompt with context
            initial_prompt = self._build_initial_prompt()

            # Execute the task with human-in-the-loop support
            result = await self._execute_with_human_loop(initial_prompt, mcp_servers)

            # Set final state
            self.state = "completed"
            self.final_report = result

            workflow.logger.info("Workflow completed successfully")
            return result

        except Exception as e:
            workflow.logger.error(f"Workflow failed: {e}")
            self.state = "failed"
            self.error_message = str(e)
            raise

    def _build_initial_prompt(self) -> str:
        """Build the initial prompt for the agent.

        Returns:
            Formatted prompt string
        """
        prompt_parts = [f"Task: {self.query}"]

        if self.context:
            prompt_parts.append("\nContext:")
            for key, value in self.context.items():
                prompt_parts.append(f"  {key}: {value}")

        return "\n".join(prompt_parts)

    async def _execute_with_human_loop(
        self,
        initial_prompt: str,
        mcp_servers: List[Any],
    ) -> str:
        """Execute the task with human-in-the-loop support.

        Args:
            initial_prompt: Initial task prompt
            mcp_servers: List of MCP server instances

        Returns:
            Final result or report
        """
        # Create the agent with human-in-the-loop instructions
        agent_instructions = """You are an AI assistant in a continuous interactive session with a user.

You have access to MCP tools to help with operational tasks. This is an ongoing conversation where:
- The user will give you tasks to complete
- You execute the tasks using available MCP tools
- You report results back to the user
- The user may ask follow-up questions or give you new tasks
- The conversation continues until the user explicitly decides to end it

Your workflow:
1. Read the user's request carefully
2. Use MCP tools to gather necessary information or perform actions
3. When you need clarification or approval, ask the user (using NEED_HUMAN_INPUT format)
4. When you've completed a task, report the results (using TASK_COMPLETE format)
5. The user will either provide a new task or end the session

CRITICAL - HANDLING MCP TOOL FAILURES:
When an MCP tool call fails (authentication error, connection error, etc.), DO NOT retry endlessly.
Instead, immediately ask the user for help using the NEED_HUMAN_INPUT format.
Explain what tool failed, why it failed, and ask the user to either:
- Provide the data manually
- Fix the authentication/connection issue
- Skip this data source and continue with what you have
- Try an alternative approach

Response Formats:

When you need human input:
{
    "type": "NEED_HUMAN_INPUT",
    "question": "Your specific question (e.g., 'MCP tool X failed with error Y. Would you like to provide the data manually or skip this step?')",
    "suggested_tools": ["tool1", "tool2"],
    "findings_so_far": ["finding1", "finding2"]
}

When you complete a task:
{
    "type": "TASK_COMPLETE",
    "report": "Your results/findings here. Be clear and concise.",
    "findings": ["finding1", "finding2"]
}

Remember: After completing a task, the user will decide whether to continue with more tasks.
Stay ready for follow-up questions and new requests."""

        agent = Agent(
            name="HumanInLoopAgent",
            instructions=agent_instructions,
            model="gemini/gemini-2.5-flash",
            mcp_servers=mcp_servers,
        )

        # Conversation history for context
        conversation_history = [initial_prompt]
        max_iterations = 50

        for iteration in range(max_iterations):
            if self.should_end:
                workflow.logger.info("Ending workflow due to signal")
                return "Workflow ended by user request"

            # Run the agent with current conversation
            workflow.logger.info(f"Agent iteration {iteration + 1}")
            current_prompt = "\n\n---\n\n".join(conversation_history)

            try:
                result = await Runner.run(agent, input=current_prompt)
                agent_response = result.final_output
                workflow.logger.info(f"Agent response: {agent_response[:200]}...")
            except Exception as e:
                # Handle MCP activity failures gracefully
                # When MCP tools fail (auth errors, connection errors, etc.),
                # we want the agent to see the error and ask the user for help
                # instead of failing the entire workflow
                error_type = type(e).__name__
                error_msg = str(e)
                workflow.logger.warning(f"Agent execution failed with {error_type}: {error_msg}")

                # Convert the error into a system message that the agent can respond to
                error_prompt = f"""
SYSTEM ERROR: An MCP tool execution failed with the following error:

Error Type: {error_type}
Error Message: {error_msg}

You must respond using the NEED_HUMAN_INPUT format to ask the user for help.
Explain what failed and provide options for how to proceed.
"""
                conversation_history.append(error_prompt)

                # Continue to next iteration so agent can respond to the error
                continue

            # Parse agent response to determine next action
            import json
            try:
                response_data = json.loads(agent_response)
                response_type = response_data.get("type")

                if response_type == "TASK_COMPLETE":
                    # Task is complete - but don't end workflow automatically
                    # Instead, ask the user if they want to continue
                    self.state = "awaiting_input"
                    self.findings = response_data.get("findings", [])
                    report = response_data.get("report", agent_response)
                    self.current_question = f"Task completed!\n\n{report}\n\nWould you like to continue with another task or end the workflow?"
                    self.suggested_mcp_tools = []

                    workflow.logger.info("Task complete, asking user if they want to continue")

                    # Wait for user action
                    self.action_received.clear()
                    await self.action_received.wait()

                    if self.should_end:
                        return report

                    # Process the user action
                    action = self.pending_action
                    action_type = action.get("action_type")
                    content = action.get("content")

                    workflow.logger.info(f"User wants to continue: {content[:100]}...")

                    # Add user's new request to conversation
                    conversation_history.append(f"AGENT: {agent_response}")
                    conversation_history.append(f"User: {content}")

                    # Reset state to executing
                    self.state = "executing"
                    self.current_question = None
                    self.pending_action = None

                elif response_type == "NEED_HUMAN_INPUT":
                    # Agent needs human input
                    self.state = "awaiting_input"
                    self.current_question = response_data.get("question")
                    self.suggested_mcp_tools = response_data.get("suggested_tools", [])
                    self.findings = response_data.get("findings_so_far", [])

                    workflow.logger.info(f"Waiting for human input: {self.current_question}")

                    # Wait for user action
                    self.action_received.clear()
                    await self.action_received.wait()

                    if self.should_end:
                        return "Workflow ended by user request"

                    # Process the user action
                    action = self.pending_action
                    action_type = action.get("action_type")
                    content = action.get("content")

                    workflow.logger.info(f"Received action type: {action_type}, content: {content[:100]}...")

                    # Add user response to conversation
                    if action_type == "text":
                        user_message = f"User response: {content}"
                    elif action_type == "tool_result":
                        user_message = f"User provided tool result:\n{content}"
                    elif action_type == "approval":
                        user_message = f"User decision: {content}"
                    else:
                        user_message = f"User input: {content}"

                    conversation_history.append(f"AGENT: {agent_response}")
                    conversation_history.append(user_message)

                    # Reset state to executing
                    self.state = "executing"
                    self.current_question = None
                    self.pending_action = None

                else:
                    # Unknown response type, treat as regular output
                    conversation_history.append(f"AGENT: {agent_response}")

            except json.JSONDecodeError:
                # Not JSON, treat as regular agent output
                # Check if it looks like a completion
                if any(keyword in agent_response.lower() for keyword in ["complete", "finished", "done", "summary", "conclusion"]):
                    # Looks like a final report - but ask user if they want to continue
                    self.state = "awaiting_input"
                    self.current_question = f"Agent report:\n\n{agent_response}\n\nWould you like to continue with another task or end the workflow?"
                    self.suggested_mcp_tools = []

                    workflow.logger.info("Agent provided completion message, asking user if they want to continue")

                    # Wait for user action
                    self.action_received.clear()
                    await self.action_received.wait()

                    if self.should_end:
                        return agent_response

                    # Process the user action
                    action = self.pending_action
                    content = action.get("content")

                    workflow.logger.info(f"User wants to continue: {content[:100]}...")

                    # Add user's new request to conversation
                    conversation_history.append(f"AGENT: {agent_response}")
                    conversation_history.append(f"User: {content}")

                    # Reset state to executing
                    self.state = "executing"
                    self.current_question = None
                    self.pending_action = None
                else:
                    # Continue conversation
                    conversation_history.append(f"AGENT: {agent_response}")

        # Max iterations reached
        workflow.logger.warning(f"Max iterations ({max_iterations}) reached")
        return f"Task incomplete after {max_iterations} iterations. Last output:\n{agent_response}"

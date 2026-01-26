import logging
from datetime import timedelta
from typing import Optional, Any

from agents import RunHooks, Agent, RunContextWrapper
from openai.types.responses import (
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseFunctionToolCall
)
from temporalio import workflow

logger = logging.getLogger(__name__)

class DSPyRecordingHooks(RunHooks):
    """Hooks to record agent interactions for DSPy training."""

    def __init__(self):
        self._current_input = {}

    async def on_llm_start(
        self,
        context: RunContextWrapper,
        agent: Agent,
        system_prompt: Optional[str],
        input_items: list[Any],
    ) -> None:
        """Capture input before LLM execution."""
        # Convert input items to a string representation for the 'input_context'
        # input_items is a list of dicts (OpenAI format)
        input_text = ""
        for item in input_items:
            role = item.get("role", "unknown")
            content = item.get("content", "")
            if isinstance(content, str):
                input_text += f"[{role}]: {content}\n"
            elif isinstance(content, list):
                # Handle multi-part content
                parts = []
                for part in content:
                    if isinstance(part, dict) and "text" in part:
                        parts.append(part["text"])
                input_text += f"[{role}]: {' '.join(parts)}\n"
        
        self._current_input[agent.name] = input_text

    async def on_llm_end(
        self,
        context: RunContextWrapper,
        agent: Agent,
        response: Any,
    ) -> None:
        """Record the interaction after LLM execution."""
        if agent.name not in self._current_input:
            return

        input_text = self._current_input.pop(agent.name)
        
        # Extract output text and tool calls
        output_text = ""
        tools_called = []
        handoffs_made = []

        for item in response.output:
            if isinstance(item, ResponseOutputMessage):
                for content in item.content:
                    if isinstance(content, ResponseOutputText):
                        output_text += content.text
            elif isinstance(item, ResponseFunctionToolCall):
                tool_name = item.name
                if tool_name.startswith("transfer_to_"):
                    handoffs_made.append(tool_name.replace("transfer_to_", ""))
                else:
                    tools_called.append(tool_name)

        # Skip recording if empty output and no tools (rare)
        if not output_text and not tools_called and not handoffs_made:
            return

        # Extract shared context if available
        shared_context_str = ""
        # Context is generic, we expect a dict with 'shared_context' key
        if context.context and isinstance(context.context, dict):
            shared_ctx_obj = context.context.get("shared_context")
            if shared_ctx_obj and hasattr(shared_ctx_obj, "format_summary"):
                shared_context_str = shared_ctx_obj.format_summary()
            
            # Also capture alert context if available (for single alert investigators)
            # It might be in the agent name or passed in context
            
        # Prepare interaction object
        interaction_data = {
            "agent_name": agent.name,
            "input_context": input_text,
            "agent_output": output_text,
            "tools_called": tools_called,
            "handoffs_made": handoffs_made,
            "outcome": "success",
            "shared_context_before": shared_context_str,
        }

        try:
            await workflow.execute_activity(
                "record_interaction_activity",
                args=[interaction_data],
                start_to_close_timeout=timedelta(seconds=10),
            )
        except Exception as e:
            # Don't fail the workflow if recording fails
            workflow.logger.warn(f"Failed to record interaction for {agent.name}: {e}")

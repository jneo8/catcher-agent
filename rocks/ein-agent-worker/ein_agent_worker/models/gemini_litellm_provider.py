"""Custom LiteLLM provider with Gemini compatibility fixes.

Gemini API has a strict requirement that conversations must end with a user message.
This becomes problematic during agent handoffs in the OpenAI Agents SDK, where the
SDK prepends conversation history as an assistant message when transferring context
between agents.

For example, during a handoff from Investigator -> ComputeSpecialist, the SDK sends:
    [
        {"role": "assistant", "content": "For context, here is the conversation..."}
    ]

This causes Gemini to reject the request with:
    "Please ensure that single turn requests end with a user role or the role field is empty."

This module provides a custom LiteLLM provider that detects this situation and
automatically appends a synthetic user message to satisfy Gemini's requirements.
"""

import asyncio
import logging
import random
from typing import Any

import litellm
from agents import Model
from agents.extensions.models.litellm_model import LitellmModel
from agents.extensions.models.litellm_provider import LitellmProvider
from agents.models.interface import ModelProvider

logger = logging.getLogger(__name__)


class GeminiCompatibleLitellmModel(LitellmModel):
    """LiteLLM model with Gemini-specific message handling.

    This model intercepts the message list before sending to the API and ensures
    that conversations always end with a user message to satisfy Gemini's API
    requirements. This fix is only applied for Gemini models.
    """

    async def _fetch_response(
        self,
        system_instructions: str | None,
        input: str | list[Any],
        model_settings: Any,
        tools: list[Any],
        output_schema: Any | None,
        handoffs: list[Any],
        span: Any,
        tracing: Any,
        stream: bool = False,
        prompt: Any | None = None,
    ) -> Any:
        """Override to fix message ordering and handle rate limits for Gemini.

        Gemini requires that conversations end with a user message. During agent
        handoffs, the OpenAI Agents SDK sends conversation history as an assistant
        message, which violates this requirement.

        This method also implements an internal retry loop for 429 RateLimitErrors
        to handle Gemini's API quotas more gracefully.
        """
        # Only apply the fix for Gemini models (e.g., "gemini/gemini-2.0-flash")
        is_gemini = self.model.startswith("gemini/") or self.model.startswith("gemini-")

        if is_gemini and isinstance(input, list) and input:
            # Get the last message in the conversation
            last_message = input[-1]

            # Check if it's an assistant message (could be a dict or Pydantic model)
            # Use hasattr to safely handle both dict and object-like messages
            if hasattr(last_message, "get") and last_message.get("role") == "assistant":
                # Append a synthetic user message to satisfy Gemini's requirements
                # This message prompts the model to continue based on the handoff context
                input = list(input) + [{
                    "role": "user",
                    "content": "Please continue with the task based on the context above."
                }]

        # Implement retry loop for 429s
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Call the parent implementation with the (possibly modified) input
                return await super()._fetch_response(
                    system_instructions=system_instructions,
                    input=input,
                    model_settings=model_settings,
                    tools=tools,
                    output_schema=output_schema,
                    handoffs=handoffs,
                    span=span,
                    tracing=tracing,
                    stream=stream,
                    prompt=prompt,
                )
            except litellm.RateLimitError:
                # Catch RateLimitError (429) specifically
                if attempt < max_retries - 1:
                    # Gemini suggests 15s in the error message, we wait a bit longer with jitter
                    wait_time = 20 + (attempt * 10) + random.uniform(0, 10)
                    logger.warning(
                        f"Gemini Rate Limit (429) hit for model {self.model} (attempt {attempt+1}/{max_retries}). "
                        f"Retrying in {wait_time:.1f}s..."
                    )
                    await asyncio.sleep(wait_time)
                    continue
                
                # Re-raise if we've exhausted retries
                raise


class GeminiCompatibleLitellmProvider(ModelProvider):
    """LiteLLM provider with Gemini compatibility fixes.

    Use this provider instead of LitellmProvider when working with Gemini
    models to avoid the "single turn requests end with a user role" error
    that occurs during agent handoffs.

    Example usage:
        run_config = RunConfig(model_provider=GeminiCompatibleLitellmProvider())

    Note: This provider works transparently with non-Gemini models as well,
    so it's safe to use as a drop-in replacement for LitellmProvider.
    """

    def __init__(self) -> None:
        # Keep a reference to the base provider (not currently used, but may be
        # useful for future enhancements like delegating non-Gemini models)
        self._base_provider = LitellmProvider()

    def get_model(self, model_name: str | None) -> Model:
        """Get a Gemini-compatible LiteLLM model.

        Args:
            model_name: The model name (e.g., "gemini/gemini-2.0-flash")

        Returns:
            A GeminiCompatibleLitellmModel instance that handles Gemini's
            message ordering requirements.

        Raises:
            ValueError: If model_name is None.
        """
        if model_name is None:
            raise ValueError("model_name is required for GeminiCompatibleLitellmProvider")

        # Return our custom model that handles Gemini's message requirements
        return GeminiCompatibleLitellmModel(model=model_name)

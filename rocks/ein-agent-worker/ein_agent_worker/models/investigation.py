"""Data models for investigation using Pydantic."""

from typing import Optional

from pydantic import BaseModel


class InvestigationConfig(BaseModel):
    """Configuration for investigation."""

    model: str = "gemini/gemini-2.5-flash"
    """LLM model to use."""

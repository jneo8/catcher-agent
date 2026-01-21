"""Data models for Human-in-the-Loop workflow."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class WorkflowStatus(str, Enum):
    """Workflow lifecycle states."""

    PENDING = "pending"  # Created, waiting for first message
    RUNNING = "running"  # Agent processing / waiting for user
    COMPLETED = "completed"  # Investigation finished with report
    ENDED = "ended"  # User terminated early


class ChatMessage(BaseModel):
    """A message in the conversation."""

    role: str = Field(description="Message role: 'user' or 'assistant'")
    content: str = Field(description="Message content")
    timestamp: datetime | None = Field(default=None, description="Message timestamp (set by workflow)")
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentSelectionRequest(BaseModel):
    """Request for user to select an agent from available options."""

    from_agent: str = Field(description="Agent requesting the handoff")
    suggested_agent: str = Field(description="LLM's suggested agent to hand off to")
    reason: str = Field(description="Reason for the handoff")
    available_agents: list[str] = Field(description="List of all available agents to choose from")


class WorkflowState(BaseModel):
    """Current workflow state - returned to clients via queries."""

    status: WorkflowStatus = WorkflowStatus.PENDING
    messages: list[ChatMessage] = Field(default_factory=list)
    findings: dict[str, Any] = Field(default_factory=dict)
    pending_question: str | None = None  # When agent called ask_user
    pending_tool_call: dict | None = None  # When agent wants to call a tool
    pending_handoff: dict | None = None  # When agent wants to hand off
    pending_agent_selection: AgentSelectionRequest | None = None  # When user needs to select agent
    last_fetched_alerts: list[dict] = Field(default_factory=list)


class HITLConfig(BaseModel):
    """Configuration for human-in-the-loop workflow."""

    model: str = Field(
        default="gemini/gemini-2.5-flash",
        description="LLM model to use",
    )
    alertmanager_url: str | None = Field(
        default=None,
        description="Alertmanager URL for fetching alerts",
    )
    max_turns: int = Field(
        default=50,
        ge=1,
        description="Maximum agent turns before stopping",
    )

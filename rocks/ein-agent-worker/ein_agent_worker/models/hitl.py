"""Data models for Human-in-the-Loop workflow."""

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

# Default model used when EIN_AGENT_MODEL environment variable is not set
DEFAULT_MODEL = "gemini/gemini-2.5-flash"


# =============================================================================
# Approval Models
# =============================================================================

class ApprovalPolicy(str, Enum):
    """Policy for tool call approval.

    - NEVER: Never require approval (trust all operations)
    - ALWAYS: Always require approval for every operation
    - WRITE_OPERATIONS: Require approval only for write operations (POST, PUT, PATCH, DELETE)
    - READ_ONLY: Require approval only for read operations (GET, LIST)
    """
    NEVER = "never"
    ALWAYS = "always"
    WRITE_OPERATIONS = "write_operations"
    READ_ONLY = "read_only"

    @classmethod
    def default(cls) -> "ApprovalPolicy":
        """Default policy requires approval for all operations (safest)."""
        return cls.ALWAYS


class WorkflowInterruption(BaseModel):
    """Represents a workflow interruption requiring human intervention.

    This unified model handles all types of interruptions following the OpenAI SDK pattern.
    """

    id: str = Field(description="Unique identifier for this interruption")
    type: Literal["tool_approval", "agent_selection", "human_input"] = Field(
        description="Type of interruption"
    )
    agent_name: str = Field(description="Name of the agent requesting the interruption")
    tool_name: str | None = Field(default=None, description="Tool name for tool_approval type")
    arguments: dict[str, Any] | None = Field(default=None, description="Tool arguments for tool_approval type")
    question: str | None = Field(default=None, description="Question for human_input type")
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context (risk_level, operation_description, etc.)"
    )
    timestamp: datetime | None = Field(default=None, description="When the interruption was created")


class ApprovalDecision(BaseModel):
    """Represents a user's approval decision."""

    interruption_id: str = Field(description="ID of the interruption being decided")
    approved: bool = Field(description="Whether the operation was approved")
    always: bool = Field(
        default=False,
        description="If True, cache this decision for future similar operations"
    )
    reason: str | None = Field(default=None, description="Optional reason for the decision")


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

    # Unified interruptions (OpenAI SDK pattern)
    interruptions: list[WorkflowInterruption] = Field(
        default_factory=list,
        description="Pending interruptions requiring human intervention"
    )

    # Sticky approvals: maps tool names to approval status
    # When user chooses "approve always" or "reject always", we store the decision here
    # Format: "tool_name" -> True (approved) or False (rejected)
    sticky_approvals: dict[str, bool] = Field(
        default_factory=dict,
        description="Sticky approval decisions (always approve/reject)"
    )

    last_fetched_alerts: list[dict] = Field(default_factory=list)


class HITLConfig(BaseModel):
    """Configuration for human-in-the-loop workflow."""

    model: str = Field(
        default=DEFAULT_MODEL,
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


class WorkflowEventType(str, Enum):
    """Types of events that can be sent to the workflow."""

    MESSAGE = "message"
    CONFIRMATION = "confirmation"
    SELECTION = "selection"
    STOP = "stop"


class WorkflowEvent(BaseModel):
    """An event sent to the workflow."""

    type: WorkflowEventType
    payload: Any = None
    timestamp: datetime | None = Field(default=None, description="Event timestamp (set by workflow)")

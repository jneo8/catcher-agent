"""Pydantic models for CLI configuration and workflow parameters."""

import os
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class AlertmanagerAlertStatus(BaseModel):
    """Alertmanager alert status."""

    state: str = Field(
        description="Alert state (firing/resolved)"
    )
    silenced_by: List[str] = Field(
        default_factory=list,
        description="List of silence IDs"
    )
    inhibited_by: List[str] = Field(
        default_factory=list,
        description="List of inhibiting alerts"
    )


class AlertmanagerAlert(BaseModel):
    """Alertmanager API alert format."""

    labels: Dict[str, str] = Field(
        default_factory=dict,
        description="Alert labels"
    )
    annotations: Dict[str, str] = Field(
        default_factory=dict,
        description="Alert annotations"
    )
    status: AlertmanagerAlertStatus = Field(
        description="Alert status"
    )
    startsAt: str = Field(
        description="Alert start time (ISO8601)"
    )
    endsAt: str = Field(
        default="0001-01-01T00:00:00Z",
        description="Alert end time (ISO8601)"
    )
    fingerprint: str = Field(
        default="",
        description="Alert fingerprint"
    )
    generatorURL: str = Field(
        default="",
        description="Generator URL"
    )

    @field_validator('startsAt', 'endsAt')
    @classmethod
    def validate_datetime(cls, v: str) -> str:
        """Validate datetime format."""
        if v and v != "0001-01-01T00:00:00Z":
            try:
                # Just check if it's parseable
                datetime.fromisoformat(v.replace('Z', '+00:00'))
            except ValueError:
                # If not parseable, that's okay - just pass through
                pass
        return v


class WorkflowAlert(BaseModel):
    """Workflow alert format (simplified from Alertmanager format)."""

    alertname: str = Field(
        description="Alert name from labels"
    )
    status: str = Field(
        description="Alert status (firing/resolved)"
    )
    labels: Dict[str, str] = Field(
        default_factory=dict,
        description="Alert labels"
    )
    annotations: Dict[str, str] = Field(
        default_factory=dict,
        description="Alert annotations"
    )
    starts_at: str = Field(
        description="Alert start time"
    )
    ends_at: str = Field(
        default="",
        description="Alert end time"
    )
    fingerprint: str = Field(
        default="",
        description="Alert fingerprint"
    )
    generator_url: str = Field(
        default="",
        description="Generator URL"
    )

    @classmethod
    def from_alertmanager_alert(cls, am_alert: AlertmanagerAlert) -> "WorkflowAlert":
        """Convert from Alertmanager alert format.

        Args:
            am_alert: Alertmanager alert

        Returns:
            WorkflowAlert instance
        """
        return cls(
            alertname=am_alert.labels.get("alertname", "unknown"),
            status=am_alert.status.state,
            labels=am_alert.labels,
            annotations=am_alert.annotations,
            starts_at=am_alert.startsAt,
            ends_at=am_alert.endsAt,
            fingerprint=am_alert.fingerprint,
            generator_url=am_alert.generatorURL,
        )


# Configuration models

class TemporalConfig(BaseModel):
    """Temporal service configuration."""

    host: str = Field(
        default_factory=lambda: os.getenv("TEMPORAL_HOST", "localhost:7233"),
        description="Temporal server host:port"
    )
    namespace: str = Field(
        default_factory=lambda: os.getenv("TEMPORAL_NAMESPACE", "default"),
        description="Temporal namespace"
    )
    queue: str = Field(
        default_factory=lambda: os.getenv("TEMPORAL_QUEUE", "ein-agent-queue"),
        description="Temporal task queue name"
    )

    @field_validator('host')
    @classmethod
    def validate_host(cls, v: str) -> str:
        """Validate host:port format."""
        if ':' not in v:
            raise ValueError("Host must be in format 'host:port'")
        return v


class AlertFilterConfig(BaseModel):
    """Alert filtering configuration."""

    include: Optional[List[str]] = Field(
        default=None,
        description="Alert names or fingerprints to include (whitelist)"
    )
    blacklist: Optional[List[str]] = Field(
        default=["Watchdog"],
        description="Alert names to exclude (blacklist)"
    )
    status: str = Field(
        default="firing",
        description="Filter alerts by status"
    )

    @field_validator('status')
    @classmethod
    def validate_status(cls, v: str) -> str:
        """Validate status value."""
        valid_statuses = ['firing', 'resolved', 'all']
        if v not in valid_statuses:
            raise ValueError(f"Status must be one of {valid_statuses}")
        return v

    @field_validator('blacklist')
    @classmethod
    def validate_blacklist(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Handle blacklist disable (empty string or empty list)."""
        if v is not None and (len(v) == 0 or "" in v):
            return None
        return v


class IncidentWorkflowConfig(BaseModel):
    """Incident workflow configuration."""

    alertmanager_url: str = Field(
        default="http://localhost:9093",
        description="Alertmanager URL"
    )
    mcp_servers: List[str] = Field(
        default=["kubernetes", "grafana"],
        description="MCP server names to use"
    )
    workflow_id: Optional[str] = Field(
        default=None,
        description="Custom workflow ID"
    )
    dry_run: bool = Field(
        default=False,
        description="If True, don't trigger workflow"
    )
    show_labels: bool = Field(
        default=False,
        description="If True, show labels in alert table"
    )
    no_prompt: bool = Field(
        default=False,
        description="If True, skip confirmation prompt"
    )
    temporal: TemporalConfig = Field(
        default_factory=TemporalConfig,
        description="Temporal configuration"
    )
    filters: AlertFilterConfig = Field(
        default_factory=AlertFilterConfig,
        description="Alert filtering configuration"
    )

    @field_validator('alertmanager_url')
    @classmethod
    def validate_alertmanager_url(cls, v: str) -> str:
        """Validate Alertmanager URL format."""
        if not v.startswith(('http://', 'https://')):
            raise ValueError("Alertmanager URL must start with http:// or https://")
        return v

    @field_validator('mcp_servers')
    @classmethod
    def split_comma_separated_servers(cls, v: List[str]) -> List[str]:
        """Split comma-separated server names in list items.

        This handles cases where users pass --mcp-server kubernetes,grafana
        instead of --mcp-server kubernetes --mcp-server grafana
        """
        if not v:
            return v

        result = []
        for item in v:
            # Split by comma and strip whitespace
            servers = [s.strip() for s in item.split(',') if s.strip()]
            result.extend(servers)
        return result

    @classmethod
    def from_cli_args(
        cls,
        alertmanager_url: str,
        include: Optional[List[str]],
        mcp_servers: List[str],
        temporal_host: Optional[str],
        temporal_namespace: Optional[str],
        temporal_queue: Optional[str],
        workflow_id: Optional[str],
        status: str,
        blacklist: Optional[List[str]],
        dry_run: bool,
        show_labels: bool,
        no_prompt: bool,
    ) -> "IncidentWorkflowConfig":
        """Create IncidentWorkflowConfig from CLI arguments.

        Args:
            alertmanager_url: Alertmanager URL
            include: Alert names or fingerprints to include (whitelist)
            mcp_servers: MCP server names to use
            temporal_host: Temporal server host:port
            temporal_namespace: Temporal namespace
            temporal_queue: Temporal task queue
            workflow_id: Custom workflow ID
            status: Filter alerts by status
            blacklist: Alert names to exclude
            dry_run: If True, don't trigger workflow
            show_labels: If True, show labels in alert table
            no_prompt: If True, skip confirmation prompt

        Returns:
            IncidentWorkflowConfig instance
        """
        temporal_config = TemporalConfig()
        if temporal_host is not None:
            temporal_config.host = temporal_host
        if temporal_namespace is not None:
            temporal_config.namespace = temporal_namespace
        if temporal_queue is not None:
            temporal_config.queue = temporal_queue

        filter_config = AlertFilterConfig(
            include=include,
            blacklist=blacklist,
            status=status,
        )

        return cls(
            alertmanager_url=alertmanager_url,
            mcp_servers=mcp_servers,
            workflow_id=workflow_id,
            dry_run=dry_run,
            show_labels=show_labels,
            no_prompt=no_prompt,
            temporal=temporal_config,
            filters=filter_config,
        )


class AlertmanagerQueryParams(BaseModel):
    """Parameters for querying Alertmanager."""

    url: str = Field(
        description="Alertmanager base URL"
    )
    timeout: int = Field(
        default=10,
        description="HTTP timeout in seconds",
        ge=1,
        le=300
    )

    @field_validator('url')
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate Alertmanager URL format."""
        if not v.startswith(('http://', 'https://')):
            raise ValueError("URL must start with http:// or https://")
        return v


class AlertFilterParams(BaseModel):
    """Parameters for filtering alerts."""

    alerts: List[AlertmanagerAlert] = Field(
        description="List of alerts to filter"
    )
    whitelist: Optional[List[str]] = Field(
        default=None,
        description="Alert names or fingerprints to include (whitelist)"
    )
    blacklist: Optional[List[str]] = Field(
        default=None,
        description="Alert names to exclude (blacklist)"
    )
    status_filter: Optional[str] = Field(
        default=None,
        description="Filter by status (firing/resolved). None = no filter"
    )


class TemporalWorkflowParams(BaseModel):
    """Parameters for triggering Temporal workflow."""

    alerts: List[AlertmanagerAlert] = Field(
        description="List of alerts to investigate"
    )
    config: TemporalConfig = Field(
        description="Temporal configuration"
    )
    mcp_servers: List[str] = Field(
        description="List of MCP server names"
    )
    workflow_id: Optional[str] = Field(
        default=None,
        description="Custom workflow ID"
    )


# Human-in-the-loop workflow models

class ActionType(str, Enum):
    """Type of user action in human-in-the-loop workflow."""

    TEXT = "text"  # User provides text answer or clarification
    TOOL_RESULT = "tool_result"  # User provides MCP tool output or data
    APPROVAL = "approval"  # User approves or denies (yes/no decision)


class UserAction(BaseModel):
    """User action during workflow execution."""

    action_type: ActionType = Field(
        description="Type of action: text, tool_result, or approval"
    )
    content: str = Field(
        description="Action content (answer, tool output, or yes/no)"
    )
    metadata: Dict[str, str] = Field(
        default_factory=dict,
        description="Additional metadata for the action"
    )


class WorkflowStatus(BaseModel):
    """Current status of human-in-the-loop workflow."""

    state: str = Field(
        description="Current state: pending, executing, awaiting_input, completed, failed"
    )
    current_question: Optional[str] = Field(
        default=None,
        description="Current question waiting for user input"
    )
    suggested_mcp_tools: List[str] = Field(
        default_factory=list,
        description="MCP tools the agent suggests using"
    )
    findings: List[str] = Field(
        default_factory=list,
        description="Findings or progress so far"
    )
    final_report: Optional[str] = Field(
        default=None,
        description="Final report (when completed)"
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Error message if workflow failed"
    )

    @field_validator('state')
    @classmethod
    def validate_state(cls, v: str) -> str:
        """Validate state value."""
        valid_states = ['pending', 'executing', 'awaiting_input', 'completed', 'failed']
        if v not in valid_states:
            raise ValueError(f"State must be one of {valid_states}")
        return v


class HumanInLoopConfig(BaseModel):
    """Configuration for human-in-the-loop workflow."""

    query: str = Field(
        default="",
        description="Query or task description (optional, can be provided interactively)"
    )
    mcp_servers: List[str] = Field(
        default=[],  # Empty by default - add MCP servers when available
        description="MCP server names to use"
    )
    workflow_id: Optional[str] = Field(
        default=None,
        description="Custom workflow ID"
    )
    poll_interval: int = Field(
        default=2,
        description="Status poll interval in seconds",
        ge=1,
        le=60
    )
    max_iterations: int = Field(
        default=50,
        description="Maximum workflow iterations",
        ge=1,
        le=200
    )
    temporal: TemporalConfig = Field(
        default_factory=TemporalConfig,
        description="Temporal configuration"
    )
    context: Dict[str, str] = Field(
        default_factory=dict,
        description="Additional context for the task"
    )

    @field_validator('mcp_servers')
    @classmethod
    def split_comma_separated_servers(cls, v: List[str]) -> List[str]:
        """Split comma-separated server names in list items.

        This handles cases where users pass --mcp-server kubernetes,grafana
        instead of --mcp-server kubernetes --mcp-server grafana
        """
        if not v:
            return v

        result = []
        for item in v:
            # Split by comma and strip whitespace
            servers = [s.strip() for s in item.split(',') if s.strip()]
            result.extend(servers)
        return result

    @classmethod
    def from_cli_args(
        cls,
        query: str,
        mcp_servers: List[str],
        temporal_host: Optional[str],
        temporal_namespace: Optional[str],
        temporal_queue: Optional[str],
        workflow_id: Optional[str],
        poll_interval: int,
        max_iterations: int,
        context: Optional[Dict[str, str]],
    ) -> "HumanInLoopConfig":
        """Create HumanInLoopConfig from CLI arguments.

        Args:
            query: Query or task description
            mcp_servers: MCP server names to use
            temporal_host: Temporal server host:port
            temporal_namespace: Temporal namespace
            temporal_queue: Temporal task queue
            workflow_id: Custom workflow ID
            poll_interval: Status poll interval in seconds
            max_iterations: Maximum workflow iterations
            context: Additional context dictionary

        Returns:
            HumanInLoopConfig instance
        """
        temporal_config = TemporalConfig()
        if temporal_host is not None:
            temporal_config.host = temporal_host
        if temporal_namespace is not None:
            temporal_config.namespace = temporal_namespace
        if temporal_queue is not None:
            temporal_config.queue = temporal_queue

        return cls(
            query=query,
            mcp_servers=mcp_servers,
            workflow_id=workflow_id,
            poll_interval=poll_interval,
            max_iterations=max_iterations,
            temporal=temporal_config,
            context=context or {},
        )

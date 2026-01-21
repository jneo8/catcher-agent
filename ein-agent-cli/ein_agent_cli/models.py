"""Pydantic models for CLI configuration and workflow parameters."""

import os
from datetime import datetime
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


class WorkflowConfig(BaseModel):
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
    ) -> "WorkflowConfig":
        """Create WorkflowConfig from CLI arguments.

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
            WorkflowConfig instance
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


# =============================================================================
# Human-in-the-Loop Configuration
# =============================================================================

class HITLWorkflowConfig(BaseModel):
    """Configuration for human-in-the-loop investigation workflow."""

    temporal: TemporalConfig = Field(
        default_factory=TemporalConfig,
        description="Temporal configuration"
    )
    workflow_id: Optional[str] = Field(
        default=None,
        description="Custom workflow ID"
    )
    model: str = Field(
        default="gemini/gemini-2.5-flash",
        description="LLM model to use"
    )
    alertmanager_url: Optional[str] = Field(
        default=None,
        description="Alertmanager URL for fetching alerts"
    )
    max_turns: int = Field(
        default=50,
        ge=1,
        description="Maximum agent turns"
    )

    @classmethod
    def from_cli_args(
        cls,
        temporal_host: Optional[str],
        temporal_namespace: Optional[str],
        temporal_queue: Optional[str],
        workflow_id: Optional[str],
        model: Optional[str],
        alertmanager_url: Optional[str],
        max_turns: int,
    ) -> "HITLWorkflowConfig":
        """Create config from CLI arguments."""
        temporal_config = TemporalConfig()
        if temporal_host is not None:
            temporal_config.host = temporal_host
        if temporal_namespace is not None:
            temporal_config.namespace = temporal_namespace
        if temporal_queue is not None:
            temporal_config.queue = temporal_queue

        config = cls(
            temporal=temporal_config,
            workflow_id=workflow_id,
            max_turns=max_turns,
        )
        if model is not None:
            config.model = model
        if alertmanager_url is not None:
            config.alertmanager_url = alertmanager_url

        return config

"""Pydantic models for CLI configuration and workflow parameters."""

import os
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

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
    status: str = Field(
        default="active",
        description="Filter alerts by status"
    )

    @field_validator('status')
    @classmethod
    def validate_status(cls, v: str) -> str:
        """Validate status value."""
        valid_statuses = ['firing', 'resolved', 'all', 'active']
        if v not in valid_statuses:
            raise ValueError(f"Status must be one of {valid_statuses}")
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


# Local context models for investigation

class ContextItemType(str, Enum):
    """Types of items that can be stored in local context."""

    ALERT = "alert"


class ContextItem(BaseModel):
    """A single item in the local context."""

    item_id: str = Field(
        description="Unique identifier for this item (e.g., alert fingerprint)"
    )
    item_type: ContextItemType = Field(
        description="Type of context item"
    )
    data: Dict[str, Any] = Field(
        description="The actual data (alert object, log entry, etc.)"
    )
    source: Optional[str] = Field(
        default=None,
        description="Source of the data (e.g., Alertmanager URL)"
    )


class WorkflowMetadata(BaseModel):
    """Metadata for workflows tracked in local context."""

    workflow_id: str = Field(
        description="Workflow ID"
    )
    alert_fingerprint: Optional[str] = Field(
        default=None,
        description="Alert fingerprint this workflow is for (if applicable)"
    )
    status: str = Field(
        description="Workflow status: pending/running/completed/failed"
    )
    result: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Workflow result/output (null when pending/running)"
    )

    @field_validator('status')
    @classmethod
    def validate_status(cls, v: str) -> str:
        """Validate status value."""
        valid_statuses = ['pending', 'running', 'completed', 'failed']
        if v not in valid_statuses:
            raise ValueError(f"Status must be one of {valid_statuses}")
        return v


class EnrichmentRCAMetadata(WorkflowMetadata):
    """Enrichment RCA workflow metadata with context info."""

    enrichment_context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Context used for enrichment (alerts, RCA outputs)"
    )


class CompactMetadata(BaseModel):
    """Compact workflow metadata."""

    workflow_id: str = Field(
        description="Workflow ID"
    )
    source_workflow_ids: List[str] = Field(
        description="Which workflows were compacted"
    )
    status: str = Field(
        description="Workflow status: pending/running/completed/failed"
    )
    result: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Compact result/output (null when pending/running)"
    )

    @field_validator('status')
    @classmethod
    def validate_status(cls, v: str) -> str:
        """Validate status value."""
        valid_statuses = ['pending', 'running', 'completed', 'failed']
        if v not in valid_statuses:
            raise ValueError(f"Status must be one of {valid_statuses}")
        return v


class LocalContext(BaseModel):
    """Local context store for investigation data."""

    # Alerts
    items: Dict[str, ContextItem] = Field(
        default_factory=dict,
        description="Alerts indexed by fingerprint"
    )

    # RCA Workflows (separate)
    rca_workflows: Dict[str, WorkflowMetadata] = Field(
        default_factory=dict,
        description="RCA workflows indexed by workflow_id"
    )

    # Enrichment RCA Workflows (separate)
    enrichment_rca_workflows: Dict[str, EnrichmentRCAMetadata] = Field(
        default_factory=dict,
        description="Enrichment RCA workflows indexed by workflow_id"
    )

    # Compact workflows (single entries)
    compact_rca: Optional[CompactMetadata] = None
    compact_enrichment_rca: Optional[CompactMetadata] = None
    incident_summary: Optional[WorkflowMetadata] = None

    # Alert management methods
    def add_item(self, item: ContextItem) -> None:
        """Add an item to the context."""
        self.items[item.item_id] = item

    def remove_item(self, item_id: str) -> bool:
        """Remove an item from context. Returns True if found and removed."""
        if item_id in self.items:
            del self.items[item_id]
            return True
        return False

    def get_item(self, item_id: str) -> Optional[ContextItem]:
        """Get an item by ID."""
        return self.items.get(item_id)

    def get_items_by_type(self, item_type: ContextItemType) -> List[ContextItem]:
        """Get all items of a specific type."""
        return [item for item in self.items.values() if item.item_type == item_type]

    def get_alerts(self) -> List[Dict[str, Any]]:
        """Convenience method to get all alerts."""
        alert_items = self.get_items_by_type(ContextItemType.ALERT)
        return [item.data for item in alert_items]

    def clear(self) -> None:
        """Clear all context items."""
        self.items.clear()

    def count(self) -> int:
        """Get total number of context items."""
        return len(self.items)

    def count_by_type(self, item_type: ContextItemType) -> int:
        """Get count of items by type."""
        return len(self.get_items_by_type(item_type))

    # Workflow management methods
    def add_rca_workflow(self, workflow: WorkflowMetadata) -> None:
        """Add an RCA workflow to the context."""
        self.rca_workflows[workflow.workflow_id] = workflow

    def add_enrichment_rca_workflow(self, workflow: EnrichmentRCAMetadata) -> None:
        """Add an enrichment RCA workflow to the context."""
        self.enrichment_rca_workflows[workflow.workflow_id] = workflow

    def get_rca_for_alert(self, fingerprint: str) -> Optional[WorkflowMetadata]:
        """Get RCA workflow for a specific alert fingerprint."""
        for workflow in self.rca_workflows.values():
            if workflow.alert_fingerprint == fingerprint:
                return workflow
        return None

    def get_enrichment_rca_for_alert(self, fingerprint: str) -> Optional[EnrichmentRCAMetadata]:
        """Get enrichment RCA workflow for a specific alert fingerprint."""
        for workflow in self.enrichment_rca_workflows.values():
            if workflow.alert_fingerprint == fingerprint:
                return workflow
        return None

    def get_alerts_without_rca(self) -> List[str]:
        """Get fingerprints of alerts without RCA workflows."""
        alert_fingerprints = {item.item_id for item in self.items.values()}
        rca_fingerprints = {w.alert_fingerprint for w in self.rca_workflows.values() if w.alert_fingerprint}
        return list(alert_fingerprints - rca_fingerprints)

    def get_alerts_without_enrichment_rca(self) -> List[str]:
        """Get fingerprints of alerts with RCA but without enrichment RCA."""
        rca_fingerprints = {w.alert_fingerprint for w in self.rca_workflows.values() if w.alert_fingerprint and w.status == 'completed'}
        enrichment_fingerprints = {w.alert_fingerprint for w in self.enrichment_rca_workflows.values() if w.alert_fingerprint}
        return list(rca_fingerprints - enrichment_fingerprints)

    def get_completed_rca_workflows(self) -> List[WorkflowMetadata]:
        """Get all completed RCA workflows."""
        return [w for w in self.rca_workflows.values() if w.status == 'completed']

    def get_completed_enrichment_rca_workflows(self) -> List[EnrichmentRCAMetadata]:
        """Get all completed enrichment RCA workflows."""
        return [w for w in self.enrichment_rca_workflows.values() if w.status == 'completed']

    def remove_workflow(self, workflow_id: str) -> bool:
        """Remove a workflow from context. Returns True if found and removed."""
        # Check all workflow types
        if workflow_id in self.rca_workflows:
            del self.rca_workflows[workflow_id]
            return True
        if workflow_id in self.enrichment_rca_workflows:
            del self.enrichment_rca_workflows[workflow_id]
            return True
        if self.compact_rca and self.compact_rca.workflow_id == workflow_id:
            self.compact_rca = None
            return True
        if self.compact_enrichment_rca and self.compact_enrichment_rca.workflow_id == workflow_id:
            self.compact_enrichment_rca = None
            return True
        if self.incident_summary and self.incident_summary.workflow_id == workflow_id:
            self.incident_summary = None
            return True
        return False

    def get_all_workflows(self) -> List[Dict[str, Any]]:
        """Get all workflows as a list with type information."""
        workflows = []

        # RCA workflows
        for w in self.rca_workflows.values():
            workflows.append({
                "workflow_id": w.workflow_id,
                "type": "RCA",
                "alert_fingerprint": w.alert_fingerprint,
                "status": w.status,
                "result": w.result,
            })

        # Enrichment RCA workflows
        for w in self.enrichment_rca_workflows.values():
            workflows.append({
                "workflow_id": w.workflow_id,
                "type": "EnrichmentRCA",
                "alert_fingerprint": w.alert_fingerprint,
                "status": w.status,
                "result": w.result,
                "enrichment_context": w.enrichment_context,
            })

        # Compact RCA
        if self.compact_rca:
            workflows.append({
                "workflow_id": self.compact_rca.workflow_id,
                "type": "CompactRCA",
                "alert_fingerprint": None,
                "status": self.compact_rca.status,
                "result": self.compact_rca.result,
                "source_workflow_ids": self.compact_rca.source_workflow_ids,
            })

        # Compact Enrichment RCA
        if self.compact_enrichment_rca:
            workflows.append({
                "workflow_id": self.compact_enrichment_rca.workflow_id,
                "type": "CompactEnrichmentRCA",
                "alert_fingerprint": None,
                "status": self.compact_enrichment_rca.status,
                "result": self.compact_enrichment_rca.result,
                "source_workflow_ids": self.compact_enrichment_rca.source_workflow_ids,
            })

        # Incident Summary
        if self.incident_summary:
            workflows.append({
                "workflow_id": self.incident_summary.workflow_id,
                "type": "IncidentSummary",
                "alert_fingerprint": None,
                "status": self.incident_summary.status,
                "result": self.incident_summary.result,
            })

        return workflows


class Context(BaseModel):
    """A single investigation context with alerts and workflows."""

    context_id: str = Field(
        description="Unique context ID"
    )
    context_name: Optional[str] = Field(
        default=None,
        description="Optional user-friendly name for the context"
    )
    local_context: LocalContext = Field(
        default_factory=LocalContext,
        description="Local investigation context (alerts and workflows)"
    )
    current_workflow_id: Optional[str] = Field(
        default=None,
        description="Currently active workflow ID in this context"
    )


class SessionState(BaseModel):
    """State for managing multiple investigation contexts."""

    current_context_id: Optional[str] = Field(
        default=None,
        description="Currently active context ID"
    )
    contexts: Dict[str, "Context"] = Field(
        default_factory=dict,
        description="All contexts indexed by context_id"
    )

    def get_current_context(self) -> Optional[Context]:
        """Get the currently active context."""
        if self.current_context_id:
            return self.contexts.get(self.current_context_id)
        return None

    def add_context(self, context: Context) -> None:
        """Add a new context and make it current."""
        self.contexts[context.context_id] = context
        self.current_context_id = context.context_id

    def switch_context(self, context_id: str) -> bool:
        """Switch to a different context.

        Returns:
            True if switch successful, False if context_id not found
        """
        if context_id in self.contexts:
            self.current_context_id = context_id
            return True
        return False

    def remove_context(self, context_id: str) -> bool:
        """Remove a context.

        Returns:
            True if removed, False if not found
        """
        if context_id in self.contexts:
            del self.contexts[context_id]
            # If we removed the current context, switch to another or None
            if self.current_context_id == context_id:
                if self.contexts:
                    # Switch to first available context
                    self.current_context_id = list(self.contexts.keys())[0]
                else:
                    self.current_context_id = None
            return True
        return False

    # Legacy compatibility methods for current context
    @property
    def current_workflow_id(self) -> Optional[str]:
        """Get current workflow ID from current context."""
        context = self.get_current_context()
        return context.current_workflow_id if context else None

    @property
    def local_context(self) -> Optional[LocalContext]:
        """Get local context from current context."""
        context = self.get_current_context()
        return context.local_context if context else None

    def add_workflow(self, workflow_id: str) -> None:
        """Add a workflow to the current context and make it current."""
        context = self.get_current_context()
        if context:
            context.current_workflow_id = workflow_id

    def switch_to(self, workflow_id: str) -> None:
        """Switch to a different workflow in current context."""
        context = self.get_current_context()
        if context:
            context.current_workflow_id = workflow_id

    def has_workflows(self) -> bool:
        """Check if there are any workflows in current context."""
        context = self.get_current_context()
        if context:
            return len(context.local_context.get_all_workflows()) > 0
        return False


class HumanInLoopConfig(BaseModel):
    """Configuration for human-in-the-loop workflow."""

    user_prompt: str = Field(
        default="",
        description="User prompt or task description (optional, can be provided interactively)"
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
    alertmanager_url: Optional[str] = Field(
        default=None,
        description="Alertmanager URL for importing alerts (optional)"
    )
    temporal: TemporalConfig = Field(
        default_factory=TemporalConfig,
        description="Temporal configuration"
    )

    @classmethod
    def from_cli_args(
        cls,
        user_prompt: str,
        temporal_host: Optional[str],
        temporal_namespace: Optional[str],
        temporal_queue: Optional[str],
        workflow_id: Optional[str],
        poll_interval: int,
        max_iterations: int,
        alertmanager_url: Optional[str] = None,
    ) -> "HumanInLoopConfig":
        """Create HumanInLoopConfig from CLI arguments.

        Args:
            user_prompt: User prompt or task description
            temporal_host: Temporal server host:port
            temporal_namespace: Temporal namespace
            temporal_queue: Temporal task queue
            workflow_id: Custom workflow ID
            poll_interval: Status poll interval in seconds
            max_iterations: Maximum workflow iterations
            alertmanager_url: Alertmanager URL for importing alerts (optional)

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
            user_prompt=user_prompt,
            workflow_id=workflow_id,
            poll_interval=poll_interval,
            max_iterations=max_iterations,
            alertmanager_url=alertmanager_url,
            temporal=temporal_config,
        )

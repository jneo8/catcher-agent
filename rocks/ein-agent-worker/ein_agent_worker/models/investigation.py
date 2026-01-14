"""Data models for multi-round investigation."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class AlertFindings:
    """Findings from a single alert investigation.

    This structure captures the essential information from investigating
    one alert, which can then be used for cross-alert correlation.
    """

    alertname: str
    alert_id: str  # Unique identifier (e.g., fingerprint)
    timestamp: str  # When the alert fired

    # Investigation results
    root_cause_assessment: str
    affected_layers: List[str]  # e.g., ["infrastructure", "storage"]
    affected_resources: List[str]  # e.g., ["resource-123", "node-456"]
    scope: str  # e.g., namespace, project, region
    confidence: float  # 0.0 to 1.0

    # Specialist reports (compact summaries)
    specialist_findings: Dict[str, str] = field(default_factory=dict)  # specialist_name → summary

    # Investigation metadata
    round_number: int = 1
    investigation_path: List[str] = field(default_factory=list)  # List of agents consulted


@dataclass
class ContextAgentState:
    """Internal state for CrossAlertContextAgent.

    This structure is embedded in the CrossAlertContextAgent's instructions
    and is NOT passed around as a data structure. It's only used to generate
    the agent's instructions.

    Phase 2 only - not needed for Phase 1.
    """

    round_number: int
    all_findings: List[AlertFindings]  # Accumulated from all rounds

    # Computed indexes (for fast lookup)
    findings_by_resource: Dict[str, List[str]] = field(default_factory=dict)  # resource → [alert_ids]
    findings_by_scope: Dict[str, List[str]] = field(default_factory=dict)  # scope → [alert_ids]
    findings_by_layer: Dict[str, List[str]] = field(default_factory=dict)  # layer → [alert_ids]

    # Convergence tracking
    confidence_by_alert: Dict[str, float] = field(default_factory=dict)
    previous_findings: Optional[List[AlertFindings]] = None


@dataclass
class MultiRoundConfig:
    """Configuration for cross-alert multi-round investigation.

    Controls behavior of the IncidentCorrelationWorkflow.
    """

    # Feature flag
    enable_multi_round: bool = False  # Phase 1: False, Phase 2: True

    # Cross-alert loop control (Phase 2)
    max_rounds: int = 5  # Maximum investigation rounds
    confidence_threshold: float = 0.85  # Stop if avg confidence >= 85%
    convergence_threshold: float = 0.90  # Stop if findings 90% similar

    # Single-alert investigation config
    single_alert_max_turns: int = 30  # Max turns for SingleAlertLeader per round
    specialist_timeout_seconds: int = 300  # 5 min per specialist

    # Execution model
    parallel_specialists: bool = False  # Default: sequential

    # Model configuration (deterministic workflow input)
    model: str = "gemini/gemini-2.5-flash"  # LLM model to use

    # Specialist descriptions (deterministic workflow input)
    # Maps specialist name to domain description
    specialist_descriptions: Optional[Dict[str, str]] = None

"""DSPy optimization module for ein-agent prompt improvement."""

from .data_collector import AgentInteraction, InteractionCollector
from .metrics import (
    incident_report_metric,
    investigation_metric,
    specialist_metric,
)
from .modules import (
    ComputeSpecialistModule,
    InvestigationAgentModule,
    NetworkSpecialistModule,
    ProjectManagerModule,
    StorageSpecialistModule,
)
from .optimizer import AGENT_METRICS, AGENT_MODULES, PromptOptimizer
from .prompt_store import PromptStore, get_prompt, get_prompt_store
from .signatures import (
    InvestigationAgentSignature,
    ProjectManagerSignature,
    SpecialistSignature,
)

__all__ = [
    # Signatures
    "InvestigationAgentSignature",
    "SpecialistSignature",
    "ProjectManagerSignature",
    # Modules
    "InvestigationAgentModule",
    "ComputeSpecialistModule",
    "StorageSpecialistModule",
    "NetworkSpecialistModule",
    "ProjectManagerModule",
    # Metrics
    "investigation_metric",
    "specialist_metric",
    "incident_report_metric",
    # Data collection
    "AgentInteraction",
    "InteractionCollector",
    # Optimization
    "PromptOptimizer",
    "PromptStore",
    "get_prompt",
    "get_prompt_store",
    # Mappings
    "AGENT_MODULES",
    "AGENT_METRICS",
]

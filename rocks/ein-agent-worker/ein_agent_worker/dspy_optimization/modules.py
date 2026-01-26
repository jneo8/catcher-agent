"""DSPy modules wrapping ein-agent behaviors for optimization.

Each module uses a signature and can be compiled with DSPy teleprompters
to generate optimized few-shot examples.
"""

import dspy

from .signatures import (
    InvestigationAgentSignature,
    ProjectManagerSignature,
    SpecialistSignature,
)


class InvestigationAgentModule(dspy.Module):
    """DSPy module for Investigation Agent optimization.

    Wraps the orchestrator agent behavior for few-shot optimization.
    """

    def __init__(self):
        super().__init__()
        self.predict = dspy.ChainOfThought(InvestigationAgentSignature)

    def forward(
        self,
        user_request: str,
        available_specialists: str,
        current_findings: str,
    ):
        """Execute the investigation agent logic."""
        return self.predict(
            user_request=user_request,
            available_specialists=available_specialists,
            current_findings=current_findings,
        )


class ComputeSpecialistModule(dspy.Module):
    """DSPy module for Compute Specialist optimization.

    Handles Kubernetes, pods, nodes, and container investigations.
    """

    def __init__(self):
        super().__init__()
        self.predict = dspy.ChainOfThought(SpecialistSignature)

    def forward(
        self,
        investigation_request: str,
        shared_context: str,
    ):
        """Execute compute specialist investigation."""
        return self.predict(
            investigation_request=investigation_request,
            domain="compute",
            shared_context=shared_context,
        )


class StorageSpecialistModule(dspy.Module):
    """DSPy module for Storage Specialist optimization.

    Handles Ceph, OSDs, PVCs, and storage volume investigations.
    """

    def __init__(self):
        super().__init__()
        self.predict = dspy.ChainOfThought(SpecialistSignature)

    def forward(
        self,
        investigation_request: str,
        shared_context: str,
    ):
        """Execute storage specialist investigation."""
        return self.predict(
            investigation_request=investigation_request,
            domain="storage",
            shared_context=shared_context,
        )


class NetworkSpecialistModule(dspy.Module):
    """DSPy module for Network Specialist optimization.

    Handles networking, DNS, load balancers, and ingress investigations.
    """

    def __init__(self):
        super().__init__()
        self.predict = dspy.ChainOfThought(SpecialistSignature)

    def forward(
        self,
        investigation_request: str,
        shared_context: str,
    ):
        """Execute network specialist investigation."""
        return self.predict(
            investigation_request=investigation_request,
            domain="network",
            shared_context=shared_context,
        )


class ProjectManagerModule(dspy.Module):
    """DSPy module for Investigation Project Manager optimization.

    Synthesizes all investigation reports into final incident analysis.
    """

    def __init__(self):
        super().__init__()
        self.predict = dspy.ChainOfThought(ProjectManagerSignature)

    def forward(
        self,
        investigation_reports: str,
        shared_context: str,
        alert_summary: str,
    ):
        """Synthesize investigation reports."""
        return self.predict(
            investigation_reports=investigation_reports,
            shared_context=shared_context,
            alert_summary=alert_summary,
        )

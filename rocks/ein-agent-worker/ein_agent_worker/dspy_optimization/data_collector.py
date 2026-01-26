"""Data collection for DSPy training.

Captures agent interactions during workflow execution for use as
training examples in DSPy optimization.
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path

import dspy
from pydantic import BaseModel, Field


class AgentInteraction(BaseModel):
    """Single agent interaction for training.

    Captures the input context, agent output, and metadata about
    the interaction for use in DSPy optimization.
    """

    agent_name: str
    input_context: str
    agent_output: str
    tools_called: list[str] = Field(default_factory=list)
    handoffs_made: list[str] = Field(default_factory=list)
    outcome: str = "success"  # success, failure, needs_input
    confidence_scores: dict[str, float] = Field(default_factory=dict)
    human_feedback: str | None = None
    timestamp: datetime = Field(default_factory=datetime.now)

    # Additional context fields for specific agent types
    alert_context: str | None = None
    shared_context_before: str | None = None
    shared_context_after: str | None = None
    domain: str | None = None  # For specialists


class InteractionCollector:
    """Collect agent interactions for DSPy training.

    Stores interactions to JSON files organized by agent type.
    Enable via EIN_COLLECT_TRAINING_DATA=true environment variable.
    """

    def __init__(self, storage_path: str | None = None):
        """Initialize collector.

        Args:
            storage_path: Directory to store interaction logs.
                         Defaults to EIN_TRAINING_DATA_PATH or ./training_data/logs
        """
        self.storage_path = Path(
            storage_path
            or os.getenv("EIN_TRAINING_DATA_PATH", "./training_data/logs")
        )
        self.enabled = os.getenv("EIN_COLLECT_TRAINING_DATA", "false").lower() == "true"

    def record_interaction(self, interaction: AgentInteraction) -> None:
        """Save interaction to storage.

        Args:
            interaction: The agent interaction to record
        """
        if not self.enabled:
            return

        # Create directory for agent type and date
        date_str = interaction.timestamp.strftime('%Y-%m-%d')
        agent_dir = self.storage_path / date_str / interaction.agent_name
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename with timestamp
        filename = f"{interaction.timestamp.strftime('%H%M%S')}_{id(interaction)}.json"
        filepath = agent_dir / filename

        # Write interaction
        with open(filepath, "w") as f:
            f.write(interaction.model_dump_json(indent=2))

    def load_interactions(
        self,
        agent_name: str,
        outcome_filter: str | None = None,
    ) -> list[AgentInteraction]:
        """Load all interactions for an agent type.

        Args:
            agent_name: The agent type to load interactions for
            outcome_filter: Optional filter by outcome (success, failure, etc.)

        Returns:
            List of AgentInteraction objects
        """
        if not self.storage_path.exists():
            return []

        interactions = []
        # Recursively search for JSON files
        for filepath in self.storage_path.rglob(f"*/{agent_name}/*.json"):
            with open(filepath) as f:
                data = json.load(f)
                interaction = AgentInteraction.model_validate(data)

                if outcome_filter is None or interaction.outcome == outcome_filter:
                    interactions.append(interaction)

        # Sort by timestamp
        interactions.sort(key=lambda x: x.timestamp)
        return interactions

    def export_for_dspy(
        self,
        agent_name: str,
        outcome_filter: str = "success",
    ) -> list[dspy.Example]:
        """Export interactions as DSPy-compatible examples.

        Args:
            agent_name: The agent type to export
            outcome_filter: Filter interactions by outcome

        Returns:
            List of dspy.Example objects ready for training
        """
        interactions = self.load_interactions(agent_name, outcome_filter)
        examples = []

        for interaction in interactions:
            example = self._interaction_to_example(interaction)
            if example:
                # Sanitize all fields in the example for better generalization
                sanitized_data = {
                    k: self._sanitize(v) if isinstance(v, str) else v
                    for k, v in example.items()
                }
                sanitized_example = dspy.Example(**sanitized_data).with_inputs(*example.inputs())
                examples.append(sanitized_example)

        return examples

    def _sanitize(self, text: str) -> str:
        """Replace specific identifiers with placeholders for better generalization.
        
        Replaces:
        - Node names (juju-*)
        - IP addresses
        - Fingerprints (16 hex chars)
        """
        if not text:
            return ""
            
        # Node names (e.g., juju-bf3765-8)
        text = re.sub(r'juju-[a-z0-9-]+', '<NODE_NAME>', text)
        
        # IP addresses
        text = re.sub(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', '<IP_ADDRESS>', text)
        
        # Fingerprints (e.g., 8c391d2a47d4567e)
        text = re.sub(r'\b[a-f0-9]{16}\b', '<FINGERPRINT>', text)
        
        return text

    def _interaction_to_example(
        self,
        interaction: AgentInteraction,
    ) -> dspy.Example | None:
        """Convert an interaction to a DSPy Example.

        Maps interaction fields to the appropriate signature fields
        based on agent type.
        """
        agent_name = interaction.agent_name.lower()

        if "investigation_agent" in agent_name or "orchestrator" in agent_name:
            return self._to_investigation_agent_example(interaction)
        elif "specialist" in agent_name:
            return self._to_specialist_example(interaction)
        elif "project_manager" in agent_name or "pm" in agent_name:
            return self._to_project_manager_example(interaction)

        return None

    def _to_investigation_agent_example(
        self,
        interaction: AgentInteraction,
    ) -> dspy.Example:
        """Convert to InvestigationAgent example."""
        # Parse output to extract action and response
        output = interaction.agent_output
        action = self._infer_action(interaction)

        return dspy.Example(
            user_request=interaction.input_context,
            available_specialists="ComputeSpecialist, StorageSpecialist, NetworkSpecialist",
            current_findings=interaction.shared_context_before or "",
            # Expected outputs
            action=action,
            response=output,
        ).with_inputs("user_request", "available_specialists", "current_findings")

    def _to_specialist_example(
        self,
        interaction: AgentInteraction,
    ) -> dspy.Example:
        """Convert to Specialist example."""
        # Extract confidence from shared context updates
        confidence = 0.7  # Default
        if interaction.confidence_scores:
            confidence = max(interaction.confidence_scores.values())

        return dspy.Example(
            investigation_request=interaction.input_context,
            domain=interaction.domain or "compute",
            shared_context=interaction.shared_context_before or "",
            # Expected outputs
            findings=interaction.agent_output,
            root_cause=self._extract_root_cause(interaction.agent_output),
            confidence=confidence,
            context_update=self._extract_context_update(interaction),
        ).with_inputs("investigation_request", "domain", "shared_context")

    def _to_project_manager_example(
        self,
        interaction: AgentInteraction,
    ) -> dspy.Example:
        """Convert to ProjectManager example."""
        return dspy.Example(
            investigation_reports=interaction.input_context,
            shared_context=interaction.shared_context_before or "",
            alert_summary=interaction.alert_context or "",
            # Expected outputs
            incident_summary=self._extract_section(interaction.agent_output, "summary"),
            root_cause=self._extract_section(interaction.agent_output, "root cause"),
            cascade_chain=self._extract_section(interaction.agent_output, "cascade"),
            recommendations=self._extract_section(interaction.agent_output, "recommend"),
        ).with_inputs("investigation_reports", "shared_context", "alert_summary")

    def _infer_action(self, interaction: AgentInteraction) -> str:
        """Infer the action type from interaction metadata."""
        if interaction.handoffs_made:
            return "handoff"
        if interaction.outcome == "needs_input":
            return "ask_user"
        return "respond"

    def _extract_root_cause(self, output: str) -> str:
        """Extract root cause from output text."""
        output_lower = output.lower()
        if "root cause" in output_lower:
            # Try to extract the line with root cause
            for line in output.split("\n"):
                if "root cause" in line.lower():
                    return line.split(":", 1)[-1].strip() if ":" in line else line
        return "Unknown"

    def _extract_context_update(self, interaction: AgentInteraction) -> str:
        """Extract context update from interaction."""
        if interaction.shared_context_after and interaction.shared_context_before:
            # Return the delta
            return f"Updated: {interaction.shared_context_after[:100]}"
        return ""

    def _extract_section(self, text: str, section_name: str) -> str:
        """Extract a section from markdown-formatted text."""
        lines = text.split("\n")
        in_section = False
        section_lines = []

        for line in lines:
            if section_name.lower() in line.lower() and (
                line.startswith("#") or line.startswith("**")
            ):
                in_section = True
                continue
            elif in_section:
                if line.startswith("#") or (line.startswith("**") and line.endswith("**")):
                    break
                section_lines.append(line)

        return "\n".join(section_lines).strip() or text[:200]

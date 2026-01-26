"""DSPy BootstrapFewShot optimizer for ein-agent prompts.

Wraps DSPy's optimization capabilities to improve agent prompts
by collecting few-shot examples from successful interactions.
"""

import os
from pathlib import Path

import dspy

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

# Agent name to module class mapping
AGENT_MODULES = {
    "investigation_agent": InvestigationAgentModule,
    "compute_specialist": ComputeSpecialistModule,
    "storage_specialist": StorageSpecialistModule,
    "network_specialist": NetworkSpecialistModule,
    "project_manager": ProjectManagerModule,
}

# Agent name to metric function mapping
AGENT_METRICS = {
    "investigation_agent": investigation_metric,
    "compute_specialist": specialist_metric,
    "storage_specialist": specialist_metric,
    "network_specialist": specialist_metric,
    "project_manager": incident_report_metric,
}


class PromptOptimizer:
    """Orchestrate DSPy BootstrapFewShot optimization for ein-agent prompts."""

    def __init__(self, task_model: str | None = None):
        """Initialize optimizer.

        Args:
            task_model: LLM model for evaluation. Defaults to DSPY_TASK_MODEL
                       env var or gemini/gemini-3-flash-preview.
        """
        model = task_model or os.getenv(
            "DSPY_TASK_MODEL", "gemini/gemini-3-flash-preview"
        )
        self.task_lm = dspy.LM(model)
        dspy.configure(lm=self.task_lm)

    def optimize_agent(
        self,
        agent_name: str,
        trainset: list[dspy.Example],
        valset: list[dspy.Example] | None = None,
        max_bootstrapped_demos: int = 4,
        max_labeled_demos: int = 8,
    ) -> tuple[str, float]:
        """Optimize agent prompt using BootstrapFewShot.

        Args:
            agent_name: Name of the agent to optimize (e.g., "compute_specialist")
            trainset: Training examples
            valset: Validation examples (defaults to trainset if not provided)
            max_bootstrapped_demos: Number of bootstrapped examples to collect
            max_labeled_demos: Number of labeled examples to use

        Returns:
            Tuple of (optimized_prompt, validation_score)
        """
        if agent_name not in AGENT_MODULES:
            raise ValueError(
                f"Unknown agent: {agent_name}. "
                f"Available agents: {list(AGENT_MODULES.keys())}"
            )

        module = AGENT_MODULES[agent_name]()
        metric = AGENT_METRICS[agent_name]
        valset = valset or trainset

        optimizer = dspy.BootstrapFewShot(
            metric=metric,
            max_bootstrapped_demos=max_bootstrapped_demos,
            max_labeled_demos=max_labeled_demos,
        )

        compiled = optimizer.compile(module, trainset=trainset)

        # Extract optimized prompt
        optimized_prompt = self._extract_prompt(compiled, agent_name)

        # Evaluate on validation set
        evaluator = dspy.Evaluate(devset=valset, metric=metric)
        result = evaluator(compiled)

        return optimized_prompt, result.score

    def _extract_prompt(self, compiled_module: dspy.Module, agent_name: str) -> str:
        """Convert DSPy compiled module back to system prompt string.

        Appends few-shot examples from the compiled module to the
        original base prompt.
        """
        base_prompt = self._get_base_prompt(agent_name)
        
        # Find all predictors in the module. ChainOfThought wraps a Predict object.
        predictors = compiled_module.predictors()
        if not predictors:
            return base_prompt

        # For our current agents, we expect one main predictor.
        # We take the one that has demos (which would be the compiled one).
        demos = []
        for p in predictors:
            if hasattr(p, "demos") and p.demos:
                demos = p.demos
                break

        if not demos:
            return base_prompt

        # Append examples to base prompt
        examples_section = "\n\n## Examples from successful investigations\n"

        for i, demo in enumerate(demos, 1):
            examples_section += f"\n### Example {i}\n"

            # Format inputs
            # Handle cases where input_keys might not be set (common in bootstrapped demos)
            input_keys = getattr(demo, "_input_keys", None) or [
                k for k in demo.keys() if k not in ["augmented", "success"] and k not in self._get_output_keys(agent_name)
            ]
            
            for key in input_keys:
                if key in demo:
                    value = demo[key]
                    display_value = str(value)[:500]
                    if len(str(value)) > 500:
                        display_value += "..."
                    examples_section += f"**{key}:** {display_value}\n"

            # Format outputs
            examples_section += "\n**Expected output:**\n"
            output_keys = self._get_output_keys(agent_name)
            for key in output_keys:
                if key in demo:
                    value = demo[key]
                    display_value = str(value)[:500]
                    if len(str(value)) > 500:
                        display_value += "..."
                    examples_section += f"- {key}: {display_value}\n"

        return base_prompt + examples_section

    def _get_output_keys(self, agent_name: str) -> list[str]:
        """Get output field names for an agent."""
        if agent_name == "investigation_agent":
            return ["reasoning", "action", "response"]
        elif agent_name == "compute_specialist":
            return ["reasoning", "findings", "root_cause", "confidence", "context_update"]
        elif agent_name == "storage_specialist":
            return ["reasoning", "findings", "root_cause", "confidence", "context_update"]
        elif agent_name == "network_specialist":
            return ["reasoning", "findings", "root_cause", "confidence", "context_update"]
        elif agent_name == "project_manager":
            return ["reasoning", "incident_summary", "root_cause", "cascade_chain", "recommendations"]
        return []

    def _get_base_prompt(self, agent_name: str) -> str:
        """Get original prompt template for agent.

        Imports from existing prompt definitions to maintain single source of truth.
        """
        if agent_name == "investigation_agent":
            from ein_agent_worker.workflows.human_in_the_loop import (
                INVESTIGATION_AGENT_PROMPT,
            )
            return INVESTIGATION_AGENT_PROMPT

        elif agent_name == "compute_specialist":
            from ein_agent_worker.workflows.agents.specialists import (
                COMPUTE_SPECIALIST_INSTRUCTIONS,
            )
            return COMPUTE_SPECIALIST_INSTRUCTIONS

        elif agent_name == "storage_specialist":
            from ein_agent_worker.workflows.agents.specialists import (
                STORAGE_SPECIALIST_INSTRUCTIONS,
            )
            return STORAGE_SPECIALIST_INSTRUCTIONS

        elif agent_name == "network_specialist":
            from ein_agent_worker.workflows.agents.specialists import (
                NETWORK_SPECIALIST_INSTRUCTIONS,
            )
            return NETWORK_SPECIALIST_INSTRUCTIONS

        elif agent_name == "project_manager":
            from ein_agent_worker.workflows.agents.investigation_project_manager import (
                INVESTIGATION_PROJECT_MANAGER_INSTRUCTIONS,
            )
            return INVESTIGATION_PROJECT_MANAGER_INSTRUCTIONS

        else:
            raise ValueError(f"Unknown agent: {agent_name}")

    def save_optimized_prompt(
        self,
        agent_name: str,
        prompt: str,
        version: str,
        base_path: str | None = None,
    ) -> Path:
        """Save optimized prompt to file.

        Args:
            agent_name: Name of the agent
            prompt: The optimized prompt content
            version: Version identifier (e.g., "v1", "v2")
            base_path: Base directory for prompts. Defaults to
                      EIN_PROMPT_STORE_PATH or ./prompts

        Returns:
            Path to the saved prompt file
        """
        base = Path(
            base_path or os.getenv("EIN_PROMPT_STORE_PATH", "./prompts")
        )
        version_dir = base / version
        version_dir.mkdir(parents=True, exist_ok=True)

        filepath = version_dir / f"{agent_name}.txt"
        filepath.write_text(prompt)

        return filepath

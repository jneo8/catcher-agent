"""Prompt store for loading optimized prompts at runtime.

Provides file-based storage and retrieval of optimized prompts
with fallback to baseline prompts.
"""

import os
from pathlib import Path


class PromptStore:
    """Load and manage optimized prompts from files.

    Prompts are organized by version in the storage directory:
        {base_path}/
            baseline/
                investigation_agent.txt
                compute_specialist.txt
                ...
            v1/
                investigation_agent.txt
                ...
            latest -> v1  (symlink or copy)
    """

    def __init__(self, base_path: str | None = None):
        """Initialize prompt store.

        Args:
            base_path: Base directory for prompt storage.
                      Defaults to EIN_PROMPT_STORE_PATH env var or /app/prompts.
        """
        self.base_path = Path(
            base_path or os.getenv("EIN_PROMPT_STORE_PATH", "/app/prompts")
        )
        self._cache: dict[str, str] = {}

    def get_prompt(self, agent_name: str, version: str | None = None) -> str:
        """Get prompt for agent.

        Args:
            agent_name: Agent identifier (e.g., "investigation_agent", "compute_specialist")
            version: Prompt version to load. Defaults to EIN_PROMPT_VERSION env var
                    or "latest". Use "baseline" for original prompts.

        Returns:
            The prompt string for the agent.
        """
        version = version or os.getenv("EIN_PROMPT_VERSION", "latest")
        cache_key = f"{agent_name}:{version}"

        if cache_key in self._cache:
            return self._cache[cache_key]

        # Try to load from file
        prompt_path = self.base_path / version / f"{agent_name}.txt"

        if prompt_path.exists():
            prompt = prompt_path.read_text()
            self._cache[cache_key] = prompt
            return prompt

        # Fallback to baseline file
        baseline_path = self.base_path / "baseline" / f"{agent_name}.txt"
        if baseline_path.exists():
            prompt = baseline_path.read_text()
            self._cache[cache_key] = prompt
            return prompt

        # Final fallback to hardcoded baseline
        prompt = self._get_hardcoded_baseline(agent_name)
        self._cache[cache_key] = prompt
        return prompt

    def clear_cache(self) -> None:
        """Clear the prompt cache to force reload from files."""
        self._cache.clear()

    def list_versions(self) -> list[str]:
        """List available prompt versions.

        Returns:
            List of version directory names.
        """
        if not self.base_path.exists():
            return []

        return [
            d.name
            for d in self.base_path.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ]

    def list_agents(self, version: str = "baseline") -> list[str]:
        """List agents with prompts in a version.

        Args:
            version: Version directory to list.

        Returns:
            List of agent names.
        """
        version_path = self.base_path / version
        if not version_path.exists():
            return []

        return [
            f.stem
            for f in version_path.glob("*.txt")
        ]

    def _get_hardcoded_baseline(self, agent_name: str) -> str:
        """Get hardcoded baseline prompt for agent.

        Falls back to importing from the original prompt definitions
        in the workflow modules.
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
                INVESTIGATION_PM_PROMPT,
            )
            return INVESTIGATION_PM_PROMPT

        else:
            raise ValueError(f"Unknown agent: {agent_name}")


# Global instance for convenience
_default_store: PromptStore | None = None


def get_prompt_store() -> PromptStore:
    """Get the global PromptStore instance."""
    global _default_store
    if _default_store is None:
        _default_store = PromptStore()
    return _default_store


def get_prompt(agent_name: str, version: str | None = None) -> str:
    """Convenience function to get a prompt from the default store.

    Args:
        agent_name: Agent identifier
        version: Optional version (defaults to EIN_PROMPT_VERSION or "latest")

    Returns:
        The prompt string.
    """
    return get_prompt_store().get_prompt(agent_name, version)

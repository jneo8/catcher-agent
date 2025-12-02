"""Alert prompt registry for mapping alert names to AI agent prompts."""

import yaml
from pathlib import Path
from typing import Dict, List, Optional
from pydantic import BaseModel, Field, field_validator
from jinja2 import Template, TemplateError
from loguru import logger


class AlertPromptConfig(BaseModel):
    """Configuration for a single alert type."""

    alert_name: str = Field(..., description="Name of the alert (e.g., 'KubePodNotReady1M')")
    mcp_servers: List[str] = Field(..., description="List of MCP server names to enable")
    prompt: str = Field(..., description="Jinja2 template string for the prompt")

    @field_validator("mcp_servers")
    @classmethod
    def validate_mcp_servers(cls, v: List[str]) -> List[str]:
        """Validate that mcp_servers is not empty."""
        if not v:
            raise ValueError("mcp_servers must contain at least one server")
        return v

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, v: str) -> str:
        """Validate that prompt is not empty."""
        if not v.strip():
            raise ValueError("prompt cannot be empty")
        return v

    def render_prompt(self, alert_data: Dict) -> str:
        """Render the prompt template with alert data.

        Args:
            alert_data: Dictionary containing alert information with keys:
                - alertname: str
                - status: str
                - labels: Dict[str, str]
                - annotations: Dict[str, str]
                - starts_at: datetime
                - ends_at: datetime (optional)
                - fingerprint: str (optional)
                - generator_url: str

        Returns:
            Rendered prompt string

        Raises:
            TemplateError: If template rendering fails
        """
        try:
            template = Template(self.prompt)
            return template.render(**alert_data)
        except TemplateError as e:
            logger.error(f"Failed to render prompt template for {self.alert_name}: {e}")
            raise


class AlertPromptRegistry:
    """Registry for managing alert-to-prompt mappings."""

    def __init__(self):
        """Initialize empty registry."""
        self._registry: Dict[str, AlertPromptConfig] = {}

    @classmethod
    def from_yaml(cls, yaml_path: str) -> "AlertPromptRegistry":
        """Load alert prompt configurations from YAML file.

        Args:
            yaml_path: Path to the YAML configuration file

        Returns:
            AlertPromptRegistry instance with loaded configurations

        Raises:
            FileNotFoundError: If YAML file doesn't exist
            yaml.YAMLError: If YAML parsing fails
            ValueError: If YAML structure is invalid
        """
        path = Path(yaml_path)

        if not path.exists():
            raise FileNotFoundError(f"Alert prompts configuration file not found: {yaml_path}")

        logger.info(f"Loading alert prompts from {yaml_path}")

        with open(path, "r") as f:
            data = yaml.safe_load(f)

        if not data or "alert_prompts" not in data:
            raise ValueError("Invalid YAML structure: missing 'alert_prompts' key")

        registry = cls()
        alert_prompts = data["alert_prompts"]

        for alert_name, config_dict in alert_prompts.items():
            try:
                # Add alert_name to the config dict before creating Pydantic model
                config_dict["alert_name"] = alert_name
                config = AlertPromptConfig(**config_dict)
                registry._registry[alert_name] = config
                logger.info(f"Registered alert: {alert_name} with MCP servers: {config.mcp_servers}")
            except Exception as e:
                logger.warning(f"Skipping alert '{alert_name}': {e}")

        logger.info(f"Loaded {len(registry._registry)} alert prompt configurations")
        return registry

    def get_config(self, alert_name: str) -> Optional[AlertPromptConfig]:
        """Get configuration for an alert.

        Args:
            alert_name: Name of the alert

        Returns:
            AlertPromptConfig if found, None otherwise
        """
        return self._registry.get(alert_name)

    def has_alert(self, alert_name: str) -> bool:
        """Check if an alert is registered.

        Args:
            alert_name: Name of the alert

        Returns:
            True if alert is registered, False otherwise
        """
        return alert_name in self._registry

    def list_alerts(self) -> List[str]:
        """List all registered alert names.

        Returns:
            List of alert names
        """
        return list(self._registry.keys())

    def get_mcp_servers(self, alert_name: str) -> List[str]:
        """Get MCP server list for an alert.

        Args:
            alert_name: Name of the alert

        Returns:
            List of MCP server names, empty list if alert not found
        """
        config = self.get_config(alert_name)
        return config.mcp_servers if config else []

    def render_prompt(self, alert_name: str, alert_data: Dict) -> Optional[str]:
        """Render prompt for an alert with given data.

        Args:
            alert_name: Name of the alert
            alert_data: Alert data dictionary

        Returns:
            Rendered prompt string, None if alert not found

        Raises:
            TemplateError: If template rendering fails
        """
        config = self.get_config(alert_name)
        if not config:
            return None
        return config.render_prompt(alert_data)

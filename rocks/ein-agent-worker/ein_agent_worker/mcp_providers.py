"""MCP Server Provider configurations for Ein Agent.

This module provides a configuration-driven approach for registering MCP servers.
MCP servers are configured entirely via environment variables - no code changes needed.

The MCP servers are registered as StatelessMCPServerProvider instances and can be accessed
in workflows using openai_agents.workflow.stateless_mcp_server(name) which returns an
MCPServer instance. Retry policies are automatically applied based on configuration.

Configuration Format:
    MCP_SERVERS: Comma-separated list of server names (e.g., "kubernetes,grafana")
    MCP_{SERVER}_URL: HTTP/HTTPS URL for the server (required)
    MCP_{SERVER}_ENABLED: Enable/disable the server (default: true)
    MCP_{SERVER}_TRANSPORT: Transport type - 'http' or 'sse' (default: http)
    MCP_{SERVER}_ALLOWED_TOOLS: Comma-separated list of allowed tools (optional)

    Retry Policy (per-server):
    MCP_{SERVER}_RETRY_MAX_ATTEMPTS: Maximum retry attempts (default: 3)
    MCP_{SERVER}_RETRY_INITIAL_INTERVAL: Initial retry interval in seconds (default: 1.0)
    MCP_{SERVER}_RETRY_BACKOFF_COEFFICIENT: Backoff multiplier (default: 2.0)
    MCP_{SERVER}_RETRY_MAX_INTERVAL: Maximum retry interval in seconds (default: 30.0)

    Global Retry Defaults:
    MCP_DEFAULT_RETRY_MAX_ATTEMPTS: Default max attempts for all servers (default: 3)
    MCP_DEFAULT_RETRY_INITIAL_INTERVAL: Default initial interval in seconds (default: 1.0)
    MCP_DEFAULT_RETRY_BACKOFF_COEFFICIENT: Default backoff coefficient (default: 2.0)
    MCP_DEFAULT_RETRY_MAX_INTERVAL: Default max interval in seconds (default: 30.0)

Example Configuration:
    # Basic setup with default retry policy
    export MCP_SERVERS="kubernetes"
    export MCP_KUBERNETES_URL="http://kubernetes-mcp:8000/mcp"

    # Advanced setup with custom retry policies
    export MCP_SERVERS="kubernetes,grafana"
    export MCP_KUBERNETES_URL="http://kubernetes-mcp:8000/mcp"
    export MCP_KUBERNETES_TRANSPORT="http"
    export MCP_KUBERNETES_ALLOWED_TOOLS="get_pods,create_deployment"
    export MCP_KUBERNETES_RETRY_MAX_ATTEMPTS="5"  # More retries for critical server
    export MCP_KUBERNETES_RETRY_INITIAL_INTERVAL="2"

    export MCP_GRAFANA_URL="http://grafana-mcp:8000/sse"
    export MCP_GRAFANA_TRANSPORT="sse"
    export MCP_GRAFANA_RETRY_MAX_ATTEMPTS="2"  # Fewer retries for faster failure

    # Set global defaults for all servers
    export MCP_DEFAULT_RETRY_MAX_ATTEMPTS="3"
"""

import logging
import os
from dataclasses import dataclass
from datetime import timedelta
from typing import List, Optional

from agents.mcp import MCPServerStreamableHttp, MCPServerSse, create_static_tool_filter
from temporalio import activity
from temporalio.common import RetryPolicy
from temporalio.contrib.openai_agents import StatelessMCPServerProvider

logger = logging.getLogger(__name__)


@dataclass
class RetryPolicyConfig:
    """Retry policy configuration for MCP server activities.

    Attributes:
        max_attempts: Maximum number of retry attempts
        initial_interval: Initial retry interval in seconds
        backoff_coefficient: Backoff multiplier for retry interval
        max_interval: Maximum retry interval in seconds
    """

    max_attempts: int = 3
    initial_interval: float = 1.0
    backoff_coefficient: float = 2.0
    max_interval: float = 30.0

    def to_temporal_retry_policy(self) -> RetryPolicy:
        """Convert to Temporal RetryPolicy object.

        Returns:
            RetryPolicy instance for use with Temporal activities
        """
        return RetryPolicy(
            maximum_attempts=self.max_attempts,
            initial_interval=timedelta(seconds=self.initial_interval),
            backoff_coefficient=self.backoff_coefficient,
            maximum_interval=timedelta(seconds=self.max_interval),
        )


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server.

    Attributes:
        name: Unique name of the MCP server
        url: HTTP/HTTPS endpoint URL
        enabled: Whether the server is enabled
        allowed_tools: Optional list of allowed tool names
        transport: Transport type to use ('http' or 'sse')
        retry_policy: Retry policy configuration for this server
    """

    name: str
    url: str
    enabled: bool = True
    allowed_tools: Optional[List[str]] = None
    transport: str = "http"
    retry_policy: Optional[RetryPolicyConfig] = None


class MCPConfig:
    """Global MCP configuration loaded from environment variables.

    This object is created once and can be passed to workers and workflows.
    """

    def __init__(self):
        """Initialize MCP configuration from environment."""
        self.servers: List[MCPServerConfig] = []
        self.default_retry_policy = self._load_default_retry_policy()
        self._load_from_env()

    def _load_default_retry_policy(self) -> RetryPolicyConfig:
        """Load default retry policy configuration from environment."""
        return RetryPolicyConfig(
            max_attempts=int(os.getenv("MCP_DEFAULT_RETRY_MAX_ATTEMPTS", "3")),
            initial_interval=float(os.getenv("MCP_DEFAULT_RETRY_INITIAL_INTERVAL", "1.0")),
            backoff_coefficient=float(os.getenv("MCP_DEFAULT_RETRY_BACKOFF_COEFFICIENT", "2.0")),
            max_interval=float(os.getenv("MCP_DEFAULT_RETRY_MAX_INTERVAL", "30.0")),
        )

    def _load_from_env(self) -> None:
        """Load MCP server configurations from environment variables."""
        servers_config = os.getenv("MCP_SERVERS", "")
        if not servers_config:
            logger.info("MCP_SERVERS not set, no MCP servers configured")
            return

        server_names = [name.strip() for name in servers_config.split(",") if name.strip()]

        if not server_names:
            logger.warning("MCP_SERVERS is empty")
            return

        logger.info("Loading configuration for %d MCP server(s): %s", len(server_names), ", ".join(server_names))

        for server_name in server_names:
            config = self._load_server_config(server_name)
            if config:
                self.servers.append(config)
                logger.info("Loaded MCP server config: %s (enabled=%s)", server_name, config.enabled)

    def _load_server_config(self, server_name: str) -> Optional[MCPServerConfig]:
        """Load configuration for a single MCP server."""
        server_key = server_name.upper().replace("-", "_")

        # Check if enabled
        enabled_key = f"MCP_{server_key}_ENABLED"
        enabled = os.getenv(enabled_key, "true").lower() == "true"

        # Get URL (required)
        url_key = f"MCP_{server_key}_URL"
        url = os.getenv(url_key)

        if not url:
            logger.warning("MCP server '%s' missing required %s, skipping", server_name, url_key)
            return None

        # Validate URL scheme
        if not url.startswith(("http://", "https://")):
            logger.error("MCP server '%s' has invalid URL '%s' (must start with http:// or https://)", server_name, url)
            return None

        # Get transport type (default: http)
        transport_key = f"MCP_{server_key}_TRANSPORT"
        transport = os.getenv(transport_key, "http").lower()

        # Validate transport type
        if transport not in ("http", "sse"):
            logger.error("MCP server '%s' has invalid transport '%s' (must be 'http' or 'sse')", server_name, transport)
            return None

        # Get optional tool filtering
        allowed_tools_key = f"MCP_{server_key}_ALLOWED_TOOLS"
        allowed_tools_str = os.getenv(allowed_tools_key)
        allowed_tools = None

        if allowed_tools_str:
            allowed_tools = [tool.strip() for tool in allowed_tools_str.split(",") if tool.strip()]

        # Load retry policy (use server-specific or fall back to defaults)
        retry_policy = self._load_server_retry_policy(server_key)

        return MCPServerConfig(
            name=server_name,
            url=url,
            enabled=enabled,
            allowed_tools=allowed_tools,
            transport=transport,
            retry_policy=retry_policy,
        )

    def _load_server_retry_policy(self, server_key: str) -> RetryPolicyConfig:
        """Load retry policy for a specific server, using defaults as fallback."""
        max_attempts_key = f"MCP_{server_key}_RETRY_MAX_ATTEMPTS"
        initial_interval_key = f"MCP_{server_key}_RETRY_INITIAL_INTERVAL"
        backoff_coefficient_key = f"MCP_{server_key}_RETRY_BACKOFF_COEFFICIENT"
        max_interval_key = f"MCP_{server_key}_RETRY_MAX_INTERVAL"

        return RetryPolicyConfig(
            max_attempts=int(os.getenv(max_attempts_key, str(self.default_retry_policy.max_attempts))),
            initial_interval=float(os.getenv(initial_interval_key, str(self.default_retry_policy.initial_interval))),
            backoff_coefficient=float(os.getenv(backoff_coefficient_key, str(self.default_retry_policy.backoff_coefficient))),
            max_interval=float(os.getenv(max_interval_key, str(self.default_retry_policy.max_interval))),
        )

    @property
    def enabled_servers(self) -> List[MCPServerConfig]:
        """Get only enabled MCP servers."""
        return [s for s in self.servers if s.enabled]

    def get_server(self, name: str) -> Optional[MCPServerConfig]:
        """Get configuration for a specific MCP server by name."""
        for server in self.servers:
            if server.name.lower() == name.lower():
                return server
        return None

    def get_retry_policy_for_server(self, name: str) -> Optional[RetryPolicy]:
        """Get Temporal RetryPolicy for a specific MCP server.

        Args:
            name: Name of the MCP server

        Returns:
            RetryPolicy instance if server exists, None otherwise
        """
        server = self.get_server(name)
        if server and server.retry_policy:
            return server.retry_policy.to_temporal_retry_policy()
        return None

    def get_default_temporal_retry_policy(self) -> RetryPolicy:
        """Get the default Temporal RetryPolicy.

        Returns:
            RetryPolicy instance with default configuration
        """
        return self.default_retry_policy.to_temporal_retry_policy()


class MCPProviderRegistry:
    """Registry for creating Temporal MCP providers from MCPConfig."""

    @classmethod
    def get_all_providers(cls, config: MCPConfig) -> List[StatelessMCPServerProvider]:
        """Create Temporal MCP providers from MCPConfig.

        Args:
            config: MCPConfig instance with loaded configuration

        Returns:
            List of StatelessMCPServerProvider instances for enabled servers
        """
        providers = []

        enabled_servers = config.enabled_servers

        if not enabled_servers:
            logger.info("No enabled MCP servers found in configuration")
            return providers

        logger.info("Creating providers for %d enabled MCP server(s)", len(enabled_servers))

        for server_config in enabled_servers:
            try:
                provider = cls._create_provider(server_config)
                if provider:
                    providers.append(provider)
                    logger.info("Successfully registered MCP provider: %s", server_config.name)
            except Exception as e:
                logger.error(
                    "Failed to create MCP provider '%s': %s",
                    server_config.name,
                    e,
                    exc_info=True
                )

        logger.info("Total MCP providers registered: %d", len(providers))
        return providers

    @classmethod
    def _create_provider(cls, server_config: MCPServerConfig) -> Optional[StatelessMCPServerProvider]:
        """Create a Temporal MCP provider from server configuration.

        The retry policy is configured per server and can be accessed via server_config.retry_policy.
        To use the retry policy in workflows, call:
            mcp_server = openai_agents.workflow.stateless_mcp_server(server_name)

        This returns an MCPServer instance that can be passed to the Agent.
        The retry policy from the configuration should be applied at the activity level
        when making MCP calls.

        Args:
            server_config: MCPServerConfig instance

        Returns:
            StatelessMCPServerProvider instance
        """
        # Create tool filter if allowed_tools specified
        tool_filter = None
        if server_config.allowed_tools:
            tool_filter = create_static_tool_filter(allowed_tool_names=server_config.allowed_tools)
            logger.info(
                "MCP server '%s' using tool filter with allowed tools: %s",
                server_config.name,
                ", ".join(server_config.allowed_tools)
            )

        def create_mcp_server(
            name: str = server_config.name,
            server_url: str = server_config.url,
            transport: str = server_config.transport,
            filter_tools=tool_filter
        ):
            """Factory function to create MCP server instance.

            This function is called by Temporal's stateless_mcp_server() to create
            the actual MCP server instance when needed in workflows.

            IMPORTANT: max_retry_attempts is set to 0 to disable MCP-level retries.
            This allows errors to surface immediately to the workflow where they
            can be handled gracefully and presented to the agent for user interaction.
            """
            if transport == "sse":
                return MCPServerSse(
                    params={"url": server_url},
                    name=name,
                    tool_filter=filter_tools,
                    max_retry_attempts=0,  # Disable retries - fail fast for human-in-loop
                )
            else:  # default to http
                return MCPServerStreamableHttp(
                    params={"url": server_url},
                    name=name,
                    tool_filter=filter_tools,
                    max_retry_attempts=0,  # Disable retries - fail fast for human-in-loop
                )

        provider = StatelessMCPServerProvider(
            server_config.name,
            create_mcp_server,
        )

        retry_info = f"retry_policy(max_attempts={server_config.retry_policy.max_attempts}, " \
                     f"initial_interval={server_config.retry_policy.initial_interval}s)"
        logger.info(
            "Created MCP provider '%s' at %s (transport=%s, %s)",
            server_config.name,
            server_config.url,
            server_config.transport,
            retry_info
        )
        return provider

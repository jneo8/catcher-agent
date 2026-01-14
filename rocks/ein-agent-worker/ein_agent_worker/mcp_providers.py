"""MCP Server Provider configurations for Catcher Agent.

This module provides a configuration-driven approach for registering MCP servers.
MCP servers are configured entirely via environment variables - no code changes needed.

Configuration Format:
    MCP_SERVERS: Comma-separated list of server names (e.g., "kubernetes,grafana")
    MCP_{SERVER}_URL: HTTP/HTTPS URL for the server (required)
    MCP_{SERVER}_ENABLED: Enable/disable the server (default: true)
    MCP_{SERVER}_TRANSPORT: Transport type - 'http' or 'sse' (default: http)
    MCP_{SERVER}_ALLOWED_TOOLS: Comma-separated list of allowed tools (optional)

Example:
    export MCP_SERVERS="kubernetes,grafana"
    export MCP_KUBERNETES_URL="http://kubernetes-mcp:8000/mcp"
    export MCP_KUBERNETES_ENABLED="true"
    export MCP_KUBERNETES_TRANSPORT="http"
    export MCP_KUBERNETES_ALLOWED_TOOLS="get_pods,create_deployment"
    export MCP_GRAFANA_URL="http://grafana-mcp:8000/sse"
    export MCP_GRAFANA_TRANSPORT="sse"
"""

import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional

from agents.mcp import MCPServerStreamableHttp, MCPServerSse, create_static_tool_filter
from temporalio import activity
from temporalio.contrib.openai_agents import StatelessMCPServerProvider

logger = logging.getLogger(__name__)


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server.

    Attributes:
        name: Unique name of the MCP server
        url: HTTP/HTTPS endpoint URL
        enabled: Whether the server is enabled
        allowed_tools: Optional list of allowed tool names
        transport: Transport type to use ('http' or 'sse')
    """

    name: str
    url: str
    enabled: bool = True
    allowed_tools: Optional[List[str]] = None
    transport: str = "http"


@dataclass
class MCPConfig:
    """Global MCP configuration loaded from environment variables.

    This object is created once and can be passed to workers and workflows.
    """
    
    servers: List[MCPServerConfig] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> "MCPConfig":
        """Load MCP configuration from environment variables."""
        config = cls()
        servers_config = os.getenv("MCP_SERVERS", "")
        if not servers_config:
            logger.info("MCP_SERVERS not set, no MCP servers configured")
            return config

        server_names = [name.strip() for name in servers_config.split(",") if name.strip()]

        if not server_names:
            logger.warning("MCP_SERVERS is empty")
            return config

        logger.info("Loading configuration for %d MCP server(s): %s", len(server_names), ", ".join(server_names))

        for server_name in server_names:
            server_config = cls._load_server_config(server_name)
            if server_config:
                config.servers.append(server_config)
                logger.info("Loaded MCP server config: %s (enabled=%s)", server_name, server_config.enabled)
        
        return config

    @staticmethod
    def _load_server_config(server_name: str) -> Optional[MCPServerConfig]:
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

        return MCPServerConfig(
            name=server_name,
            url=url,
            enabled=enabled,
            allowed_tools=allowed_tools,
            transport=transport,
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


@activity.defn
async def load_mcp_config() -> MCPConfig:
    """Activity to load MCP configuration from environment variables."""
    return MCPConfig.from_env()



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
            if transport == "sse":
                return MCPServerSse(
                    params={"url": server_url},
                    name=name,
                    tool_filter=filter_tools,
                )
            else:  # default to http
                return MCPServerStreamableHttp(
                    params={"url": server_url},
                    name=name,
                    tool_filter=filter_tools,
                )

        provider = StatelessMCPServerProvider(
            server_config.name,
            create_mcp_server,
        )

        logger.info("Created MCP provider '%s' at %s (transport=%s)", server_config.name, server_config.url, server_config.transport)
        return provider

"""UTCP client registry - global storage for pre-initialized UTCP clients.

UTCP clients are created at worker startup (where network I/O is allowed)
and stored here for workflows to access. Workflows then create lightweight
meta-tools (search, get_details, call) that reference these clients.

This pattern:
1. Avoids network I/O inside Temporal workflow sandboxes
2. Only passes 3 meta-tools to agents (not thousands of individual operations)
3. Actual API operations are discovered dynamically via search at runtime
"""

import logging
from typing import Optional

from utcp.utcp_client import UtcpClient
from ein_agent_worker.utcp.config import UTCPServiceConfig

logger = logging.getLogger(__name__)

# Global registry of pre-initialized UTCP clients
_utcp_clients: dict[str, UtcpClient] = {}

# Global registry of service configurations
_service_configs: dict[str, UTCPServiceConfig] = {}


def register_client(
    service_name: str,
    client: UtcpClient,
    config: Optional[UTCPServiceConfig] = None
) -> None:
    """Register a pre-initialized UTCP client.

    Args:
        service_name: Service name (e.g., 'kubernetes', 'grafana')
        client: The UTCP client instance (already initialized with OpenAPI spec)
        config: Optional service configuration (for approval policy, etc.)
    """
    _utcp_clients[service_name] = client
    if config:
        _service_configs[service_name] = config
    logger.info(f"Registered UTCP client for '{service_name}'")


def get_client(service_name: str) -> Optional[UtcpClient]:
    """Get a registered UTCP client.

    Args:
        service_name: Service name

    Returns:
        The UTCP client or None if not registered
    """
    return _utcp_clients.get(service_name)


def get_service_config(service_name: str) -> Optional[UTCPServiceConfig]:
    """Get a registered service configuration.

    Args:
        service_name: Service name

    Returns:
        The service config or None if not registered
    """
    return _service_configs.get(service_name)


def list_services() -> list[str]:
    """List all registered service names.

    Returns:
        List of registered service names
    """
    return list(_utcp_clients.keys())


def clear() -> None:
    """Clear all registered clients and configs."""
    _utcp_clients.clear()
    _service_configs.clear()
    logger.info("Cleared UTCP registry")

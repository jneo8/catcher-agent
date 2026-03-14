"""UTCP (Universal Tool Calling Protocol) module for Ein Agent.

This module provides tools generated from OpenAPI specifications,
replacing the previous MCP-based approach.

Architecture:
- UTCP clients are initialized at worker startup (in worker.py)
- Clients are stored in the registry for workflows to access
- Workflows create 3 lightweight meta-tools per service:
  - search_{service}_operations: Search available API operations
  - get_{service}_operation_details: Get parameter schema for an operation
  - call_{service}_operation: Execute an API operation
- This keeps agent context small while enabling dynamic API discovery
"""

from ein_agent_worker.utcp.config import (
    UTCPConfig,
    UTCPServiceConfig,
    KubernetesVersion,
    CephVersion,
    GrafanaVersion,
    SUPPORTED_VERSIONS,
    DEFAULT_VERSIONS,
)
from ein_agent_worker.utcp.loader import ToolLoader, create_utcp_tools
from ein_agent_worker.utcp import registry
from ein_agent_worker.utcp.temporal_utcp import (
    create_utcp_workflow_tools,
    get_utcp_activities,
)
from ein_agent_worker.utcp.local_file_protocol import (
    LocalFileHttpProtocol,
    register_local_file_protocol,
    set_api_base_url,
    get_api_base_url,
)
from ein_agent_worker.utcp.openapi_handlers import (
    OpenApiHandler,
    DefaultOpenApiHandler,
    KubernetesOpenApiHandler,
    GrafanaOpenApiHandler,
    BearerTokenLoader,
    DEFAULT_OPENAPI_HANDLERS,
)
from ein_agent_worker.utcp.spec import (
    SpecSourceStrategy,
    LocalFileStrategy,
    LiveURLStrategy,
    SpecSource,
)
from ein_agent_worker.utcp.ssl_config import SSLConfigManager

__all__ = [
    # Config
    "UTCPConfig",
    "UTCPServiceConfig",
    "KubernetesVersion",
    "CephVersion",
    "GrafanaVersion",
    "SUPPORTED_VERSIONS",
    "DEFAULT_VERSIONS",
    # Loader
    "ToolLoader",
    "create_utcp_tools",
    # Registry
    "registry",
    # Temporal
    "create_utcp_workflow_tools",
    "get_utcp_activities",
    # Protocol
    "LocalFileHttpProtocol",
    "register_local_file_protocol",
    "set_api_base_url",
    "get_api_base_url",
    # OpenAPI Handlers
    "OpenApiHandler",
    "DefaultOpenApiHandler",
    "KubernetesOpenApiHandler",
    "GrafanaOpenApiHandler",
    "BearerTokenLoader",
    "DEFAULT_OPENAPI_HANDLERS",
    # Spec Strategies
    "SpecSourceStrategy",
    "LocalFileStrategy",
    "LiveURLStrategy",
    "SpecSource",
    # SSL
    "SSLConfigManager",
]

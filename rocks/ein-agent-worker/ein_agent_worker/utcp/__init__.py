"""UTCP (Universal Tool Calling Protocol) module for Ein Agent.

This module provides tools generated from OpenAPI specifications,
replacing the previous MCP-based approach.
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

__all__ = [
    "UTCPConfig",
    "UTCPServiceConfig",
    "KubernetesVersion",
    "CephVersion",
    "GrafanaVersion",
    "SUPPORTED_VERSIONS",
    "DEFAULT_VERSIONS",
    "ToolLoader",
    "create_utcp_tools",
]

"""UTCP configuration from environment variables.

Configuration Format:
    UTCP_SERVICES: Comma-separated list of service names (e.g., "kubernetes,grafana,ceph")
    UTCP_{SERVICE}_OPENAPI_URL: URL to the OpenAPI spec (required)
    UTCP_{SERVICE}_AUTH_TYPE: Authentication type - 'proxy', 'bearer', 'api_key', 'jwt' (default: proxy)
    UTCP_{SERVICE}_ENABLED: Enable/disable the service (default: true)
    UTCP_{SERVICE}_VERSION: Version of the spec to use (default: latest supported)

Example:
    export UTCP_SERVICES="kubernetes,grafana,ceph"
    export UTCP_KUBERNETES_OPENAPI_URL="http://localhost:8080/openapi/v2"
    export UTCP_KUBERNETES_AUTH_TYPE="proxy"
    export UTCP_KUBERNETES_VERSION="1.30"
    export UTCP_GRAFANA_OPENAPI_URL="https://grafana.example.com/api/swagger.json"
    export UTCP_GRAFANA_AUTH_TYPE="api_key"
"""

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Supported Versions
# =============================================================================

class KubernetesVersion(str, Enum):
    """Supported Kubernetes versions (N-2 support policy)."""
    V1_35 = "1.35"
    V1_34 = "1.34"
    V1_33 = "1.33"

    @classmethod
    def default(cls) -> "KubernetesVersion":
        return cls.V1_35


class CephVersion(str, Enum):
    """Supported Ceph versions (active stable releases)."""
    TENTACLE = "tentacle"  # v20.x
    SQUID = "squid"        # v19.x
    REEF = "reef"          # v18.x

    @classmethod
    def default(cls) -> "CephVersion":
        return cls.TENTACLE


class GrafanaVersion(str, Enum):
    """Supported Grafana versions."""
    V12 = "12"
    V11 = "11"

    @classmethod
    def default(cls) -> "GrafanaVersion":
        return cls.V12


# Mapping of service names to their version enums
SUPPORTED_VERSIONS = {
    "kubernetes": KubernetesVersion,
    "ceph": CephVersion,
    "grafana": GrafanaVersion,
}

# Default versions for each service
DEFAULT_VERSIONS: dict[str, str] = {
    "kubernetes": KubernetesVersion.default().value,
    "ceph": CephVersion.default().value,
    "grafana": GrafanaVersion.default().value,
}


@dataclass
class UTCPServiceConfig:
    """Configuration for a single UTCP service.

    Attributes:
        name: Unique name of the service (e.g., 'kubernetes', 'grafana')
        openapi_url: URL to the OpenAPI specification endpoint (for runtime calls)
        auth_type: Authentication type ('proxy', 'bearer', 'api_key', 'jwt')
        enabled: Whether the service is enabled
        version: Version of the OpenAPI spec to use (e.g., '1.30', 'reef', '11')
    """

    name: str
    openapi_url: str
    auth_type: str = "proxy"
    enabled: bool = True
    version: str = ""
    dynamic: bool = False  # If True, generate tools at runtime from OpenAPI URL


@dataclass
class UTCPConfig:
    """Global UTCP configuration loaded from environment variables."""

    services: List[UTCPServiceConfig] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> "UTCPConfig":
        """Load UTCP configuration from environment variables."""
        config = cls()
        services_str = os.getenv("UTCP_SERVICES", "")

        if not services_str:
            logger.info("UTCP_SERVICES not set, no UTCP services configured")
            return config

        service_names = [name.strip() for name in services_str.split(",") if name.strip()]

        if not service_names:
            logger.warning("UTCP_SERVICES is empty")
            return config

        logger.info(
            "Loading configuration for %d UTCP service(s): %s",
            len(service_names),
            ", ".join(service_names),
        )

        for service_name in service_names:
            service_config = cls._load_service_config(service_name)
            if service_config:
                config.services.append(service_config)
                logger.info(
                    "Loaded UTCP service config: %s (enabled=%s, dynamic=%s)",
                    service_name,
                    service_config.enabled,
                    service_config.dynamic,
                )

        return config

    @staticmethod
    def _load_service_config(service_name: str) -> Optional[UTCPServiceConfig]:
        """Load configuration for a single UTCP service."""
        service_key = service_name.upper().replace("-", "_")

        # Check if enabled
        enabled_key = f"UTCP_{service_key}_ENABLED"
        enabled = os.getenv(enabled_key, "true").lower() == "true"

        # Get OpenAPI URL (required)
        url_key = f"UTCP_{service_key}_OPENAPI_URL"
        openapi_url = os.getenv(url_key)

        if not openapi_url:
            logger.warning(
                "UTCP service '%s' missing required %s, skipping",
                service_name,
                url_key,
            )
            return None

        # Get auth type
        auth_type_key = f"UTCP_{service_key}_AUTH_TYPE"
        auth_type = os.getenv(auth_type_key, "proxy").lower()

        # Validate auth type
        valid_auth_types = ("proxy", "bearer", "api_key", "jwt")
        if auth_type not in valid_auth_types:
            logger.error(
                "UTCP service '%s' has invalid auth type '%s' (must be one of %s)",
                service_name,
                auth_type,
                valid_auth_types,
            )
            return None

        # Get version (for loading the correct spec file)
        version_key = f"UTCP_{service_key}_VERSION"
        version = os.getenv(version_key, "")

        # Get dynamic flag (generate tools at runtime from OpenAPI URL)
        dynamic_key = f"UTCP_{service_key}_DYNAMIC"
        dynamic = os.getenv(dynamic_key, "false").lower() == "true"

        return UTCPServiceConfig(
            name=service_name,
            openapi_url=openapi_url,
            auth_type=auth_type,
            enabled=enabled,
            version=version,
            dynamic=dynamic,
        )

    @property
    def enabled_services(self) -> List[UTCPServiceConfig]:
        """Get only enabled UTCP services."""
        return [s for s in self.services if s.enabled]

    def get_service(self, name: str) -> Optional[UTCPServiceConfig]:
        """Get configuration for a specific service by name."""
        for service in self.services:
            if service.name.lower() == name.lower():
                return service
        return None

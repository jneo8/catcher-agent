"""UTCP configuration from environment variables.

Configuration Format:
    UTCP_SERVICES: Comma-separated list of service names (e.g., "kubernetes,grafana,ceph")
    UTCP_{SERVICE}_OPENAPI_URL: URL to the OpenAPI spec (required)
    UTCP_{SERVICE}_AUTH_TYPE: Authentication type - 'proxy', 'bearer', 'api_key', 'jwt', 'kubeconfig' (default: proxy)
    UTCP_{SERVICE}_TOKEN: Bearer token for direct API access (required when AUTH_TYPE=bearer)
    UTCP_{SERVICE}_KUBECONFIG_CONTENT: Base64-encoded kubeconfig (required when AUTH_TYPE=kubeconfig)
    UTCP_{SERVICE}_INSECURE: Skip TLS verification (default: false)
    UTCP_{SERVICE}_ENABLED: Enable/disable the service (default: true)
    UTCP_{SERVICE}_VERSION: Version of the spec to use (default: latest supported)
    UTCP_{SERVICE}_SPEC_SOURCE: Where to load OpenAPI spec - 'local' or 'live' (default: local)

Example (Kubernetes with kubeconfig):
    export UTCP_SERVICES="kubernetes,grafana"
    export UTCP_KUBERNETES_OPENAPI_URL="https://10.0.0.1:6443/openapi/v2"
    export UTCP_KUBERNETES_AUTH_TYPE="kubeconfig"
    export UTCP_KUBERNETES_KUBECONFIG_CONTENT="<base64-encoded-kubeconfig>"
    export UTCP_KUBERNETES_INSECURE="true"
    export UTCP_KUBERNETES_VERSION="1.35"

Example (Grafana with bearer token):
    export UTCP_GRAFANA_OPENAPI_URL="https://grafana.example.com/api/swagger.json"
    export UTCP_GRAFANA_AUTH_TYPE="bearer"
    export UTCP_GRAFANA_TOKEN="glsa_xxxxxxxxxxxxx"
"""

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Approval Policies
# =============================================================================

class ApprovalPolicy(str, Enum):
    """Policy for tool call approval.

    - NEVER: Never require approval (trust all operations)
    - ALWAYS: Always require approval for every operation
    - WRITE_OPERATIONS: Require approval only for write operations (POST, PUT, PATCH, DELETE)
    - READ_ONLY: Require approval only for read operations (GET, LIST)
    """
    NEVER = "never"
    ALWAYS = "always"
    WRITE_OPERATIONS = "write_operations"
    READ_ONLY = "read_only"

    @classmethod
    def default(cls) -> "ApprovalPolicy":
        """Default policy is to approve writes only in production."""
        return cls.WRITE_OPERATIONS


# HTTP methods that are considered "write" operations
WRITE_HTTP_METHODS = {"POST", "PUT", "PATCH", "DELETE", "CREATE", "UPDATE"}

# HTTP methods that are considered "read" operations
READ_HTTP_METHODS = {"GET", "LIST", "WATCH", "READ"}


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


class PrometheusVersion(str, Enum):
    """Supported Prometheus versions."""
    V3_5_0 = "3.5.0"

    @classmethod
    def default(cls) -> "PrometheusVersion":
        return cls.V3_5_0


class LokiVersion(str, Enum):
    """Supported Loki versions."""
    V3 = "3"

    @classmethod
    def default(cls) -> "LokiVersion":
        return cls.V3


# Mapping of service names to their version enums
SUPPORTED_VERSIONS = {
    "kubernetes": KubernetesVersion,
    "ceph": CephVersion,
    "grafana": GrafanaVersion,
    "prometheus": PrometheusVersion,
    "loki": LokiVersion,
}

# Default versions for each service
DEFAULT_VERSIONS: dict[str, str] = {
    "kubernetes": KubernetesVersion.default().value,
    "ceph": CephVersion.default().value,
    "grafana": GrafanaVersion.default().value,
    "prometheus": PrometheusVersion.default().value,
    "loki": LokiVersion.default().value,
}


# =============================================================================
# Auth Validation Helpers
# =============================================================================

# Service-specific supported auth types mapping
# This avoids circular imports while maintaining service-specific validation
SERVICE_AUTH_TYPES: dict[str, tuple[str, ...]] = {
    "kubernetes": ("kubeconfig",),
    "grafana": ("bearer",),
    "prometheus": ("none", "bearer"),
    "loki": ("none", "bearer"),
    # Default for other services
    "_default": ("proxy", "bearer", "api_key", "jwt"),
}

# Service-specific supported spec sources
# Services without a live OpenAPI endpoint should only support 'local'
SERVICE_SPEC_SOURCES: dict[str, tuple[str, ...]] = {
    "loki": ("local",),        # Loki does not serve an OpenAPI spec
    "prometheus": ("local",),  # Prometheus spec is hand-curated from GitHub
    # Default: all sources available
    "_default": ("local", "live"),
}


def _get_supported_auth_types(service_name: str) -> tuple[str, ...]:
    """Get supported auth types for a service.

    Args:
        service_name: Service name

    Returns:
        Tuple of supported auth type strings
    """
    return SERVICE_AUTH_TYPES.get(service_name, SERVICE_AUTH_TYPES["_default"])


def _validate_kubeconfig_auth(service_name: str, service_key: str) -> bool:
    """Validate kubeconfig authentication configuration.

    Args:
        service_name: Service name for logging
        service_key: Uppercase service key for env var lookup

    Returns:
        True if valid, False otherwise
    """
    kubeconfig_key = f"UTCP_{service_key}_KUBECONFIG_CONTENT"
    kubeconfig_content = os.getenv(kubeconfig_key)

    if not kubeconfig_content:
        logger.error(
            "UTCP service '%s' has auth_type='kubeconfig' but %s is not set. "
            "Ensure Juju secret with kubeconfig-content is granted.",
            service_name,
            kubeconfig_key,
        )
        return False

    logger.info("UTCP service '%s' configured with kubeconfig authentication", service_name)
    return True


def _validate_bearer_auth(service_name: str, service_key: str) -> bool:
    """Validate bearer token authentication configuration.

    Args:
        service_name: Service name for logging
        service_key: Uppercase service key for env var lookup

    Returns:
        True if valid, False otherwise
    """
    token_key = f"UTCP_{service_key}_TOKEN"
    token = os.getenv(token_key, "")

    if not token:
        logger.error(
            "UTCP service '%s' has auth_type='bearer' but %s is not set",
            service_name,
            token_key,
        )
        return False

    logger.info("UTCP service '%s' configured with bearer token authentication", service_name)
    return True


@dataclass
class UTCPServiceConfig:
    """Configuration for a single UTCP service.

    Attributes:
        name: Unique name of the service (e.g., 'kubernetes', 'grafana')
        openapi_url: URL to the OpenAPI specification endpoint (for runtime calls)
        auth_type: Authentication type ('proxy', 'bearer', 'api_key', 'jwt')
        token: Bearer token for direct API access (required when auth_type='bearer')
        insecure: Skip TLS verification for self-signed certificates
        enabled: Whether the service is enabled
        version: Version of the OpenAPI spec to use (e.g., '1.30', 'reef', '11')
        dynamic: If True, generate tools at runtime from OpenAPI URL
        approval_policy: Policy for requiring human approval (never, always, write_operations, read_only)
    """

    name: str
    openapi_url: str
    auth_type: str = "proxy"
    token: str = ""
    insecure: bool = False
    enabled: bool = True
    version: str = ""
    dynamic: bool = False
    approval_policy: str = "always"  # Default: require approval for all operations (safest)
    spec_source: str = "local"  # Where to load spec: 'local' or 'live'


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

        # Validate auth type against service-specific supported types
        supported_auth_types = _get_supported_auth_types(service_name)
        if auth_type not in supported_auth_types:
            logger.error(
                "UTCP service '%s' has invalid auth type '%s' (supported: %s)",
                service_name,
                auth_type,
                ", ".join(supported_auth_types),
            )
            return None

        # Validate auth-specific requirements
        if auth_type == "kubeconfig":
            if not _validate_kubeconfig_auth(service_name, service_key):
                return None
        elif auth_type == "bearer":
            if not _validate_bearer_auth(service_name, service_key):
                return None

        # Get token for bearer auth (will be empty for kubeconfig)
        token_key = f"UTCP_{service_key}_TOKEN"
        token = os.getenv(token_key, "")

        # Get insecure flag (skip TLS verification)
        insecure_key = f"UTCP_{service_key}_INSECURE"
        insecure = os.getenv(insecure_key, "false").lower() == "true"

        # Get version (for loading the correct spec file)
        version_key = f"UTCP_{service_key}_VERSION"
        version = os.getenv(version_key, "")

        # Get dynamic flag (generate tools at runtime from OpenAPI URL)
        dynamic_key = f"UTCP_{service_key}_DYNAMIC"
        dynamic = os.getenv(dynamic_key, "false").lower() == "true"

        # Get approval policy (default: always require approval for safety)
        approval_policy_key = f"UTCP_{service_key}_APPROVAL_POLICY"
        approval_policy = os.getenv(approval_policy_key, "always").lower()

        # Validate approval policy
        valid_policies = {"never", "always", "write_operations", "read_only"}
        if approval_policy not in valid_policies:
            logger.warning(
                "UTCP service '%s' has invalid approval_policy '%s' (valid: %s), using default 'write_operations'",
                service_name,
                approval_policy,
                ", ".join(valid_policies),
            )
            approval_policy = "write_operations"

        # Get spec source strategy (local or live)
        spec_source_key = f"UTCP_{service_key}_SPEC_SOURCE"
        spec_source = os.getenv(spec_source_key, "local").lower()

        supported_spec_sources = SERVICE_SPEC_SOURCES.get(
            service_name, SERVICE_SPEC_SOURCES["_default"]
        )
        if spec_source not in supported_spec_sources:
            logger.warning(
                "UTCP service '%s' does not support spec_source '%s' (supported: %s), using default 'local'",
                service_name,
                spec_source,
                ", ".join(supported_spec_sources),
            )
            spec_source = "local"

        return UTCPServiceConfig(
            name=service_name,
            openapi_url=openapi_url,
            auth_type=auth_type,
            token=token,
            insecure=insecure,
            enabled=enabled,
            version=version,
            dynamic=dynamic,
            approval_policy=approval_policy,
            spec_source=spec_source,
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

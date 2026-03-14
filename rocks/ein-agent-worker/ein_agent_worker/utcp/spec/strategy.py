"""Spec source strategies for resolving where to load OpenAPI specs from.

Strategies determine whether specs are loaded from local files or live URLs.
Each UTCP service can be configured independently via UTCP_{SERVICE}_SPEC_SOURCE.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from ein_agent_worker.utcp.spec.resolver import find_spec_file, strip_openapi_suffix

logger = logging.getLogger(__name__)


@dataclass
class SpecSource:
    """Result of spec source resolution."""

    url: str  # file:// or https:// URL to load the spec from
    api_base_url: str  # Real API endpoint URL for making calls
    source_type: str  # "local" or "live"


class SpecSourceStrategy(ABC):
    """Strategy for resolving where to load OpenAPI specs from."""

    @abstractmethod
    def resolve(
        self,
        service_name: str,
        openapi_url: str,
        version: str,
        specs_dir: Path,
    ) -> SpecSource:
        """Resolve the spec source and API base URL.

        Args:
            service_name: Service name (e.g., 'kubernetes', 'grafana').
            openapi_url: The configured OpenAPI spec URL.
            version: Version string for local spec file lookup.
            specs_dir: Directory containing local spec files.

        Returns:
            SpecSource with the resolved URL and API base URL.
        """


class LocalFileStrategy(SpecSourceStrategy):
    """Only use local spec files. Raises if not found."""

    def resolve(
        self,
        service_name: str,
        openapi_url: str,
        version: str,
        specs_dir: Path,
    ) -> SpecSource:
        """Resolve spec source from local file only."""
        api_base_url = strip_openapi_suffix(openapi_url)

        local_spec_path = find_spec_file(specs_dir, service_name, version)
        if not local_spec_path or not local_spec_path.exists():
            raise FileNotFoundError(
                f"Local spec file not found for service '{service_name}' "
                f"in {specs_dir / service_name}"
            )

        logger.info(
            f"[{service_name}] Loading OpenAPI spec from LOCAL file: {local_spec_path}"
        )
        logger.info(f"[{service_name}] API calls will use base: {api_base_url}")
        return SpecSource(
            url=f"file://{local_spec_path}",
            api_base_url=api_base_url,
            source_type="local",
        )


class LiveURLStrategy(SpecSourceStrategy):
    """Only use live URLs, ignore local spec files."""

    def resolve(
        self,
        service_name: str,
        openapi_url: str,
        version: str,
        specs_dir: Path,
    ) -> SpecSource:
        """Resolve spec source from live URL only."""
        api_base_url = strip_openapi_suffix(openapi_url)

        logger.info(
            f"[{service_name}] Loading OpenAPI spec from LIVE URL: {openapi_url}"
        )
        logger.info(f"[{service_name}] API calls will use base: {api_base_url}")
        return SpecSource(
            url=openapi_url,
            api_base_url=api_base_url,
            source_type="live",
        )

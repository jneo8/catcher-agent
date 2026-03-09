"""UTCP tool loader - generates tools dynamically at runtime from OpenAPI specs.

Tools are created from OpenAPI specification files stored in the specs/ directory.
Only GET operations are exposed to ensure read-only access.
"""

import json
import logging
import re
import ssl
from pathlib import Path
from typing import Callable, List, Optional

from agents import function_tool
from utcp.data.variable_loader import VariableLoader
from utcp.utcp_client import UtcpClient

from ein_agent_worker.utcp.local_file_protocol import (
    register_local_file_protocol,
    set_api_base_url,
)

logger = logging.getLogger(__name__)

# Track if SSL verification has been disabled
_ssl_verification_disabled = False


def disable_ssl_verification() -> None:
    """Disable SSL certificate verification globally for aiohttp.

    WARNING: Only use this for development/testing with self-signed certs.
    This patches aiohttp to disable SSL verification.
    """
    global _ssl_verification_disabled
    if _ssl_verification_disabled:
        return

    import aiohttp

    # Create an insecure SSL context
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    # Patch aiohttp's TCPConnector to use insecure SSL by default
    _original_init = aiohttp.TCPConnector.__init__

    def _patched_init(self, *args, **kwargs):
        if "ssl" not in kwargs:
            kwargs["ssl"] = ssl_context
        _original_init(self, *args, **kwargs)

    aiohttp.TCPConnector.__init__ = _patched_init

    # Also patch ClientSession to pass ssl=False by default
    _original_request = aiohttp.ClientSession._request

    async def _patched_request(self, method, url, **kwargs):
        if "ssl" not in kwargs:
            kwargs["ssl"] = False
        return await _original_request(self, method, url, **kwargs)

    aiohttp.ClientSession._request = _patched_request

    _ssl_verification_disabled = True
    logger.warning("SSL verification disabled for aiohttp - use only for development")


class K8sBearerTokenLoader(VariableLoader):
    """Variable loader that provides K8s bearer token for direct API access.

    UTCP's OpenAPI security definitions require API key variables to be resolved.
    This loader provides the bearer token for k8s_API_KEY_* variables.
    """

    variable_loader_type: str = "k8s_bearer"
    token: str

    def __init__(self, token: str, **kwargs):
        super().__init__(token=token, **kwargs)

    def get(self, key: str) -> Optional[str]:
        """Return bearer token for k8s API key variables."""
        if re.match(r"k8s_API_KEY_\d+", key) or re.match(r"kubernetes_API_KEY_\d+", key):
            return f"Bearer {self.token}"
        return None


class GrafanaBearerTokenLoader(VariableLoader):
    """Variable loader that provides Grafana bearer token for direct API access.

    UTCP's OpenAPI security definitions require API key variables to be resolved.
    This loader provides the bearer token for grafana_API_KEY_* variables.
    """

    variable_loader_type: str = "grafana_bearer"
    token: str

    def __init__(self, token: str, **kwargs):
        super().__init__(token=token, **kwargs)

    def get(self, key: str) -> Optional[str]:
        """Return bearer token for Grafana API key variables."""
        if re.match(r"grafana_API_KEY_\d+", key):
            return f"Bearer {self.token}"
        return None

# Default specs directory (relative to this file)
DEFAULT_SPECS_DIR = Path(__file__).parent.parent.parent / "specs"


def _serialize_result(result) -> str:
    """Serialize a result to JSON string."""
    if isinstance(result, dict):
        return json.dumps(result, indent=2)
    elif isinstance(result, list):
        return json.dumps(result, indent=2)
    return str(result)


def create_utcp_tools(utcp_client: UtcpClient, service_name: str) -> List[Callable]:
    """Create UTCP tools with the client captured in closures.

    This follows the operator-agent-poc pattern with 4 tools:
    - list_{service}_operations: List available API operations with pagination
    - search_{service}_operations: Search for available API operations
    - get_{service}_operation_details: Get parameter schema for an operation
    - call_{service}_operation: Execute an API operation

    Args:
        utcp_client: The UTCP client instance to use for API calls
        service_name: Service name prefix (e.g., 'k8s', 'grafana', 'ceph')

    Returns:
        List of function tools for the agent
    """
    # Cache for all available tools (populated lazily on first use)
    _tools_cache: Optional[List] = None

    async def _get_all_tools():
        """Get all tools with caching to avoid repeated fetches."""
        nonlocal _tools_cache
        if _tools_cache is None:
            logger.info(f"[{service_name}] Loading all operations into cache (one-time operation)")
            _tools_cache = await utcp_client.search_tools(" ", limit=2000)
            logger.info(f"[{service_name}] Cached {len(_tools_cache)} operations")
        return _tools_cache

    @function_tool(name_override=f"list_{service_name}_operations")
    async def list_operations(tag: str = "", page: int = 1) -> str:
        """List available API operations with optional tag filtering and pagination.

        Use this to discover what operations are available. Returns only operation names as plain text.
        For details about specific operations, use get_{service}_operation_details.

        Args:
            tag: Optional tag filter (e.g., "v1", "core", "apps"). Leave empty to list all.
            page: Page number starting from 1 (default: 1, 200 operations per page)

        Returns:
            Plain text list of operation names (one per line) with pagination info.
        """
        try:
            # Use cached tools to avoid repeated fetches
            all_tools = await _get_all_tools()

            # Filter by tag if provided
            if tag:
                tag_lower = tag.lower()
                filtered_tools = [
                    t for t in all_tools
                    if hasattr(t, "tags") and any(tag_lower in str(tag).lower() for tag in t.tags)
                ]
            else:
                filtered_tools = all_tools

            # Apply pagination (200 per page)
            page_size = 200
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size

            paginated_tools = filtered_tools[start_idx:end_idx]
            total_count = len(filtered_tools)
            total_pages = (total_count + page_size - 1) // page_size

            # Return plain text list of names
            operation_names = [tool.name for tool in paginated_tools]

            result = f"Total: {total_count} operations | Page: {page}/{total_pages}\n\n"
            result += "\n".join(operation_names)

            return result
        except Exception as e:
            logger.error(f"Error listing {service_name} operations: {e}")
            return f"Error: {str(e)}"

    @function_tool(name_override=f"search_{service_name}_operations")
    async def search_operations(query: str, limit: int = 20) -> str:
        """Search for API operations matching the query.

        Args:
            query: Natural language description of what you want to do
                   (e.g., "list pods", "get dashboard", "cluster status")
            limit: Maximum number of operations to return (default: 20, max: 50)

        Returns:
            JSON list of available operations with their names and descriptions (truncated to 100 chars).
        """
        try:
            # Use cached tools to avoid repeated fetches
            all_tools = await _get_all_tools()

            query_lower = query.lower()
            query_words = query_lower.split()

            scored_tools = []

            for tool in all_tools:
                name_lower = tool.name.lower()
                desc_lower = tool.description.lower() if tool.description else ""

                score = 0

                # Exact name match
                if query_lower == name_lower.replace(f"{service_name}.", ""):
                    score += 100

                # Partial name match
                if query_lower in name_lower:
                    score += 50

                # Word matches in name
                matches_in_name = sum(1 for w in query_words if w in name_lower)
                score += matches_in_name * 10

                # Word matches in description
                matches_in_desc = sum(1 for w in query_words if w in desc_lower)
                score += matches_in_desc * 5

                if score > 0:
                    scored_tools.append((score, tool))

            # Sort by score descending
            scored_tools.sort(key=lambda x: x[0], reverse=True)

            # Take top 'limit' (cap at 50)
            actual_limit = min(limit, 50)
            top_tools = [t[1] for t in scored_tools[:actual_limit]]

            result = []
            for tool in top_tools:
                # Truncate description to 100 chars
                desc = tool.description if tool.description else ""
                if len(desc) > 100:
                    desc = desc[:100] + "..."

                result.append({
                    "name": tool.name,
                    "tags": tool.tags if hasattr(tool, "tags") else [],
                    "description": desc,
                })

            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error(f"Error searching {service_name} operations: {e}")
            return json.dumps({"error": str(e)})

    @function_tool(name_override=f"get_{service_name}_operation_details")
    async def get_operation_details(tool_name: str) -> str:
        """Get detailed parameter schema for a specific operation.

        Use this after finding an operation with search to know what parameters it requires.

        Args:
            tool_name: The exact name of the tool (e.g., "k8s.listCoreV1NamespacedPod")

        Returns:
            JSON schema of the tool's parameters.
        """
        try:
            # Use cached tools to avoid repeated fetches
            all_tools = await _get_all_tools()

            for tool in all_tools:
                if tool.name == tool_name:
                    # Serialize the schema
                    schema = _serialize_schema(tool.inputs) if hasattr(tool, "inputs") else {}

                    response = {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": schema,
                    }

                    return json.dumps(response, indent=2)

            return json.dumps({"error": f"Tool '{tool_name}' not found."})
        except Exception as e:
            logger.error(f"Error getting {service_name} operation details: {e}")
            return json.dumps({"error": str(e)})

    @function_tool(name_override=f"call_{service_name}_operation")
    async def call_operation(tool_name: str, arguments: str = "{}") -> str:
        f"""Execute a {service_name} API operation.

        IMPORTANT: This tool is ONLY for {service_name} operations. Tool names must start with '{service_name}.'
        If you need to call operations from other services, use their respective call_*_operation tools.

        Args:
            tool_name: The exact tool name from search results (must start with '{service_name}.')
            arguments: JSON string of arguments matching the tool's parameter schema

        Returns:
            The result of the API call as JSON
        """
        try:
            # Validate tool name belongs to this service
            # Tool names should be prefixed with service name (e.g., "kubernetes.listPods")
            expected_prefix = f"{service_name}."
            if not tool_name.startswith(expected_prefix):
                error_msg = (
                    f"Tool name mismatch: '{tool_name}' does not start with '{expected_prefix}'. "
                    f"You called 'call_{service_name}_operation' but provided a tool from a different service. "
                    f"Please use the correct tool function: call_{tool_name.split('.')[0]}_operation"
                )
                logger.error(f"[{service_name}] {error_msg}")
                return json.dumps({"error": error_msg})

            logger.debug(f"[{service_name}] Calling tool: {tool_name}")
            args = json.loads(arguments) if arguments else {}
            result = await utcp_client.call_tool(tool_name, args)
            return _serialize_result(result)
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON arguments: {e}"})
        except Exception as e:
            import traceback
            error_msg = str(e) or type(e).__name__
            logger.error(f"[{service_name}] Error calling operation {tool_name}: {error_msg}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return json.dumps({"error": error_msg})

    return [list_operations, search_operations, get_operation_details, call_operation]


def _serialize_schema(obj) -> dict:
    """Recursively serialize JsonSchema objects to dicts."""
    if hasattr(obj, "model_dump"):
        data = obj.model_dump()
        return _serialize_schema(data)
    elif isinstance(obj, dict):
        return {k: _serialize_schema(v) for k, v in obj.items() if v is not None}
    elif isinstance(obj, list):
        return [_serialize_schema(item) for item in obj]
    return obj


class ToolLoader:
    """Load UTCP tools for services."""

    def __init__(self, specs_dir: Optional[Path] = None):
        """Initialize the tool loader.

        Args:
            specs_dir: Directory containing OpenAPI spec files.
                       Defaults to specs/ directory relative to package.
        """
        self.specs_dir = specs_dir or DEFAULT_SPECS_DIR
        self._clients: dict[str, UtcpClient] = {}

    async def create_client(
        self,
        service_name: str,
        openapi_url: str,
        auth_type: str = "proxy",
        token: str = "",
        insecure: bool = False,
        version: str = "",
    ) -> UtcpClient:
        """Create a UTCP client for a service.

        Args:
            service_name: Service name (e.g., 'kubernetes', 'grafana')
            openapi_url: URL to the OpenAPI spec endpoint
            auth_type: Authentication type ('proxy', 'bearer', 'api_key', 'jwt')
            token: Bearer token for direct API access (required when auth_type='bearer')
            insecure: Skip TLS verification for self-signed certificates
            version: Version of the spec to use (for local spec file lookup)

        Returns:
            Configured UtcpClient instance
        """
        from utcp.data.utcp_client_config import UtcpClientConfig

        # Register our custom HTTP protocol that supports file:// URLs
        # This is idempotent and only registers once
        register_local_file_protocol()

        # Disable SSL verification if insecure mode is enabled
        if insecure:
            disable_ssl_verification()

        # Determine spec source: local file or live URL
        spec_source = openapi_url
        spec_type = "live"

        # Calculate API base URL (strip /openapi/v2 or /openapi/v3 suffix)
        # This is needed when OpenAPI specs don't specify basePath/servers
        api_base_url = openapi_url
        original_url = openapi_url
        for suffix in ["/openapi/v2", "/openapi/v3", "/openapi"]:
            if api_base_url.endswith(suffix):
                api_base_url = api_base_url[:-len(suffix)]
                logger.debug(
                    f"[{service_name}] Stripped '{suffix}' from URL: {original_url} → {api_base_url}"
                )
                break

        # Check for local spec file first
        local_spec_path = self.get_spec_path(service_name, version)
        if local_spec_path and local_spec_path.exists():
            spec_source = f"file://{local_spec_path}"
            spec_type = "local"
            # Register the real API base URL so that API calls go to the correct endpoint
            # (not the file:// URL which is only for loading the spec)
            set_api_base_url(service_name, api_base_url)
            logger.info(
                f"[{service_name}] Loading OpenAPI spec from LOCAL file: {local_spec_path}"
            )
            logger.info(
                f"[{service_name}] API calls will use base: {api_base_url}"
            )
        else:
            # For live URLs, also register the API base URL
            # This ensures proper base path when OpenAPI spec doesn't define basePath/servers
            set_api_base_url(service_name, api_base_url)
            logger.info(
                f"[{service_name}] Loading OpenAPI spec from LIVE URL: {openapi_url}"
            )
            logger.info(
                f"[{service_name}] API calls will use base: {api_base_url}"
            )
            if local_spec_path:
                logger.debug(
                    f"[{service_name}] Local spec path checked but not found: {local_spec_path}"
                )

        # Build the call template
        # NOTE: The 'url' field is used for loading the OpenAPI spec.
        # For local specs (file://), we register the real API base URL separately
        # so that OpenApiConverter can use it when converting operations.
        call_template: dict = {
            "name": service_name,
            "call_template_type": "http",
            "url": spec_source,
        }

        # Configure authentication for bearer token
        # K8sBearerTokenLoader resolves API key variables (e.g., kubernetes_API_KEY_0)
        # GrafanaBearerTokenLoader resolves API key variables (e.g., grafana_API_KEY_204)
        # referenced in the OpenAPI spec's security schemes.
        # This works because UTCP client creation now happens at worker startup,
        # outside Temporal's workflow sandbox.
        load_variables_from = []
        if auth_type == "bearer" and token:
            call_template["auth"] = {
                "auth_type": "api_key",
                "api_key": f"Bearer {token}",
                "var_name": "Authorization",
                "location": "header",
            }
            # Use service-specific variable loader
            if service_name == "grafana":
                load_variables_from.append(GrafanaBearerTokenLoader(token=token))
            else:
                load_variables_from.append(K8sBearerTokenLoader(token=token))
            logger.info(f"[{service_name}] Configured bearer token authentication")

        config_dict: dict = {
            "manual_call_templates": [call_template],
            "tool_search_strategy": {
                "tool_search_strategy_type": "tag_and_description_word_match"
            },
        }

        if load_variables_from:
            config_dict["load_variables_from"] = load_variables_from

        logger.info(f"[{service_name}] Creating UTCP client (spec_type={spec_type})")
        logger.info(f"[{service_name}] Final configuration:")
        logger.info(f"  - Spec source: {spec_source}")
        logger.info(f"  - API base URL: {api_base_url}")
        logger.info(f"  - Auth type: {auth_type}")
        logger.info(f"  - Insecure mode: {insecure}")

        config = UtcpClientConfig(**config_dict)
        client = await UtcpClient.create(config=config)
        self._clients[service_name] = client
        logger.info(f"[{service_name}] UTCP client created successfully")
        return client

    def load_service_tools(
        self,
        utcp_client: UtcpClient,
        service_name: str,
    ) -> List[Callable]:
        """Load tools for a service.

        Args:
            utcp_client: The UTCP client for this service
            service_name: Service name (e.g., 'kubernetes', 'grafana', 'ceph')

        Returns:
            List of function tools for the agent
        """
        return create_utcp_tools(utcp_client, service_name)

    def get_spec_path(self, service_name: str, version: str = "") -> Optional[Path]:
        """Get the path to a service's OpenAPI spec file.

        Args:
            service_name: Service name (e.g., 'kubernetes', 'grafana')
            version: Version string (e.g., '1.35', 'tentacle', '12')

        Returns:
            Path to spec file if it exists, None otherwise
        """
        from ein_agent_worker.utcp.config import DEFAULT_VERSIONS

        service_dir = self.specs_dir / service_name

        if not service_dir.exists():
            logger.warning(f"Spec directory not found: {service_dir}")
            return None

        # Use default version if not specified
        if not version:
            version = DEFAULT_VERSIONS.get(service_name.lower(), "")

        # Look for the version-specific file
        if version:
            for ext in [".json", ".yaml", ".yml"]:
                spec_path = service_dir / f"{version}{ext}"
                if spec_path.exists():
                    return spec_path

        # Fallback: find any available spec
        for ext in [".json", ".yaml", ".yml"]:
            spec_files = list(service_dir.glob(f"*{ext}"))
            if spec_files:
                return spec_files[0]

        logger.warning(f"No spec file found for {service_name}")
        return None

    def list_available_versions(self, service_name: str) -> List[str]:
        """List available spec versions for a service.

        Args:
            service_name: Service name (e.g., 'kubernetes', 'grafana')

        Returns:
            List of available version strings
        """
        service_dir = self.specs_dir / service_name

        if not service_dir.exists():
            return []

        versions = []
        for spec_file in service_dir.iterdir():
            if spec_file.suffix in [".json", ".yaml", ".yml"]:
                versions.append(spec_file.stem)

        return sorted(versions)

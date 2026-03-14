"""UTCP tool loader - generates tools dynamically at runtime from OpenAPI specs.

Tools are created from OpenAPI specification files (local or live URLs).
Only GET operations are exposed to ensure read-only access (filtered via handlers).
"""

import base64
import json
import logging
import os
from pathlib import Path
from typing import Callable, List, Optional

import yaml
from agents import function_tool
from utcp.utcp_client import UtcpClient

from ein_agent_worker.utcp.local_file_protocol import (
    register_local_file_protocol,
    set_api_base_url,
)
from ein_agent_worker.utcp.openapi_handlers import (
    DEFAULT_OPENAPI_HANDLERS,
    OpenApiHandler,
)
from ein_agent_worker.utcp.openapi_handlers.default import DefaultOpenApiHandler
from ein_agent_worker.utcp.spec.strategy import (
    LocalFileStrategy,
    LiveURLStrategy,
    SpecSourceStrategy,
)
from ein_agent_worker.utcp.ssl_config import SSLConfigManager

logger = logging.getLogger(__name__)

# Default specs directory (relative to this file)
DEFAULT_SPECS_DIR = Path(__file__).parent.parent.parent / "specs"


def _serialize_result(result) -> str:
    """Serialize a result to JSON string."""
    if isinstance(result, (dict, list)):
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


def _extract_token_from_kubeconfig(kubeconfig_data: dict, service_name: str) -> str:
    """Extract bearer token from kubeconfig dictionary (IN MEMORY).

    This method processes kubeconfig entirely in memory without writing to disk,
    ensuring credentials are never persisted to the filesystem.

    Args:
        kubeconfig_data: Parsed kubeconfig as dictionary
        service_name: Service name for logging

    Returns:
        Bearer token string (without "Bearer " prefix)

    Raises:
        ValueError: If token cannot be extracted from kubeconfig
    """
    try:
        # Get current context
        current_context = kubeconfig_data.get('current-context')
        if not current_context:
            raise ValueError("No current-context found in kubeconfig")

        # Find context and user mappings
        contexts = {c['name']: c['context'] for c in kubeconfig_data.get('contexts', [])}
        users = {u['name']: u['user'] for u in kubeconfig_data.get('users', [])}

        if current_context not in contexts:
            raise ValueError(f"Current context '{current_context}' not found in kubeconfig")

        context = contexts[current_context]
        user_name = context.get('user')

        if not user_name:
            raise ValueError(f"No user found in context '{current_context}'")

        user = users.get(user_name, {})
        if not user:
            raise ValueError(f"User '{user_name}' not found in kubeconfig users list")

        # Extract token from user config
        token = user.get('token', '')

        if not token:
            # Fallback: check for tokenFile reference (less secure, requires disk read)
            token_file = user.get('tokenFile', '')
            if token_file:
                logger.warning(
                    f"[{service_name}] kubeconfig uses tokenFile reference: {token_file}. "
                    "For better security, embed the token directly in kubeconfig."
                )
                try:
                    with open(token_file, 'r') as f:
                        token = f.read().strip()
                except Exception as e:
                    raise ValueError(f"Failed to read token from {token_file}: {e}")

        if not token:
            raise ValueError(
                f"No token found for user '{user_name}'. "
                "Ensure kubeconfig contains 'token' field in user configuration."
            )

        logger.debug(f"[{service_name}] Token extracted successfully (length: {len(token)} chars)")
        return token

    except Exception as e:
        logger.error(f"[{service_name}] Kubeconfig parsing error: {e}")
        raise ValueError(f"Kubeconfig parsing failed: {e}")


class ToolLoader:
    """Load UTCP tools for services.

    Orchestrates client creation using injected strategies and handlers:
    - SpecSourceStrategy: determines where to load specs from (local/live)
    - OpenApiHandler: provides service-specific auth and spec preprocessing
    - SSLConfigManager: manages SSL verification settings
    """

    # Map spec_source config values to strategy classes
    _SPEC_STRATEGIES: dict[str, type[SpecSourceStrategy]] = {
        "local": LocalFileStrategy,
        "live": LiveURLStrategy,
    }

    def __init__(
        self,
        specs_dir: Optional[Path] = None,
        openapi_handlers: Optional[dict[str, OpenApiHandler]] = None,
        ssl_manager: Optional[SSLConfigManager] = None,
    ):
        """Initialize the tool loader.

        Args:
            specs_dir: Directory containing OpenAPI spec files.
                       Defaults to specs/ directory relative to package.
            openapi_handlers: Map of service name to OpenApiHandler.
                              Defaults to DEFAULT_OPENAPI_HANDLERS.
            ssl_manager: SSL configuration manager.
                         Defaults to a new SSLConfigManager instance.
        """
        self.specs_dir = specs_dir or DEFAULT_SPECS_DIR
        self.openapi_handlers = openapi_handlers or DEFAULT_OPENAPI_HANDLERS
        self.ssl_manager = ssl_manager or SSLConfigManager()
        self._clients: dict[str, UtcpClient] = {}

    async def create_client(
        self,
        service_name: str,
        openapi_url: str,
        auth_type: str = "proxy",
        token: str = "",
        insecure: bool = False,
        version: str = "",
        spec_source: str = "local",
    ) -> UtcpClient:
        """Create a UTCP client for a service.

        Args:
            service_name: Service name (e.g., 'kubernetes', 'grafana')
            openapi_url: URL to the OpenAPI spec endpoint
            auth_type: Authentication type ('proxy', 'bearer', 'api_key', 'jwt')
            token: Bearer token for direct API access (required when auth_type='bearer')
            insecure: Skip TLS verification for self-signed certificates
            version: Version of the spec to use (for local spec file lookup)
            spec_source: Where to load the spec from - 'local' or 'live'

        Returns:
            Configured UtcpClient instance
        """
        from utcp.data.utcp_client_config import UtcpClientConfig

        # 1. Register protocol (idempotent)
        register_local_file_protocol()

        # 2. Configure SSL if needed
        if insecure:
            self.ssl_manager.disable_ssl_verification()

        # 3. Resolve spec source using per-service strategy
        strategy_cls = self._SPEC_STRATEGIES.get(spec_source, LocalFileStrategy)
        strategy = strategy_cls()
        resolved_source = strategy.resolve(
            service_name, openapi_url, version, self.specs_dir
        )
        set_api_base_url(service_name, resolved_source.api_base_url)

        # 4. Get OpenAPI handler
        handler = self.openapi_handlers.get(
            service_name, DefaultOpenApiHandler(service_name)
        )

        # 5. Build call template
        call_template: dict = {
            "name": service_name,
            "call_template_type": "http",
            "url": resolved_source.url,
        }

        # 6. Configure auth using handler
        load_variables_from = []
        bearer_token = None

        if auth_type == "kubeconfig":
            # KUBECONFIG AUTH: Extract token from base64-encoded kubeconfig (IN MEMORY)
            kubeconfig_env_key = f"UTCP_{service_name.upper().replace('-', '_')}_KUBECONFIG_CONTENT"
            kubeconfig_b64 = os.getenv(kubeconfig_env_key)

            if not kubeconfig_b64:
                raise ValueError(
                    f"[{service_name}] {kubeconfig_env_key} environment variable not found. "
                    "Ensure Juju secret with kubeconfig-content is granted."
                )

            # Decode and parse kubeconfig (IN MEMORY - NO DISK WRITE)
            try:
                kubeconfig_yaml_str = base64.b64decode(kubeconfig_b64).decode('utf-8')
                kubeconfig_data = yaml.safe_load(kubeconfig_yaml_str)
                bearer_token = _extract_token_from_kubeconfig(kubeconfig_data, service_name)
                logger.info(f"[{service_name}] Token extracted from kubeconfig (in-memory, no disk write)")
            except Exception as e:
                raise ValueError(f"[{service_name}] Failed to process kubeconfig: {e}")

        elif auth_type == "bearer":
            # BEARER AUTH: Read token directly from environment or parameter
            token_env_key = f"UTCP_{service_name.upper().replace('-', '_')}_TOKEN"
            bearer_token = os.getenv(token_env_key) or token

            if not bearer_token:
                raise ValueError(
                    f"[{service_name}] {token_env_key} environment variable not found. "
                    "Ensure Juju secret with token is granted."
                )

            logger.info(f"[{service_name}] Using bearer token from environment")

        elif auth_type == "none":
            # NO AUTH: Service requires no authentication (e.g., Prometheus behind proxy)
            logger.info(f"[{service_name}] No authentication configured (auth_type=none)")

        # Configure bearer auth (unified for both kubeconfig-extracted and direct tokens)
        if bearer_token:
            call_template["auth"] = {
                "auth_type": "api_key",
                "api_key": f"Bearer {bearer_token}",
                "var_name": "Authorization",
                "location": "header",
            }

            variable_loader = handler.get_variable_loader(bearer_token)
            if variable_loader:
                load_variables_from.append(variable_loader)

            logger.info(f"[{service_name}] Configured bearer token authentication")

        # 7. Create config and client
        config_dict: dict = {
            "manual_call_templates": [call_template],
            "tool_search_strategy": {
                "tool_search_strategy_type": "tag_and_description_word_match"
            },
        }
        if load_variables_from:
            config_dict["load_variables_from"] = load_variables_from

        logger.info(f"[{service_name}] Creating UTCP client (spec_source={spec_source})")
        logger.info(f"[{service_name}] Final configuration:")
        logger.info(f"  - Spec URL: {resolved_source.url}")
        logger.info(f"  - API base URL: {resolved_source.api_base_url}")
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

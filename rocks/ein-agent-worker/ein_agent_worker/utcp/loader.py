"""UTCP tool loader - generates tools dynamically at runtime from OpenAPI specs.

Tools are created from OpenAPI specification files stored in the specs/ directory.
Only GET operations are exposed to ensure read-only access.
"""

import json
import logging
from pathlib import Path
from typing import Callable, List, Optional

from agents import function_tool
from utcp.utcp_client import UtcpClient

logger = logging.getLogger(__name__)

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

    This follows the operator-agent-poc pattern with 3 tools:
    - search_{service}_operations: Search for available API operations
    - get_{service}_operation_details: Get parameter schema for an operation
    - call_{service}_operation: Execute an API operation

    Args:
        utcp_client: The UTCP client instance to use for API calls
        service_name: Service name prefix (e.g., 'k8s', 'grafana', 'ceph')

    Returns:
        List of function tools for the agent
    """

    @function_tool(name_override=f"search_{service_name}_operations")
    async def search_operations(query: str, limit: int = 20) -> str:
        """Search for API operations matching the query.

        Args:
            query: Natural language description of what you want to do
                   (e.g., "list pods", "get dashboard", "cluster status")
            limit: Maximum number of operations to return (default: 20)

        Returns:
            JSON list of available operations with their names and descriptions.
        """
        try:
            # Fetch all tools for client-side scoring
            all_tools = await utcp_client.search_tools(" ", limit=2000)

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

            # Take top 'limit'
            top_tools = [t[1] for t in scored_tools[:limit]]

            result = []
            for tool in top_tools:
                result.append({
                    "name": tool.name,
                    "tags": tool.tags if hasattr(tool, "tags") else [],
                    "description": tool.description,
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
            tools = await utcp_client.search_tools(tool_name, limit=10)

            for tool in tools:
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
        """Execute an API operation.

        Args:
            tool_name: The exact tool name from search results
            arguments: JSON string of arguments matching the tool's parameter schema

        Returns:
            The result of the API call as JSON
        """
        try:
            args = json.loads(arguments) if arguments else {}
            result = await utcp_client.call_tool(tool_name, args)
            return _serialize_result(result)
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON arguments: {e}"})
        except Exception as e:
            logger.error(f"Error calling {service_name} operation {tool_name}: {e}")
            return json.dumps({"error": str(e)})

    return [search_operations, get_operation_details, call_operation]


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

    async def create_client(self, service_name: str, openapi_url: str) -> UtcpClient:
        """Create a UTCP client for a service.

        Args:
            service_name: Service name (e.g., 'kubernetes', 'grafana')
            openapi_url: URL to the OpenAPI spec endpoint

        Returns:
            Configured UtcpClient instance
        """
        from utcp.data.utcp_client_config import UtcpClientConfig

        config = UtcpClientConfig(
            manual_call_templates=[{
                "name": service_name,
                "call_template_type": "http",
                "url": openapi_url,
            }],
            tool_search_strategy={
                "tool_search_strategy_type": "tag_and_description_word_match"
            },
        )

        client = await UtcpClient.create(config=config)
        self._clients[service_name] = client
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

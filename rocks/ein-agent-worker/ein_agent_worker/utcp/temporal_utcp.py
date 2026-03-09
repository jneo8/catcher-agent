"""Temporal UTCP integration - run UTCP operations as Temporal activities.

This module provides UTCP tool execution within Temporal workflows by running
each UTCP operation as a separate activity. This allows network I/O to happen
outside the workflow sandbox.

Pattern follows the MCP integration in temporalio.contrib.openai_agents._mcp.
"""

import dataclasses
import json
import logging
from collections.abc import Callable, Sequence
from datetime import timedelta
from typing import Any

from agents import function_tool
from temporalio import activity, workflow
from temporalio.workflow import ActivityConfig

from ein_agent_worker.utcp import registry as utcp_registry

logger = logging.getLogger(__name__)


# =============================================================================
# Activity Arguments
# =============================================================================


@dataclasses.dataclass
class _ListOperationsArguments:
    service_name: str
    tag: str = ""


@dataclasses.dataclass
class _SearchOperationsArguments:
    service_name: str
    query: str
    limit: int = 20


@dataclasses.dataclass
class _GetOperationDetailsArguments:
    service_name: str
    tool_name: str


@dataclasses.dataclass
class _CallOperationArguments:
    service_name: str
    tool_name: str
    arguments: str  # JSON string


# =============================================================================
# Activity Definitions
# =============================================================================


def get_utcp_activities() -> Sequence[Callable]:
    """Get UTCP activity functions to register with the worker.

    Returns:
        Sequence of activity functions
    """

    @activity.defn(name="utcp-list-operations")
    async def list_operations(args: _ListOperationsArguments) -> str:
        """List all available API operations with optional tag filtering."""
        client = utcp_registry.get_client(args.service_name)
        if not client:
            return json.dumps({"error": f"UTCP service '{args.service_name}' not found"})

        try:
            # Fetch all tools using a broad search
            all_tools = await client.search_tools(" ", limit=2000)

            # Filter by tag if provided
            if args.tag:
                tag_lower = args.tag.lower()
                filtered_tools = [
                    t for t in all_tools
                    if hasattr(t, "tags") and any(tag_lower in str(tag).lower() for tag in t.tags)
                ]
            else:
                filtered_tools = all_tools

            result = []
            for tool in filtered_tools:
                result.append({
                    "name": tool.name,
                    "tags": tool.tags if hasattr(tool, "tags") else [],
                    "description": tool.description,
                })

            response = {
                "total": len(result),
                "operations": result,
            }

            return json.dumps(response, indent=2)
        except Exception as e:
            logger.error(f"Error listing {args.service_name} operations: {e}")
            return json.dumps({"error": str(e)})

    @activity.defn(name="utcp-search-operations")
    async def search_operations(args: _SearchOperationsArguments) -> str:
        """Search for API operations matching the query."""
        client = utcp_registry.get_client(args.service_name)
        if not client:
            return json.dumps({"error": f"UTCP service '{args.service_name}' not found"})

        try:
            # Fetch all tools for client-side scoring
            all_tools = await client.search_tools(" ", limit=2000)

            query_lower = args.query.lower()
            query_words = query_lower.split()

            scored_tools = []
            for tool in all_tools:
                name_lower = tool.name.lower()
                desc_lower = tool.description.lower() if tool.description else ""

                score = 0

                # Exact name match
                if query_lower == name_lower.replace(f"{args.service_name}.", ""):
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
            top_tools = [t[1] for t in scored_tools[: args.limit]]

            result = []
            for tool in top_tools:
                result.append(
                    {
                        "name": tool.name,
                        "tags": tool.tags if hasattr(tool, "tags") else [],
                        "description": tool.description,
                    }
                )

            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error(f"Error searching {args.service_name} operations: {e}")
            return json.dumps({"error": str(e)})

    @activity.defn(name="utcp-get-operation-details")
    async def get_operation_details(args: _GetOperationDetailsArguments) -> str:
        """Get detailed parameter schema for a specific operation."""
        client = utcp_registry.get_client(args.service_name)
        if not client:
            return json.dumps({"error": f"UTCP service '{args.service_name}' not found"})

        try:
            tools = await client.search_tools(args.tool_name, limit=10)

            for tool in tools:
                if tool.name == args.tool_name:
                    schema = _serialize_schema(tool.inputs) if hasattr(tool, "inputs") else {}

                    response = {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": schema,
                    }

                    return json.dumps(response, indent=2)

            return json.dumps({"error": f"Tool '{args.tool_name}' not found."})
        except Exception as e:
            logger.error(f"Error getting {args.service_name} operation details: {e}")
            return json.dumps({"error": str(e)})

    @activity.defn(name="utcp-call-operation")
    async def call_operation(args: _CallOperationArguments) -> str:
        """Execute an API operation."""
        client = utcp_registry.get_client(args.service_name)
        if not client:
            return json.dumps({"error": f"UTCP service '{args.service_name}' not found"})

        try:
            # Validate tool name belongs to this service
            # Tool names should be prefixed with service name (e.g., "kubernetes.listPods")
            expected_prefix = f"{args.service_name}."
            if not args.tool_name.startswith(expected_prefix):
                error_msg = (
                    f"Tool name mismatch: '{args.tool_name}' does not start with '{expected_prefix}'. "
                    f"You called 'call_{args.service_name}_operation' but provided a tool from a different service. "
                    f"Please use the correct tool function: call_{args.tool_name.split('.')[0]}_operation"
                )
                logger.error(f"[{args.service_name}] {error_msg}")
                return json.dumps({"error": error_msg})

            logger.debug(f"[{args.service_name}] Calling tool: {args.tool_name}")
            arguments = json.loads(args.arguments) if args.arguments else {}
            result = await client.call_tool(args.tool_name, arguments)
            return _serialize_result(result)
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON arguments: {e}"})
        except Exception as e:
            import traceback

            error_msg = str(e) or type(e).__name__
            logger.error(f"[{args.service_name}] Error calling operation {args.tool_name}: {error_msg}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return json.dumps({"error": error_msg})

    return (list_operations, search_operations, get_operation_details, call_operation)


# =============================================================================
# Workflow Tool Wrappers
# =============================================================================


def create_utcp_workflow_tools(
    service_name: str,
    config: ActivityConfig | None = None,
) -> list[Callable]:
    """Create UTCP tools for use in Temporal workflows.

    These tools execute UTCP operations as activities, allowing network I/O
    to happen outside the workflow sandbox.

    Args:
        service_name: UTCP service name (e.g., 'kubernetes')
        config: Optional activity configuration

    Returns:
        List of function tools for the agent
    """
    _config = config or ActivityConfig(start_to_close_timeout=timedelta(seconds=60))

    @function_tool(name_override=f"list_{service_name}_operations")
    async def list_operations(tag: str = "") -> str:
        """List all available API operations with optional tag filtering.

        Use this to discover what operations are available without searching.
        Returns ALL operations (no pagination).

        Args:
            tag: Optional tag filter (e.g., "v1", "core", "apps"). Leave empty to list all.

        Returns:
            JSON list of available operations with their names, tags, and descriptions.
        """
        return await workflow.execute_activity(
            "utcp-list-operations",
            _ListOperationsArguments(service_name, tag),
            result_type=str,
            **_config,
        )

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
        return await workflow.execute_activity(
            "utcp-search-operations",
            _SearchOperationsArguments(service_name, query, limit),
            result_type=str,
            **_config,
        )

    @function_tool(name_override=f"get_{service_name}_operation_details")
    async def get_operation_details(tool_name: str) -> str:
        """Get detailed parameter schema for a specific operation.

        Use this after finding an operation with search to know what parameters it requires.

        Args:
            tool_name: The exact name of the tool (e.g., "kubernetes.listCoreV1NamespacedPod")

        Returns:
            JSON schema of the tool's parameters.
        """
        return await workflow.execute_activity(
            "utcp-get-operation-details",
            _GetOperationDetailsArguments(service_name, tool_name),
            result_type=str,
            **_config,
        )

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
        return await workflow.execute_activity(
            "utcp-call-operation",
            _CallOperationArguments(service_name, tool_name, arguments),
            result_type=str,
            **_config,
        )

    return [list_operations, search_operations, get_operation_details, call_operation]


# =============================================================================
# Helpers
# =============================================================================


def _serialize_result(result: Any) -> str:
    """Serialize a result to JSON string."""
    if isinstance(result, dict):
        return json.dumps(result, indent=2)
    elif isinstance(result, list):
        return json.dumps(result, indent=2)
    return str(result)


def _serialize_schema(obj: Any) -> dict:
    """Recursively serialize JsonSchema objects to dicts."""
    if hasattr(obj, "model_dump"):
        data = obj.model_dump()
        return _serialize_schema(data)
    elif isinstance(obj, dict):
        return {k: _serialize_schema(v) for k, v in obj.items() if v is not None}
    elif isinstance(obj, list):
        return [_serialize_schema(item) for item in obj]
    return obj

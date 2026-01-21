"""Configuration for MCP (Model Context Protocol) activities."""

from datetime import timedelta
from temporalio.common import RetryPolicy
from temporalio.workflow import ActivityConfig

def get_mcp_activity_config() -> ActivityConfig:
    """Get the activity configuration for MCP server operations.

    This configures a strict retry policy to fail fast on errors (like 401 Unauthorized),
    preventing infinite retry loops which can hang the workflow.
    """
    return ActivityConfig(
        # Limit retries to 2 attempts to fail fast on auth errors
        retry_policy=RetryPolicy(maximum_attempts=2),
        # Default timeout for MCP operations
        start_to_close_timeout=timedelta(minutes=1),
    )

"""Activity functions for Temporal workflows.

Note: The multi-agent investigation activities have been removed.
Agent orchestration now happens in workflows (durable execution),
following Temporal + OpenAI Agents SDK best practices.

MCP operations are handled automatically by the OpenAIAgentsPlugin
using stateless_mcp_server() references in workflow context.
"""

# No activities exported - agent orchestration moved to workflows
__all__ = []

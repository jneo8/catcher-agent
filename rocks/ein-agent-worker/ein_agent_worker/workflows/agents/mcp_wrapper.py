from typing import Any, List
import logging
from agents.mcp import MCPServer
from mcp.types import CallToolResult, TextContent, Tool as MCPTool, ListPromptsResult, GetPromptResult
from temporalio import activity
from temporalio.exceptions import ActivityError, ApplicationError
from agents import AgentBase, RunContextWrapper

logger = logging.getLogger(__name__)

class SafeMCPServer(MCPServer):
    """Wrapper around MCPServer that catches exceptions in call_tool and returns them as error results."""

    def __init__(self, wrapped: MCPServer):
        self._wrapped = wrapped
        super().__init__()

    @property
    def name(self) -> str:
        return self._wrapped.name

    async def connect(self) -> None:
        await self._wrapped.connect()

    async def cleanup(self) -> None:
        await self._wrapped.cleanup()

    async def list_tools(
        self,
        run_context: RunContextWrapper[Any] | None = None,
        agent: AgentBase | None = None,
    ) -> list[MCPTool]:
        return await self._wrapped.list_tools(run_context, agent)

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any] | None
    ) -> CallToolResult:
        try:
            return await self._wrapped.call_tool(tool_name, arguments)
        except Exception as e:
            error_msg = f"Error calling tool '{tool_name}': {str(e)}"
            logger.error(error_msg, exc_info=True)
            
            # Extract deeper cause if it's an ActivityError
            if isinstance(e, ActivityError) and e.cause:
                error_msg += f" (Cause: {str(e.cause)})"
                
            return CallToolResult(
                content=[TextContent(type="text", text=error_msg)],
                isError=True
            )

    async def list_prompts(self) -> ListPromptsResult:
        return await self._wrapped.list_prompts()

    async def get_prompt(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> GetPromptResult:
        return await self._wrapped.get_prompt(name, arguments)


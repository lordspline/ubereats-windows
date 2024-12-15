import asyncio
from typing import ClassVar, Literal
from anthropic.types.beta import BetaToolBash20241022Param
from .base import BaseAnthropicTool, ToolError, ToolResult

class BashTool(BaseAnthropicTool):
    """A tool that allows the agent to run terminal commands."""

    name: ClassVar[Literal["bash"]] = "bash"
    api_type: ClassVar[Literal["bash_20241022"]] = "bash_20241022"

    async def __call__(self, command: str | None = None, restart: bool = False, **kwargs):
        """Execute a terminal command."""
        if not command:
            raise ToolError("no command provided.")

        try:
            # Create subprocess
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # Wait for command to complete and get output
            stdout, stderr = await process.communicate()

            # Decode output and error
            output = stdout.decode().strip() if stdout else ""
            error = stderr.decode().strip() if stderr else ""

            return ToolResult(output=output, error=error)

        except Exception as e:
            return ToolResult(error=str(e))

    def to_params(self) -> BetaToolBash20241022Param:
        return {
            "type": self.api_type,
            "name": self.name,
        }
